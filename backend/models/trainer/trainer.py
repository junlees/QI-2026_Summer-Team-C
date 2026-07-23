import numpy as np
import torch
from base import BaseTrainer
from utils import inf_loop, MetricTracker


class Trainer(BaseTrainer):
    """
    Trainer class
    """
    def __init__(self, model, criterion, metric_ftns, optimizer, config, device,
                 data_loader, valid_data_loader=None, lr_scheduler=None, len_epoch=None):
        amp_requested = config['trainer'].get('amp', False)
        self.amp_enabled = amp_requested and device.type == 'cuda'
        amp_init_scale = config['trainer'].get('amp_init_scale', 65536.0)
        self.scaler = torch.amp.GradScaler(
            'cuda', init_scale=amp_init_scale, enabled=self.amp_enabled)
        super().__init__(model, criterion, metric_ftns, optimizer, config, lr_scheduler)
        self.config = config
        self.device = device
        self.data_loader = data_loader
        if len_epoch is None:
            # epoch-based training
            self.len_epoch = len(self.data_loader)
        else:
            # iteration-based training
            self.data_loader = inf_loop(data_loader)
            self.len_epoch = len_epoch
        self.valid_data_loader = valid_data_loader
        self.do_validation = self.valid_data_loader is not None
        self.grad_clip_norm = config['trainer'].get('grad_clip_norm')
        self.log_step = int(np.sqrt(data_loader.batch_size))

        self.train_metrics = MetricTracker('loss', *[m.__name__ for m in self.metric_ftns], writer=self.writer)
        self.valid_metrics = MetricTracker('loss', *[m.__name__ for m in self.metric_ftns], writer=self.writer)

    def _train_epoch(self, epoch):
        """
        Training logic for an epoch

        :param epoch: Integer, current training epoch.
        :return: A log that contains average loss and metric in this epoch.
        """
        self.model.train()
        self.train_metrics.reset()
        epoch_outputs, epoch_targets = [], []
        for batch_idx, (data, target) in enumerate(self.data_loader):
            data, target = data.to(self.device), target.to(self.device)

            self.optimizer.zero_grad()
            with torch.autocast(device_type=self.device.type, dtype=torch.float16,
                                enabled=self.amp_enabled):
                output = self.model(data)
                loss = self.criterion(output, target)
            self.scaler.scale(loss).backward()
            if self.grad_clip_norm is not None:
                self.scaler.unscale_(self.optimizer)
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip_norm)
            self.scaler.step(self.optimizer)
            self.scaler.update()

            self.writer.set_step((epoch - 1) * self.len_epoch + batch_idx)
            self.train_metrics.update('loss', loss.item(), n=target.size(0))
            epoch_outputs.append(self._main_logits(output).detach().cpu())
            epoch_targets.append(target.detach().cpu())

            if batch_idx % self.log_step == 0:
                self.logger.debug('Train Epoch: {} {} Loss: {:.6f}'.format(
                    epoch,
                    self._progress(batch_idx),
                    loss.item()))

            if batch_idx == self.len_epoch:
                break

        self._update_epoch_metrics(self.train_metrics, epoch_outputs, epoch_targets)
        log = self.train_metrics.result()

        # log current learning rate (value used during this epoch, before scheduler steps)
        self.writer.add_scalar('lr', self.optimizer.param_groups[0]['lr'])

        if self.do_validation:
            val_log = self._valid_epoch(epoch)
            log.update(**{'val_'+k : v for k, v in val_log.items()})

        if self.lr_scheduler is not None:
            self.lr_scheduler.step()
        return log

    def _valid_epoch(self, epoch):
        """
        Validate after training an epoch

        :param epoch: Integer, current training epoch.
        :return: A log that contains information about validation
        """
        self.model.eval()
        self.valid_metrics.reset()
        epoch_outputs, epoch_targets = [], []
        with torch.no_grad():
            for batch_idx, (data, target) in enumerate(self.valid_data_loader):
                data, target = data.to(self.device), target.to(self.device)

                with torch.autocast(device_type=self.device.type, dtype=torch.float16,
                                    enabled=self.amp_enabled):
                    output = self.model(data)
                    loss = self.criterion(output, target)

                self.writer.set_step((epoch - 1) * len(self.valid_data_loader) + batch_idx, 'valid')
                self.valid_metrics.update('loss', loss.item(), n=target.size(0))
                epoch_outputs.append(self._main_logits(output).detach().cpu())
                epoch_targets.append(target.detach().cpu())

        self._update_epoch_metrics(self.valid_metrics, epoch_outputs, epoch_targets)

        return self.valid_metrics.result()

    @staticmethod
    def _main_logits(output):
        return output if torch.is_tensor(output) else output.logits

    def _update_epoch_metrics(self, tracker, outputs, targets):
        """Calculate non-additive metrics once over the complete epoch."""
        if not outputs:
            return
        output = torch.cat(outputs, dim=0)
        target = torch.cat(targets, dim=0)
        for met in self.metric_ftns:
            tracker.update(met.__name__, met(output, target))

    def _progress(self, batch_idx):
        base = '[{}/{} ({:.0f}%)]'
        if hasattr(self.data_loader, 'n_samples'):
            current = batch_idx * self.data_loader.batch_size
            total = self.data_loader.n_samples
        else:
            current = batch_idx
            total = self.len_epoch
        return base.format(current, total, 100.0 * current / total)
