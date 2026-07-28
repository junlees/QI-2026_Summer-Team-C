import random
import shutil
from abc import abstractmethod
from pathlib import Path

import numpy as np
import torch
from numpy import inf
from logger import TensorboardWriter


class BaseTrainer:
    """
    Base class for all trainers
    """
    def __init__(self, model, criterion, metric_ftns, optimizer, config, lr_scheduler=None):
        self.config = config
        self.logger = config.get_logger('trainer', config['trainer']['verbosity'])

        self.model = model
        self.criterion = criterion
        self.metric_ftns = metric_ftns
        self.optimizer = optimizer
        self.lr_scheduler = lr_scheduler

        cfg_trainer = config['trainer']
        self.epochs = cfg_trainer['epochs']
        self.save_period = cfg_trainer['save_period']
        self.monitor = cfg_trainer.get('monitor', 'off')

        # configuration to monitor model performance and save best
        if self.monitor == 'off':
            self.mnt_mode = 'off'
            self.mnt_best = 0
        else:
            self.mnt_mode, self.mnt_metric = self.monitor.split()
            assert self.mnt_mode in ['min', 'max']

            self.mnt_best = inf if self.mnt_mode == 'min' else -inf
            self.early_stop = cfg_trainer.get('early_stop', inf)
            if self.early_stop <= 0:
                self.early_stop = inf

        self.start_epoch = 1
        self.not_improved_count = 0

        self.checkpoint_dir = config.save_dir

        # setup visualization writer instance                
        self.writer = TensorboardWriter(config.log_dir, self.logger, cfg_trainer['tensorboard'])

        if config.resume is not None:
            self._resume_checkpoint(config.resume)

    @abstractmethod
    def _train_epoch(self, epoch):
        """
        Training logic for an epoch

        :param epoch: Current epoch number
        """
        raise NotImplementedError

    def train(self):
        """
        Full training logic
        """
        for epoch in range(self.start_epoch, self.epochs + 1):
            result = self._train_epoch(epoch)

            # save logged informations into log dict
            log = {'epoch': epoch}
            log.update(result)

            # print logged informations to the screen
            for key, value in log.items():
                self.logger.info('    {:15s}: {}'.format(str(key), value))

            # evaluate model performance according to configured metric, save best checkpoint as model_best
            best = False
            if self.mnt_mode != 'off':
                try:
                    # check whether model performance improved or not, according to specified metric(mnt_metric)
                    improved = (self.mnt_mode == 'min' and log[self.mnt_metric] <= self.mnt_best) or \
                               (self.mnt_mode == 'max' and log[self.mnt_metric] >= self.mnt_best)
                except KeyError:
                    self.logger.warning("Warning: Metric '{}' is not found. "
                                        "Model performance monitoring is disabled.".format(self.mnt_metric))
                    self.mnt_mode = 'off'
                    improved = False

                if improved:
                    self.mnt_best = log[self.mnt_metric]
                    self.not_improved_count = 0
                    best = True
                else:
                    self.not_improved_count += 1

                if self.not_improved_count > self.early_stop:
                    self.logger.info("Validation performance didn\'t improve for {} epochs. "
                                     "Training stops.".format(self.early_stop))
                    break

            if epoch % self.save_period == 0:
                self._save_checkpoint(epoch, save_best=best)

    def _save_checkpoint(self, epoch, save_best=False):
        """
        Saving checkpoints

        :param epoch: current epoch number
        :param log: logging information of the epoch
        :param save_best: if True, rename the saved checkpoint to 'model_best.pth'
        """
        arch = type(self.model).__name__
        state = {
            'arch': arch,
            'epoch': epoch,
            'state_dict': self.model.state_dict(),
            'optimizer': self.optimizer.state_dict(),
            'lr_scheduler': self.lr_scheduler.state_dict() if self.lr_scheduler is not None else None,
            'amp_scaler': self.scaler.state_dict() if getattr(self, 'scaler', None) is not None else None,
            'monitor_best': self.mnt_best,
            'not_improved_count': self.not_improved_count,
            'rng_state': self._rng_state(),
            'config': self.config
        }
        filename = str(self.checkpoint_dir / 'checkpoint-epoch{}.pth'.format(epoch))
        torch.save(state, filename)
        self.logger.info("Saving checkpoint: {} ...".format(filename))
        if save_best:
            best_path = str(self.checkpoint_dir / 'model_best.pth')
            torch.save(state, best_path)
            self.logger.info("Saving current best: model_best.pth ...")

    def _resume_checkpoint(self, resume_path):
        """
        Resume from saved checkpoints

        :param resume_path: Checkpoint path to be resumed
        """
        resume_path = str(resume_path)
        self.logger.info("Loading checkpoint: {} ...".format(resume_path))
        # weights_only=False: 체크포인트에 ConfigParser 객체가 저장됨 (PyTorch 2.6+ 대응)
        checkpoint = torch.load(resume_path, map_location='cpu', weights_only=False)
        self.start_epoch = checkpoint['epoch'] + 1
        self.mnt_best = checkpoint['monitor_best']
        self.not_improved_count = checkpoint.get('not_improved_count', 0)

        # load architecture params from checkpoint.
        if checkpoint['config']['arch'] != self.config['arch']:
            self.logger.warning("Warning: Architecture configuration given in config file is different from that of "
                                "checkpoint. This may yield an exception while state_dict is being loaded.")
        self.model.load_state_dict(checkpoint['state_dict'])

        # load optimizer state from checkpoint only when optimizer type is not changed.
        optimizer_resumed = checkpoint['config']['optimizer']['type'] == self.config['optimizer']['type']
        if not optimizer_resumed:
            self.logger.warning("Warning: Optimizer type given in config file is different from that of checkpoint. "
                                "Optimizer parameters not being resumed.")
        else:
            self.optimizer.load_state_dict(checkpoint['optimizer'])

        if self.lr_scheduler is not None and optimizer_resumed:
            scheduler_state = checkpoint.get('lr_scheduler')
            if scheduler_state is not None:
                self.lr_scheduler.load_state_dict(scheduler_state)
            else:
                # Legacy checkpoints did not save scheduler state. This pipeline steps once per epoch,
                # so aligning last_epoch preserves the configured StepLR boundary on the next step.
                self.lr_scheduler.last_epoch = checkpoint['epoch']
                self.lr_scheduler._step_count = checkpoint['epoch'] + 1
                self.lr_scheduler._last_lr = [group['lr'] for group in self.optimizer.param_groups]
                self.logger.warning("Checkpoint has no LR scheduler state; inferred it from the saved epoch.")

        scaler_state = checkpoint.get('amp_scaler')
        if getattr(self, 'scaler', None) is not None and scaler_state:
            self.scaler.load_state_dict(scaler_state)

        if 'rng_state' in checkpoint:
            self._restore_rng_state(checkpoint['rng_state'])
        else:
            self.logger.warning("Checkpoint has no RNG state; resumed data order and augmentation may differ.")

        self._inherit_best_checkpoint(Path(resume_path))

        self.logger.info("Checkpoint loaded. Resume training from epoch {}".format(self.start_epoch))

    @staticmethod
    def _rng_state():
        state = {
            'python': random.getstate(),
            'numpy': np.random.get_state(),
            'torch': torch.get_rng_state(),
        }
        if torch.cuda.is_available():
            state['cuda'] = torch.cuda.get_rng_state_all()
        return state

    def _restore_rng_state(self, state):
        random.setstate(state['python'])
        np.random.set_state(state['numpy'])
        torch.set_rng_state(state['torch'])

        cuda_states = state.get('cuda', [])
        if torch.cuda.is_available() and cuda_states:
            for device_idx, cuda_state in enumerate(cuda_states[:torch.cuda.device_count()]):
                torch.cuda.set_rng_state(cuda_state, device=device_idx)

    def _inherit_best_checkpoint(self, resume_path):
        """Keep the previous run's best model available in the new resume directory."""
        source_best = resume_path.parent / 'model_best.pth'
        if not source_best.is_file() and resume_path.name == 'model_best.pth':
            source_best = resume_path

        destination = Path(self.checkpoint_dir) / 'model_best.pth'
        if source_best.is_file() and source_best.resolve() != destination.resolve():
            shutil.copy2(source_best, destination)
            self.logger.info("Copied previous best checkpoint into resumed run: {}".format(destination))
