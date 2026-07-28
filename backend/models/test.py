import argparse
import numpy as np
import torch
from tqdm import tqdm
from sklearn.metrics import accuracy_score, f1_score, classification_report

import data_loader.data_loaders as module_data
import model.model as module_arch
from parse_config import ConfigParser


def main(config):
    logger = config.get_logger('test')

    # test/ 폴더 평가용 데이터로더 (split='test' → 평가 전처리, 셔플 없음)
    data_loader = getattr(module_data, config['data_loader']['type'])(
        config['data_loader']['args']['data_dir'],
        batch_size=64,
        shuffle=False,
        validation_split=0.0,
        split='test',
        num_workers=8,
    )
    class_names = data_loader.dataset.classes
    labels = list(range(len(class_names)))

    # 모델 로드
    model = config.init_obj('arch', module_arch)
    logger.info('Loading checkpoint: {} ...'.format(config.resume))
    # 체크포인트에 ConfigParser 객체가 함께 저장되므로 weights_only=False 필요
    # (PyTorch 2.6+ 기본값 True는 커스텀 클래스 언피클을 거부). 자체 생성 파일이라 안전.
    checkpoint = torch.load(config.resume, map_location='cpu', weights_only=False)
    state_dict = checkpoint['state_dict']
    if config['n_gpu'] > 1:
        model = torch.nn.DataParallel(model)
    model.load_state_dict(state_dict)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    model.eval()

    # 전체 예측/정답을 모은 뒤 한 번에 지표 계산 (정확한 macro F1)
    preds, gts = [], []
    with torch.no_grad():
        for data, target in tqdm(data_loader, desc='Evaluating'):
            data = data.to(device)
            output = model(data)  # eval() -> logits Tensor
            preds.append(torch.argmax(output, dim=1).cpu().numpy())
            gts.append(target.numpy())

    preds = np.concatenate(preds)
    gts = np.concatenate(gts)

    acc = accuracy_score(gts, preds)
    mean_f1 = f1_score(gts, preds, average='macro', labels=labels, zero_division=0)
    per_class = f1_score(gts, preds, average=None, labels=labels, zero_division=0)

    logger.info('=' * 70)
    logger.info('Samples evaluated : {}'.format(len(gts)))
    logger.info('Accuracy          : {:.4f}'.format(acc))
    logger.info('Mean F1 (macro)   : {:.4f}'.format(mean_f1))
    logger.info('=' * 70)
    logger.info('Per-class F1:')
    for name, f1 in zip(class_names, per_class):
        logger.info('  {:52s} {:.4f}'.format(name, f1))
    logger.info('=' * 70)
    logger.info('\n' + classification_report(
        gts, preds, labels=labels, target_names=class_names, digits=4, zero_division=0))


if __name__ == '__main__':
    args = argparse.ArgumentParser(description='PyTorch Template')
    args.add_argument('-c', '--config', default=None, type=str,
                      help='config file path (default: None)')
    args.add_argument('-r', '--resume', default=None, type=str,
                      help='path to checkpoint (default: None)')
    args.add_argument('-d', '--device', default=None, type=str,
                      help='indices of GPUs to enable (default: all)')

    config = ConfigParser.from_args(args)
    main(config)
