"""단일(또는 다수) 이미지 분류: 예측 라벨 + 클래스 확률(top-k) 출력.

사용:
  PY=/home/kntst/anaconda3/envs/env1/bin/python
  "$PY" predict.py <image ...> -r saved/models/<name>/<run>/model_best.pth [-k 5]

- 클래스 인덱스→이름은 config의 data_dir/train 폴더(ImageFolder 정렬)로 재구성한다(학습 시와 동일 순서).
- 전처리는 평가용(Resize 256 → CenterCrop 224 → ImageNet 정규화)으로 test.py와 일치.
"""
import argparse
import json
import os
import torch
from PIL import Image
from torchvision import transforms

import model.model as module_arch
from data_loader.data_loaders import IMAGENET_MEAN, IMAGENET_STD

EVAL_TRSFM = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
])


def load_classes(data_dir):
    train_dir = os.path.join(data_dir, 'train')
    return sorted(d for d in os.listdir(train_dir)
                  if os.path.isdir(os.path.join(train_dir, d)))


def build_model(cfg, ckpt_path, device):
    arch = cfg['arch']['args']
    model = getattr(module_arch, cfg['arch']['type'])(
        num_classes=arch['num_classes'], pretrained=False)
    # GoogLeNet/Inception은 사전학습 로드 시 transform_input=True 상태로 학습됐다.
    # pretrained=False로 빌드하면 기본값 False가 되고, transform_input은 state_dict에 없어
    # load_state_dict로도 복원되지 않는다 → 입력 분포가 어긋나 예측이 무너진다. 명시적으로 켠다.
    if hasattr(model, 'backbone') and hasattr(model.backbone, 'transform_input'):
        model.backbone.transform_input = True
    # 체크포인트에 ConfigParser 객체가 함께 저장되어 weights_only=False 필요 (PyTorch 2.6+)
    ckpt = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    model.load_state_dict(ckpt['state_dict'])
    return model.eval().to(device)


def predict(model, classes, image_path, device, topk):
    img = Image.open(image_path).convert('RGB')
    x = EVAL_TRSFM(img).unsqueeze(0).to(device)
    with torch.no_grad():
        probs = torch.softmax(model(x), dim=1)[0]   # eval() -> raw logits -> softmax
    top = torch.topk(probs, min(topk, len(classes)))
    return [(classes[i], probs[i].item()) for i in top.indices]


def main():
    ap = argparse.ArgumentParser(description='단일 이미지 분류 (라벨 + 확률)')
    ap.add_argument('image', nargs='+', help='이미지 경로 (여러 개 가능)')
    ap.add_argument('-r', '--resume', required=True, help='체크포인트 (model_best.pth)')
    ap.add_argument('-c', '--config', default=None, help='config.json (기본: resume 옆)')
    ap.add_argument('-k', '--topk', type=int, default=5, help='상위 k개 확률 출력 (기본 5)')
    args = ap.parse_args()

    cfg_path = args.config or os.path.join(os.path.dirname(args.resume), 'config.json')
    cfg = json.load(open(cfg_path))
    classes = load_classes(cfg['data_loader']['args']['data_dir'])
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = build_model(cfg, args.resume, device)

    for path in args.image:
        preds = predict(model, classes, path, device, args.topk)
        label, conf = preds[0]
        print(f'\n[{os.path.basename(path)}]')
        print(f'  예측: {label}  ({conf * 100:.2f}%)')
        print(f'  Top-{args.topk}:')
        for name, p in preds:
            bar = '#' * int(round(p * 30))
            print(f'    {p * 100:6.2f}%  {bar:<30s} {name}')


if __name__ == '__main__':
    main()
