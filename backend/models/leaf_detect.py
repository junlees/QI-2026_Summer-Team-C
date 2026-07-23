"""잎 검출 유틸 — torch 없이 cv2/numpy/PIL만 사용하는 경량 모듈.

`predict_leaf.py`에서 검출 부분만 분리했다: 사진에서 잎 후보를 찾아
이미지 중심에 가장 가까운 잎 하나를 정사각 크롭한다. Flask 백엔드가
모델 로딩 없이 싸게 import할 수 있도록 torch/predict/test_external을
절대 import하지 않는다.
"""
import os

import cv2
import numpy as np
from PIL import Image, ImageOps


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


# ---------------------------------------------------------------- 고수준 API
def detect_and_crop_leaf(image_path, out_path=None, method='auto',
                         min_area_frac=0.01, pad=0.15, out_size=256):
    """이미지에서 중앙 잎 하나를 검출·크롭해 JPEG로 저장하고 결과 dict를 반환.

    잎을 못 찾으면 중앙 정사각 크롭으로 폴백(fallback=True).
    반환 dict는 JSON 직렬화 가능(모든 값이 파이썬 기본 타입).
    """
    # PIL 로드 + EXIF 회전 적용. 폰 세로 사진은 픽셀은 가로인데 EXIF로 회전
    # 표시되므로, 회전을 실제 픽셀에 반영해야 bbox 좌표가 브라우저 표시
    # 방향과 일치한다(프론트의 바운딩박스 오버레이 정합).
    img = ImageOps.exif_transpose(Image.open(image_path))
    rgb = np.array(img.convert('RGB'))

    bbox, _mask, cands, used = find_center_leaf(rgb, method, min_area_frac, pad)
    fallback = bbox is None
    if fallback:  # 잎 못 찾음 → 중앙 크롭 폴백
        bbox = center_square(rgb)

    x0, y0, x1, y1 = bbox
    crop = rgb[y0:y1, x0:x1]
    crop = cv2.resize(crop, (out_size, out_size), interpolation=cv2.INTER_AREA)

    if out_path is None:
        stem, _ext = os.path.splitext(image_path)
        out_path = f'{stem}_leaf.jpg'
    Image.fromarray(crop).save(out_path, quality=95)

    return {
        'cropped_path': str(out_path),
        'bbox': [int(x0), int(y0), int(x1), int(y1)],
        'num_candidates': int(len(cands)),
        'method_used': str(used),
        'fallback': bool(fallback),
    }
