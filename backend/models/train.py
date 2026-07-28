import argparse
import collections
import random
from functools import partial

import torch
import numpy as np
import data_loader.data_loaders as module_data
import model.loss as module_loss
import model.lr_scheduler as module_lr_scheduler
import model.metric as module_metric
import model.model as module_arch
from parse_config import ConfigParser
from trainer import Trainer
from utils import prepare_device


# fix random seeds for reproducibility
SEED = 123
torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True

def main(config):
    logger = config.get_logger('train')

    # setup data_loader instances
    data_loader = config.init_obj('data_loader', module_data)
    valid_data_loader = data_loader.split_validation()

    # build model architecture, then log a concise parameter summary
    # (전체 구조 덤프는 GoogLeNet 기준 200줄이 넘어 로그를 채우므로 요약만 출력)
    model = config.init_obj('arch', module_arch)
    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info('{}: {:,} trainable parameters'.format(type(model).__name__, n_trainable))

    # prepare for (multi-device) GPU training
    device, device_ids = prepare_device(config['n_gpu'])
    model = model.to(device)
    if len(device_ids) > 1:
        model = torch.nn.DataParallel(model, device_ids=device_ids)

    # get function handles of loss and metrics
    loss_ftn = getattr(module_loss, config['loss'])
    loss_args = config.config.get('loss_args', {})
    criterion = partial(loss_ftn, **loss_args) if loss_args else loss_ftn
    metrics = [getattr(module_metric, met) for met in config['metrics']]

    # build optimizer, learning rate scheduler. delete every lines containing lr_scheduler for disabling scheduler
    trainable_params = filter(lambda p: p.requires_grad, model.parameters())
    optimizer = config.init_obj('optimizer', torch.optim, trainable_params)
    scheduler_type = config['lr_scheduler']['type']
    scheduler_module = module_lr_scheduler if hasattr(module_lr_scheduler, scheduler_type) \
        else torch.optim.lr_scheduler
    lr_scheduler = config.init_obj('lr_scheduler', scheduler_module, optimizer)

    trainer = Trainer(model, criterion, metrics, optimizer,
                      config=config,
                      device=device,
                      data_loader=data_loader,
                      valid_data_loader=valid_data_loader,
                      lr_scheduler=lr_scheduler)

    trainer.train()


if __name__ == '__main__':
    args = argparse.ArgumentParser(description='PyTorch Template')
    args.add_argument('-c', '--config', default=None, type=str,
                      help='config file path (default: None)')
    args.add_argument('-r', '--resume', default=None, type=str,
                      help='path to latest checkpoint (default: None)')
    args.add_argument('-d', '--device', default=None, type=str,
                      help='indices of GPUs to enable (default: all)')

    # custom cli options to modify configuration from default values given in json file.
    CustomArgs = collections.namedtuple('CustomArgs', 'flags type target')
    options = [
        CustomArgs(['--lr', '--learning_rate'], type=float, target='optimizer;args;lr'),
        CustomArgs(['--bs', '--batch_size'], type=int, target='data_loader;args;batch_size')
    ]
    config = ConfigParser.from_args(args, options)
    main(config)
