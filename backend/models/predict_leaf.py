"""작물 이미지 → 잎 검출 → 가장 가운데 잎 하나 크롭 → 학습 규격 변환 → 분류.

파이프라인:
  1) ExG(초과녹색 = 2G−R−B) Otsu 임계로 식생(잎) 마스크 생성 + 모폴로지 정리.
     녹색이 거의 없어(잎 전체가 병들어 갈변) 마스크가 비면 GrabCut(외형 기반 전경분리)로 폴백.
  2) 연결요소(잎 후보) 중 **이미지 중심에 가장 가까운**(충분히 큰) 것을 선택.
  3) 그 bbox를 정사각으로 패딩해 원본에서 크롭 → **256×256 RGB**(=PlantVillage 규격)로 리사이즈.
  4) 학습 평가 전처리(Resize 256 → CenterCrop 224 → ImageNet 정규화; arch에 맞춤)로 모델 입력 → top-k 예측.

`predict.py`의 모델 로딩/클래스 복원과 `test_external.py`의 arch별 전처리를 재사용한다.

사용:
  PY=/home/kntst/anaconda3/envs/env1/bin/python
  "$PY" predict_leaf.py <image ...> -r saved/models/<name>/<run>/model_best.pth [-k 5] [--debug]

옵션:
  --method {exg,grabcut,auto}  잎 검출 방식(기본 auto: exg 실패 시 grabcut)
  --min-area FLOAT   잎 후보 최소 면적(이미지 대비 비율, 기본 0.01)
  --pad FLOAT        선택 bbox 정사각 패딩 비율(기본 0.15)
  --no-detect        검출 생략, 이미지 중앙 정사각 크롭만(비교/폴백용)
  --save-crop        256×256 잎 크롭 저장
  --debug            원본+마스크+bbox+크롭 시각화 PNG 저장
  --out DIR          크롭/디버그 저장 폴더(기본 saved/leaf_predict)
"""
import argparse
import json
import os

import cv2
import numpy as np
import torch
from PIL import Image

# 기존 코드 재사용 (중복 방지)
from predict import build_model, load_classes
from test_external import build_transform


# ---------------------------------------------------------------- 잎 검출
def vegetation_mask_exg(rgb):
    """ExG(2G−R−B) Otsu 임계 → 식생(초록) 이진 마스크(0/255)."""
    r, g, b = [c.astype(np.float32) for c in cv2.split(rgb)]
    exg = 2 * g - r - b
    exg = np.clip(exg, 0, None)
    exg8 = cv2.normalize(exg, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, mask = cv2.threshold(exg8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return mask


def foreground_mask_grabcut(rgb):
    """GrabCut(중앙 사각형 초기화)로 색과 무관하게 전경(잎)을 분리 — 갈변 잎 대비 폴백."""
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros((h, w), np.uint8)
    rect = (int(0.06 * w), int(0.06 * h), int(0.88 * w), int(0.88 * h))
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(bgr, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return np.zeros((h, w), np.uint8)
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def clean_mask(mask, min_dim):
    k = max(3, int(round(min_dim * 0.012)) | 1)  # 홀수 커널
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)  # 병반 구멍 메우기
    return mask


def find_center_leaf(rgb, method='auto', min_area_frac=0.01, pad=0.15):
    """이미지 중심에 가장 가까운 잎의 정사각 bbox 반환.
    return (bbox(x0,y0,x1,y1) | None, mask, candidates[(cx,cy,area,box)], used_method)."""
    h, w = rgb.shape[:2]
    used = method

    def candidates_from(mask):
        mask = clean_mask(mask, min(h, w))
        n, _lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        cands = []
        for i in range(1, n):  # 0=배경
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_area_frac * h * w:
                continue
            x, y, ww, hh = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
            cands.append((float(cents[i][0]), float(cents[i][1]), area, (x, y, ww, hh)))
        return mask, cands

    if method in ('exg', 'auto'):
        mask, cands = candidates_from(vegetation_mask_exg(rgb))
        used = 'exg'
        if not cands and method == 'auto':
            mask, cands = candidates_from(foreground_mask_grabcut(rgb))
            used = 'grabcut(auto)'
    else:  # grabcut
        mask, cands = candidates_from(foreground_mask_grabcut(rgb))

    if not cands:
        return None, mask, [], used

    cx, cy = w / 2.0, h / 2.0
    diag = (w ** 2 + h ** 2) ** 0.5
    # 점수: 중심까지 거리(정규화)에서 면적비를 약간 감산(근접 동률 시 큰 잎 선호)
    def score(c):
        d = ((c[0] - cx) ** 2 + (c[1] - cy) ** 2) ** 0.5 / diag
        return d - 0.12 * (c[2] / (h * w))
    chosen = min(cands, key=score)

    x, y, ww, hh = chosen[3]
    bcx, bcy = x + ww / 2.0, y + hh / 2.0
    side = min(int(round(max(ww, hh) * (1 + pad))), min(h, w))  # 참 정사각(이미지 내부)
    x0 = int(np.clip(round(bcx - side / 2), 0, w - side))
    y0 = int(np.clip(round(bcy - side / 2), 0, h - side))
    return (x0, y0, x0 + side, y0 + side), mask, cands, used


def center_square(rgb):
    h, w = rgb.shape[:2]
    s = min(h, w)
    x0, y0 = (w - s) // 2, (h - s) // 2
    return (x0, y0, x0 + s, y0 + s)


# ---------------------------------------------------------------- 시각화
def save_debug(rgb, mask, bbox, cands, crop256, pred, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(15, 5))
    ax[0].imshow(rgb); ax[0].set_title('input + detected leaf'); ax[0].axis('off')
    h, w = rgb.shape[:2]
    ax[0].plot(w / 2, h / 2, '+', color='cyan', ms=14, mew=2)
    for cxx, cyy, _a, (x, y, ww, hh) in cands:
        ax[0].add_patch(plt.Rectangle((x, y), ww, hh, fill=False, edgecolor='yellow', lw=1, alpha=0.6))
    if bbox:
        x0, y0, x1, y1 = bbox
        ax[0].add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor='red', lw=2.5))
    ax[1].imshow(mask, cmap='gray'); ax[1].set_title('vegetation / foreground mask'); ax[1].axis('off')
    ax[2].imshow(crop256); ax[2].axis('off')
    ax[2].set_title(f'256x256 crop\n{pred[0][0]}  ({pred[0][1]*100:.1f}%)', fontsize=10)
    fig.tight_layout(pad=1.4, rect=[0, 0, 1, 0.94]); fig.savefig(path, dpi=120); plt.close(fig)


# ---------------------------------------------------------------- main
def process(path, model, classes, trsfm, device, args, out_dir):
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:  # cv2가 못 읽으면 PIL 폴백
        rgb = np.array(Image.open(path).convert('RGB'))
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    if args.no_detect:
        bbox, mask, cands, used = center_square(rgb), np.zeros(rgb.shape[:2], np.uint8), [], 'center-crop'
    else:
        bbox, mask, cands, used = find_center_leaf(rgb, args.method, args.min_area, args.pad)
        if bbox is None:  # 잎 못 찾음 → 중앙 크롭 폴백
            bbox, used = center_square(rgb), used + ' → center-crop(fallback)'

    x0, y0, x1, y1 = bbox
    crop = rgb[y0:y1, x0:x1]
    crop256 = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_AREA)  # PlantVillage 규격

    x = trsfm(Image.fromarray(crop256)).unsqueeze(0).to(device)
    with torch.no_grad():
        probs = torch.softmax(model(x), dim=1)[0]
    top = torch.topk(probs, min(args.topk, len(classes)))
    pred = [(classes[i], probs[i].item()) for i in top.indices]

    base = os.path.splitext(os.path.basename(path))[0]
    saved = []
    if args.save_crop:
        p = os.path.join(out_dir, f'{base}_leaf.jpg')
        Image.fromarray(crop256).save(p, quality=95); saved.append(p)
    if args.debug:
        p = os.path.join(out_dir, f'{base}_debug.png')
        save_debug(rgb, mask, None if args.no_detect else bbox, cands, crop256, pred, p); saved.append(p)

    print(f'\n[{os.path.basename(path)}]  ({rgb.shape[1]}x{rgb.shape[0]}, 검출={used}, 잎후보={len(cands)})')
    print(f'  크롭 bbox: ({x0},{y0})-({x1},{y1})  → 256x256')
    label, conf = pred[0]
    gate = '  ⚠️ 확신도<70% (불확실)' if conf * 100 < 70 else ''
    print(f'  예측: {label}  ({conf*100:.2f}%){gate}')
    print(f'  Top-{args.topk}:')
    for name, p in pred:
        bar = '#' * int(round(p * 30))
        print(f'    {p*100:6.2f}%  {bar:<30s} {name}')
    for s in saved:
        print(f'  저장: {s}')


def main():
    ap = argparse.ArgumentParser(description='잎 검출 → 중앙 잎 크롭 → 학습규격 변환 → 분류')
    ap.add_argument('image', nargs='+', help='이미지 경로(여러 개 가능)')
    ap.add_argument('-r', '--resume', required=True, help='체크포인트(.pth)')
    ap.add_argument('-c', '--config', default=None, help='config.json(기본: resume 옆)')
    ap.add_argument('-k', '--topk', type=int, default=5, help='상위 k개 확률(기본 5)')
    ap.add_argument('--method', default='auto', choices=['exg', 'grabcut', 'auto'],
                    help='잎 검출 방식(기본 auto)')
    ap.add_argument('--min-area', type=float, default=0.01, dest='min_area',
                    help='잎 후보 최소 면적(이미지 비율, 기본 0.01)')
    ap.add_argument('--pad', type=float, default=0.15, help='bbox 정사각 패딩 비율(기본 0.15)')
    ap.add_argument('--no-detect', action='store_true', help='검출 생략, 중앙 정사각 크롭')
    ap.add_argument('--save-crop', action='store_true', help='256x256 잎 크롭 저장')
    ap.add_argument('--debug', action='store_true', help='검출 시각화 PNG 저장')
    ap.add_argument('--out', default='saved/leaf_predict', help='저장 폴더')
    args = ap.parse_args()

    cfg_path = args.config or os.path.join(os.path.dirname(args.resume), 'config.json')
    cfg = json.load(open(cfg_path))
    classes = load_classes(cfg['data_loader']['args']['data_dir'])
    trsfm, crop = build_transform(cfg['arch']['type'])
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = build_model(cfg, args.resume, device)
    out_dir = args.out
    if args.save_crop or args.debug:
        os.makedirs(out_dir, exist_ok=True)

    print(f'모델: {cfg.get("name")}  (arch={cfg["arch"]["type"]}, 입력 {crop}, {len(classes)}클래스)')
    for path in args.image:
        if not os.path.exists(path):
            print(f'\n[{path}] 파일 없음 — 건너뜀'); continue
        process(path, model, classes, trsfm, device, args, out_dir)


if __name__ == '__main__':
    main()
