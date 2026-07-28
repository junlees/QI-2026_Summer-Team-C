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

# 검출은 이 크기로 축소한 사본에서 수행한다(_find_center_leaf_impl 참조).
# 형태학 연산/GrabCut 비용이 화소수와 함께 폭증해 12MP 폰 사진이 요청 타임아웃을
# 넘기기 때문 — 크롭 자체는 원본 해상도에서 잘라 화질은 그대로다.
DETECT_MAX_SIDE = 1024

# cv2.grabCut의 GMM 초기화(k-means++)는 OpenCV 전역 RNG를 쓴다. 시드를 고정하지
# 않으면 같은 사진을 다시 진단할 때마다 bbox가 달라진다(같은 이미지 6회 호출에
# 전경 화소수가 3.5만~4.1만으로 흔들림). 호출 직전마다 같은 시드를 심어 진단을
# 재현 가능하게 만든다 — 전역 상태라 grabCut 호출부에서만 건드린다.
GRABCUT_SEED = 42


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
        cv2.setRNGSeed(GRABCUT_SEED)  # 재현 가능한 분할 (GRABCUT_SEED 주석 참조)
        cv2.grabCut(bgr, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return np.zeros((h, w), np.uint8)
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def _fill_holes(mask):
    """마스크 내부의 닫힌 구멍을 메운다 — 병반(황갈색)은 ExG에 안 잡혀
    잎 안쪽이 뚫린 채 남는데, 그 자리를 잎의 일부로 되돌린다."""
    h, w = mask.shape[:2]
    ff = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ffmask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(ff, ffmask, (0, 0), 255)
    holes = cv2.bitwise_not(ff)[1:-1, 1:-1]
    return cv2.bitwise_or(mask, holes)


def clean_mask(mask, min_dim):
    k = max(3, int(round(min_dim * 0.012)) | 1)  # 홀수 커널
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return _fill_holes(mask)  # 닫기가 못 메운 큰 병반 구멍까지 채운다


def _component_of(mask, chosen):
    """mask에서 chosen 후보(bbox+면적 일치)의 연결요소만 담은 0/255 마스크. 없으면 None."""
    n, lab, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, n):
        box = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
               stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
        if box == chosen[3] and int(stats[i, cv2.CC_STAT_AREA]) == chosen[2]:
            return np.where(lab == i, np.uint8(255), np.uint8(0))
    return None


def _split_large_component(rgb, mask, chosen, min_area, core_frac=0.4):
    """겹쳐 붙은 잎 덩어리(하나의 연결요소)를 distance-transform watershed로
    개별 잎 후보로 분할한다. 밀집 군락 사진은 ExG 마스크에서 모든 잎이 한
    덩어리로 붙어 '중앙 잎 선택'이 화면 전체가 되는데, 그 경우에만 호출된다.

    과분할 방지 3중 게이트(단일 잎이 조각나 bbox가 잎 가운데 엉뚱하게 잡히는
    실측 최다 오류의 대책):
    ① 볼록도 게이트 — 덩어리 면적이 볼록껍질의 62% 이상이면 잎 하나로 본다
       (군락은 잎 사이 빈틈 탓에 볼록도가 낮고, 결각 잎도 이보다는 높다).
    ② 미세 코어 제거 — 최대 코어 대비 10% 미만 코어(결각·병반이 만든 지역
       최대)는 씨앗에서 빼고, 남은 코어가 1개면 분할하지 않는다.
    ③ 지배 조각 게이트 — 분할 결과 최대 조각이 덩어리의 80% 이상이면
       가장자리만 떼어낸 과분할이므로 결과를 버린다."""
    comp = _component_of(mask, chosen)
    if comp is None:
        return []

    # ① 볼록도 게이트
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        hull = cv2.convexHull(np.vstack([c.reshape(-1, 2) for c in cnts]))
        if chosen[2] >= 0.62 * max(cv2.contourArea(hull), 1.0):
            return []

    dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
    if dist.max() <= 0:
        return []
    core = (dist > core_frac * dist.max()).astype(np.uint8) * 255

    # ② 미세 코어 제거
    n_seed, seed_lab = cv2.connectedComponents(core)
    if n_seed > 2:
        sizes = np.bincount(seed_lab.ravel())
        sizes[0] = 0
        for i in range(1, n_seed):
            if sizes[i] < 0.1 * sizes.max():
                core[seed_lab == i] = 0
        n_seed, seed_lab = cv2.connectedComponents(core)
    if n_seed <= 2:  # 코어 1개 = 잎 하나 → 분할하지 않음
        return []

    markers = seed_lab.astype(np.int32) + 1  # 바깥 배경=1, 잎 코어=2..
    markers[(comp > 0) & (core == 0)] = 0    # 미확정 영역은 watershed가 배분
    cv2.watershed(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), markers)

    cands = []
    for s in range(2, n_seed + 1):
        seg = ((markers == s) & (comp > 0)).astype(np.uint8)
        area = int(cv2.countNonZero(seg))
        if area < min_area:
            continue
        x, y, ww, hh = cv2.boundingRect(seg)
        m = cv2.moments(seg, binaryImage=True)
        if m["m00"] == 0:
            continue
        cands.append((m["m10"] / m["m00"], m["m01"] / m["m00"], area, (x, y, ww, hh)))

    # watershed 조각(sliver) 제거: 가장 큰 하위 잎 대비 너무 작거나(30% 미만)
    # 잎 형태로 보기 어려운 극단적 종횡비 조각은 후보에서 뺀다 — 중앙의 작은
    # 파편이 '중심 최근접' 점수로 선택되는 것을 막는다.
    if cands:
        amax = max(c[2] for c in cands)
        cands = [c for c in cands
                 if c[2] >= 0.3 * amax
                 and max(c[3][2], c[3][3]) <= 3.5 * max(1, min(c[3][2], c[3][3]))]

    # ③ 지배 조각 게이트
    if cands and max(c[2] for c in cands) >= 0.8 * chosen[2]:
        return []
    return cands if len(cands) >= 2 else []


def _refine_bbox_grabcut(rgb, mask, chosen, max_side=420, grow_cap=3.0):
    """선택된 잎의 식생 마스크를 시드로 mask-init GrabCut을 돌려, 변색돼
    ExG에서 빠진 부위(황화·갈변·병반)까지 잎 범위를 확장한 tight bbox를
    반환한다. 시드는 확정 전경(GC_FGD)으로 고정하므로 결과는 항상 시드를
    포함하며, 확장이 비정상(면적 grow_cap배 초과)이면 원래 bbox를 유지한다."""
    x, y, ww, hh = chosen[3]
    comp = _component_of(mask, chosen)
    if comp is None:
        return chosen[3]

    h, w = rgb.shape[:2]
    s = min(1.0, max_side / max(h, w))
    ws, hs = max(1, int(round(w * s))), max(1, int(round(h * s)))
    rgb_s = cv2.resize(rgb, (ws, hs), interpolation=cv2.INTER_AREA)
    comp_s = cv2.resize(comp, (ws, hs), interpolation=cv2.INTER_NEAREST)
    if cv2.countNonZero(comp_s) == 0:
        return chosen[3]

    # 시드 주변 넉넉한 링을 '아마 전경'으로 — 잎의 변색부가 들어올 자리
    k = max(9, int(round(min(ws, hs) * 0.08)) | 1)
    ring = cv2.dilate(comp_s, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))

    gc = np.full((hs, ws), cv2.GC_PR_BGD, np.uint8)
    gc[ring > 0] = cv2.GC_PR_FGD
    gc[comp_s > 0] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.setRNGSeed(GRABCUT_SEED)  # 재현 가능한 분할 (GRABCUT_SEED 주석 참조)
        cv2.grabCut(cv2.cvtColor(rgb_s, cv2.COLOR_RGB2BGR), gc, None, bgd, fgd, 3,
                    cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return chosen[3]

    fg = ((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)).astype(np.uint8)
    n, lab = cv2.connectedComponents(fg, 8)
    keep = np.zeros((hs, ws), np.uint8)
    for i in range(1, n):
        seg = lab == i
        if np.any(seg & (comp_s > 0)):  # 시드와 이어진 조각만 잎으로 인정
            keep[seg] = 255
    grown = cv2.countNonZero(keep)
    if grown == 0 or grown > grow_cap * cv2.countNonZero(comp_s) or grown > 0.9 * ws * hs:
        return chosen[3]

    gx, gy, gw, gh = cv2.boundingRect(keep)
    x0 = int(np.clip(round(gx / s), 0, w - 1))
    y0 = int(np.clip(round(gy / s), 0, h - 1))
    x1 = int(np.clip(round((gx + gw) / s), x0 + 1, w))
    y1 = int(np.clip(round((gy + gh) / s), y0 + 1, h))
    return (x0, y0, x1 - x0, y1 - y0)


def _find_center_leaf_impl(rgb, method='auto', min_area_frac=0.01, pad=0.15,
                           split_area_frac=0.30, core_frac=0.4):
    """find_center_leaf의 본체 — (정사각 bbox, tight bbox, mask, cands, used) 반환.

    검출은 DETECT_MAX_SIDE로 축소한 사본에서 수행하고 좌표만 원본 배율로 되돌린다
    (mask/cands는 축소 좌표계 그대로 — 디버그 시각화용). 폰 사진은 12MP가 예사인데
    형태학 연산·GrabCut은 화소수와 커널 크기에 함께 비례해 원본 해상도로 돌리면
    한 장에 수십~수백 초가 걸리고 gunicorn 타임아웃(120s)을 넘긴다. 결과 bbox는
    잎 하나를 감싸는 큰 영역이라 축소본 정밀도로 충분하다."""
    full = rgb
    h0, w0 = full.shape[:2]
    scale = min(1.0, DETECT_MAX_SIDE / float(max(h0, w0))) if max(h0, w0) > 0 else 1.0
    if scale < 1.0:
        rgb = cv2.resize(full, (max(1, int(round(w0 * scale))), max(1, int(round(h0 * scale)))),
                         interpolation=cv2.INTER_AREA)

    h, w = rgb.shape[:2]
    used = method

    def candidates_of(mask):
        n, _lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        cands = []
        for i in range(1, n):  # 0=배경
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_area_frac * h * w:
                continue
            x, y, ww, hh = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
            cands.append((float(cents[i][0]), float(cents[i][1]), area, (x, y, ww, hh)))
        return cands

    def candidates_from(raw_mask):
        mask = clean_mask(raw_mask, min(h, w))
        return mask, candidates_of(mask)

    if method in ('exg', 'auto'):
        mask, cands = candidates_from(vegetation_mask_exg(rgb))
        used = 'exg'
        if not cands and method == 'auto':
            mask, cands = candidates_from(foreground_mask_grabcut(rgb))
            used = 'grabcut(auto)'
    else:  # grabcut
        mask, cands = candidates_from(foreground_mask_grabcut(rgb))

    if not cands:
        return None, None, mask, [], used

    cx, cy = w / 2.0, h / 2.0
    diag = (w ** 2 + h ** 2) ** 0.5
    # 점수: 중심까지 거리(정규화)에서 면적비를 감산 — 촬영 대상 잎은 대체로
    # 화면 중앙의 '큰' 잎이므로, 근접한 배경 잎보다 큰 잎을 우선한다.
    def score(c):
        d = ((c[0] - cx) ** 2 + (c[1] - cy) ** 2) ** 0.5 / diag
        return d - 0.2 * (c[2] / (h * w))
    chosen = min(cands, key=score)

    # 변색이 심한 잎(예: 포도 Esca)은 ExG 마스크가 초록 조각들로 부서진다.
    # 큰 커널로 한 번 더 닫아 조각을 잎 단위로 재결합해 다시 고르고, 선택
    # 잎이 크게(1.5배↑) 자라면 '조각난 한 잎'으로 보고 채택한다. 군락에서
    # 서로 닿아 이미 한 덩어리인 잎들은 닫아도 거의 안 자라므로 안 걸린다.
    merge_applied = False
    if chosen[2] <= 0.8 * h * w:
        # 커널이 크면 잎 사이 간격까지 이어붙여 군락 전체를 '잎 하나'로 삼킨다.
        # 0.025는 라벨셋 정확도 최고치(67.5%)를 유지하면서 그 삼킴을 0.05 대비
        # 절반으로 줄인 값 — 키우지 말 것.
        k = max(9, int(round(min(h, w) * 0.025)) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        merged = _fill_holes(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel))
        m_cands = candidates_of(merged)
        if m_cands:
            m_chosen = min(m_cands, key=score)
            if m_chosen[2] >= 1.5 * chosen[2]:
                mask, cands, chosen = merged, m_cands, m_chosen
                used += '+merge'
                merge_applied = True

    # 선택된 후보가 화면 30~80%를 덮으면(밀집 군락에서 잎들이 한 덩어리로
    # 붙은 경우) watershed로 분할해 개별 잎 중에서 다시 고른다. 80% 초과는
    # 잎 하나가 프레임을 채운 클로즈업, 재결합(+merge) 덩어리는 정의상 잎
    # 하나이므로 분할하지 않는다.
    split_applied = False
    if not merge_applied and split_area_frac * h * w < chosen[2] <= 0.8 * h * w:
        sub = _split_large_component(rgb, mask, chosen, min_area_frac * h * w, core_frac)
        if sub:
            cands = sub
            chosen = min(sub, key=score)
            used += '+watershed'
            split_applied = True

    # 변색부까지 잎 범위 확장(GrabCut): 병반·갈변은 ExG 마스크 밖이라 bbox가
    # 초록 부분만 감싸는데, 이를 잎 전체로 넓힌다. watershed 조각은 mask의
    # 연결요소가 아니라 확장 대상이 아니고, 화면 절반 이상 덩어리는 그대로 둔다.
    tight = chosen[3]
    if not split_applied and chosen[2] < 0.5 * h * w:
        tight = _refine_bbox_grabcut(rgb, mask, chosen)
        if tight != chosen[3]:
            used += '+refine'

    x, y, ww, hh = tight
    tight_box = (x, y, x + ww, y + hh)
    if scale < 1.0:  # 좌표를 원본 배율로 되돌리고 이미지 안으로 클램프
        inv = 1.0 / scale
        tight_box = (max(0, int(round(x * inv))), max(0, int(round(y * inv))),
                     min(w0, int(round((x + ww) * inv))), min(h0, int(round((y + hh) * inv))))
    return square_bbox_around(tight_box, pad), tight_box, mask, cands, used


def find_center_leaf(rgb, method='auto', min_area_frac=0.01, pad=0.15,
                     split_area_frac=0.30, core_frac=0.4):
    """이미지 중심에 가장 가까운 잎의 정사각 bbox 반환.
    return (bbox(x0,y0,x1,y1) | None, mask, candidates[(cx,cy,area,box)], used_method).

    bbox는 이미지 밖으로 나갈 수 있다(square_bbox_around 참조) — 잘라낼 때는
    numpy 슬라이스 대신 crop_square()를 쓸 것."""
    square, _tight, mask, cands, used = _find_center_leaf_impl(
        rgb, method, min_area_frac, pad, split_area_frac, core_frac)
    return square, mask, cands, used


def center_square(rgb):
    h, w = rgb.shape[:2]
    s = min(h, w)
    x0, y0 = (w - s) // 2, (h - s) // 2
    return (x0, y0, x0 + s, y0 + s)


# ------------------------------------------------------- 정사각 크롭(레터박스)
LETTERBOX_FILL = (124, 116, 104)  # ImageNet 평균색 ≈ 정규화 후 0 (여백이 신호가 되지 않게)


def square_bbox_around(tight, pad=0.15):
    """잎 tight bbox를 중심에 둔 참 정사각 bbox. **이미지 밖으로 나갈 수 있다** —
    프레임을 채운 잎을 이미지 안으로 밀어 넣으면(clamp) 잎 끝이 잘려나가므로,
    밖으로 나간 만큼은 crop_square가 여백으로 채운다."""
    x0, y0, x1, y1 = tight
    ww, hh = x1 - x0, y1 - y0
    side = int(round(max(ww, hh) * (1 + pad)))
    cx, cy = x0 + ww / 2.0, y0 + hh / 2.0
    sx, sy = int(round(cx - side / 2)), int(round(cy - side / 2))
    return (sx, sy, sx + side, sy + side)


def crop_square(rgb, sq, out_size=256, fill=LETTERBOX_FILL):
    """sq 영역을 잘라 out_size 정사각으로 반환. 이미지 밖 영역은 fill로 채운다."""
    h, w = rgb.shape[:2]
    sx0, sy0, sx1, sy1 = sq
    side = max(1, sx1 - sx0, sy1 - sy0)  # 정사각이 아닌 박스를 받아도 깨지지 않게
    canvas = np.full((side, side, 3), fill, np.uint8)
    ix0, iy0 = max(0, sx0), max(0, sy0)
    ix1, iy1 = min(w, sx1), min(h, sy1)
    if ix1 > ix0 and iy1 > iy0:
        canvas[iy0 - sy0:iy1 - sy0, ix0 - sx0:ix1 - sx0] = rgb[iy0:iy1, ix0:ix1]
    return cv2.resize(canvas, (out_size, out_size), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------- 고수준 API
def detect_and_crop_leaf(image_path, out_path=None, method='auto',
                         min_area_frac=0.01, pad=0.15, out_size=256):
    """이미지에서 중앙 잎 하나를 검출·크롭해 JPEG로 저장하고 결과 dict를 반환.

    잎을 못 찾으면 중앙 정사각 크롭으로 폴백(fallback=True).
    반환 dict는 JSON 직렬화 가능(모든 값이 파이썬 기본 타입).
    bbox는 분류기에 들어간 정사각 크롭(이미지 밖으로 나갈 수 있음),
    leaf_bbox는 잎만 감싼 tight 박스 — 프론트 오버레이는 항상 이미지 안에
    있는 leaf_bbox를 쓴다.
    """
    # PIL 로드 + EXIF 회전 적용. 폰 세로 사진은 픽셀은 가로인데 EXIF로 회전
    # 표시되므로, 회전을 실제 픽셀에 반영해야 bbox 좌표가 브라우저 표시
    # 방향과 일치한다(프론트의 바운딩박스 오버레이 정합).
    img = ImageOps.exif_transpose(Image.open(image_path))
    rgb = np.array(img.convert('RGB'))

    bbox, tight, cands, used = None, None, [], 'none'
    try:
        bbox, tight, _mask, cands, used = _find_center_leaf_impl(rgb, method, min_area_frac, pad)
    except cv2.error:
        bbox = None
    fallback = bbox is None
    if fallback:  # 잎 못 찾음 → 중앙 크롭 폴백
        bbox = center_square(rgb)
        tight = bbox

    x0, y0, x1, y1 = bbox
    crop = crop_square(rgb, bbox, out_size)

    if out_path is None:
        stem, _ext = os.path.splitext(image_path)
        out_path = f'{stem}_leaf.jpg'
    Image.fromarray(crop).save(out_path, quality=95)

    return {
        'cropped_path': str(out_path),
        'bbox': [int(x0), int(y0), int(x1), int(y1)],
        'leaf_bbox': [int(tight[0]), int(tight[1]), int(tight[2]), int(tight[3])],
        'num_candidates': int(len(cands)),
        'method_used': str(used),
        'fallback': bool(fallback),
    }
