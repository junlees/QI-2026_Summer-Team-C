"""PlantDoc(세그먼테이션 leaf 크롭) 교차 평가 — PlantVillage 학습 모델의 도메인 시프트 성능.

PlantDoc는 웹수집 실사진에서 bbox로 잘라낸 잎(dataset/plantdoc_leaf_crops/)이라 PlantVillage와
촬영 조건이 완전히 다르다. manifest.csv에 pd_class→pv_class(PlantVillage 38클래스) 매핑이 내장돼 있어,
학습 모델 logits에서 argmax한 예측을 PV 인덱스 정답과 맞춰 교차 평가한다.
(25클래스 서브셋 모델은 모델에 포함된 PV 클래스만 평가한다.)
(PlantDoc 이미지는 어떤 PV 학습셋에도 포함된 적 없어 누수 없음 — 순수 도메인 시프트 평가.)

지표: 전체 accuracy, macro-F1(PlantDoc에 존재하는 PV 클래스만), per-class F1, classification_report,
      혼동행렬. 분석: '질병 라벨' vs '일반 잎→healthy(가정)' 분리, 상위 혼동쌍, 크롭 크기별 정확도,
      정답/오답 시 평균 확신도.

산출: saved/plantdoc_eval/<name>_<run>/ 에 metrics.json + per_class.csv + confusion.csv (+ confusion.png).

사용:
  PY=/home/kntst/anaconda3/envs/env1/bin/python
  "$PY" test_plantdoc.py -r saved/models/<name>/<run>/model_best.pth [--split all|train|test]
"""
import argparse
import csv
import json
import os
from collections import Counter

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from tqdm import tqdm
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix

import model.model as module_arch
from data_loader.data_loaders import IMAGENET_MEAN, IMAGENET_STD

PROJ = os.path.dirname(os.path.abspath(__file__))
PD_ROOT = os.path.join(PROJ, 'dataset', 'plantdoc_leaf_crops')
MANIFEST = os.path.join(PD_ROOT, 'manifest.csv')

# PlantDoc → PlantVillage(38클래스) 권위 라벨 매핑 (CLAUDE.md에 문서화된 표와 동일).
# 값 = (PlantVillage 폴더명, 품질). 품질 weak = 근사/가정 매핑(정확도 해석 시 주의).
# 표에 없는 pd_class(예: 바 'Potato leaf')는 평가에서 제외한다.
PD2PV = {
    'Apple Scab Leaf':                        ('Apple___Apple_scab',                                 'exact'),
    'Apple leaf':                             ('Apple___healthy',                                    'exact'),
    'Apple rust leaf':                        ('Apple___Cedar_apple_rust',                           'exact'),
    'Bell_pepper leaf':                       ('Pepper,_bell___healthy',                             'exact'),
    'Bell_pepper leaf spot':                  ('Pepper,_bell___Bacterial_spot',                      'weak'),
    'Blueberry leaf':                         ('Blueberry___healthy',                                'exact'),
    'Cherry leaf':                            ('Cherry_(including_sour)___healthy',                  'exact'),
    'Corn Gray leaf spot':                    ('Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot', 'exact'),
    'Corn leaf blight':                       ('Corn_(maize)___Northern_Leaf_Blight',                'exact'),
    'Corn rust leaf':                         ('Corn_(maize)___Common_rust_',                        'exact'),
    'Peach leaf':                             ('Peach___healthy',                                    'exact'),
    'Potato leaf early blight':               ('Potato___Early_blight',                              'exact'),
    'Potato leaf late blight':                ('Potato___Late_blight',                               'exact'),
    'Raspberry leaf':                         ('Raspberry___healthy',                                'exact'),
    'Soyabean leaf':                          ('Soybean___healthy',                                  'weak'),
    'Squash Powdery mildew leaf':             ('Squash___Powdery_mildew',                            'exact'),
    'Strawberry leaf':                        ('Strawberry___healthy',                               'weak'),
    'Tomato Early blight leaf':               ('Tomato___Early_blight',                              'exact'),
    'Tomato Septoria leaf spot':              ('Tomato___Septoria_leaf_spot',                        'exact'),
    'Tomato leaf':                            ('Tomato___healthy',                                   'exact'),
    'Tomato leaf bacterial spot':             ('Tomato___Bacterial_spot',                            'exact'),
    'Tomato leaf late blight':                ('Tomato___Late_blight',                               'exact'),
    'Tomato leaf mosaic virus':               ('Tomato___Tomato_mosaic_virus',                       'exact'),
    'Tomato leaf yellow virus':               ('Tomato___Tomato_Yellow_Leaf_Curl_Virus',            'exact'),
    'Tomato mold leaf':                       ('Tomato___Leaf_Mold',                                 'exact'),
    'Tomato two spotted spider mites leaf':   ('Tomato___Spider_mites Two-spotted_spider_mite',      'exact'),
    'grape leaf':                             ('Grape___healthy',                                    'exact'),
    'grape leaf black rot':                   ('Grape___Black_rot',                                  'exact'),
}


# ---------------------------------------------------------------- 전처리(arch별 입력 크기)
def build_transform(arch_type):
    # InceptionV3는 299 입력, 그 외(GoogLeNet/ResNet)는 224. 학습 평가 전처리와 동일 계열.
    resize, crop = (342, 299) if 'Inception' in arch_type else (256, 224)
    trsfm = transforms.Compose([
        transforms.Resize(resize),
        transforms.CenterCrop(crop),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    return trsfm, crop


# ---------------------------------------------------------------- 데이터셋
class PlantDocCrops(Dataset):
    """manifest.csv 기반 크롭 로더 — (tensor, gt_idx, sample_idx) 반환."""

    def __init__(self, samples, trsfm):
        self.samples = samples          # list of dict (abs_path, gt_idx, ...)
        self.trsfm = trsfm

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        s = self.samples[i]
        img = Image.open(s['abs_path']).convert('RGB')
        return self.trsfm(img), s['gt_idx'], i


# ---------------------------------------------------------------- 유틸
def load_classes(data_dir):
    train_dir = os.path.join(data_dir, 'train')
    return sorted(d for d in os.listdir(train_dir)
                  if os.path.isdir(os.path.join(train_dir, d)))


def build_model(cfg, ckpt_path, device):
    a = cfg['arch']['args']
    model = getattr(module_arch, cfg['arch']['type'])(
        num_classes=a['num_classes'], pretrained=False)
    # 중요: GoogLeNet/Inception은 사전학습 로드 시 transform_input=True가 켜진 상태로 학습됐다.
    # pretrained=False로 빌드하면 transform_input=False(기본)라 입력 분포가 어긋난다.
    # transform_input은 state_dict에 없어 load로 복원되지 않으므로 명시적으로 켜서 학습과 일치시킨다.
    if hasattr(model, 'backbone') and hasattr(model.backbone, 'transform_input'):
        model.backbone.transform_input = True
    ckpt = torch.load(ckpt_path, map_location='cpu', weights_only=False)  # ConfigParser 임베드 → False
    model.load_state_dict(ckpt['state_dict'])
    return model.eval().to(device)


def load_samples(split, cls2idx):
    with open(MANIFEST, newline='') as f:
        rows = list(csv.DictReader(f))
    samples, skipped = [], Counter()
    for r in rows:
        if split != 'all' and r['split'] != split:
            continue
        pd = r['pd_class']
        if pd not in PD2PV:                      # 권위 매핑 표에 없는 pd_class는 제외
            skipped['unmapped:' + pd] += 1
            continue
        pv, quality = PD2PV[pd]
        if pv not in cls2idx:                    # 25클래스 등 서브셋 모델의 범위 밖
            skipped['not_in_model:' + pv] += 1
            continue
        abs_path = os.path.join(PD_ROOT, r['crop_path'])
        if not os.path.exists(abs_path):
            skipped['missing_file'] += 1
            continue
        box_area = (int(r['xmax']) - int(r['xmin'])) * (int(r['ymax']) - int(r['ymin']))
        samples.append({
            'abs_path': abs_path, 'gt_idx': cls2idx[pv], 'pv': pv, 'pd': pd,
            'quality': quality, 'box_area': box_area, 'healthy_assumed': pv.endswith('healthy'),
        })
    return samples, skipped


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description='PlantDoc 세그먼테이션 교차 평가')
    ap.add_argument('-r', '--resume', required=True, help='체크포인트 model_best.pth')
    ap.add_argument('-c', '--config', default=None, help='config.json (기본: resume 옆)')
    ap.add_argument('--split', default='all', choices=['all', 'train', 'test'],
                    help='manifest split (기본 all — PD 전체를 외부 테스트로 사용)')
    ap.add_argument('--out', default=None, help='결과 저장 폴더')
    ap.add_argument('--batch', type=int, default=64)
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()

    cfg_path = args.config or os.path.join(os.path.dirname(args.resume), 'config.json')
    cfg = json.load(open(cfg_path))
    arch_type = cfg['arch']['type']
    data_dir = cfg['data_loader']['args']['data_dir']

    classes = load_classes(data_dir)
    assert len(classes) == cfg['arch']['args']['num_classes'], \
        f"class 수 불일치: {len(classes)} vs num_classes={cfg['arch']['args']['num_classes']}"
    cls2idx = {c: i for i, c in enumerate(classes)}

    run_id = os.path.basename(os.path.dirname(args.resume))
    tag = f"{cfg.get('name', arch_type)}_{run_id}"
    out_dir = args.out or os.path.join(PROJ, 'saved', 'plantdoc_eval', tag)
    os.makedirs(out_dir, exist_ok=True)

    trsfm, crop = build_transform(arch_type)
    samples, skipped = load_samples(args.split, cls2idx)
    if not samples:
        raise RuntimeError('선택한 split과 모델 클래스에 대응하는 PlantDoc 샘플이 없습니다.')
    n_skip = sum(skipped.values())
    print(f'모델      : {tag}  (arch={arch_type}, 입력 {crop})')
    print(f'학습 데이터: {os.path.basename(data_dir.rstrip("/"))}')
    print(f'매핑      : 권위표 PD2PV {len(PD2PV)}개 pd_class')
    print(f'PlantDoc  : split={args.split}, 평가 크롭 {len(samples):,}장 '
          f'(제외 {n_skip}: {dict(skipped)})')

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = build_model(cfg, args.resume, device)

    ds = PlantDocCrops(samples, trsfm)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=False, num_workers=args.workers,
                    pin_memory=True)

    preds = np.zeros(len(samples), dtype=np.int64)
    gts = np.array([s['gt_idx'] for s in samples], dtype=np.int64)
    confs = np.zeros(len(samples), dtype=np.float32)
    with torch.no_grad():
        for x, _, idx in tqdm(dl, desc='Evaluating'):
            x = x.to(device)
            prob = torch.softmax(model(x), dim=1)      # eval() → logits → softmax
            p, c = prob.max(dim=1)
            idx = idx.numpy()
            preds[idx] = c.cpu().numpy()
            confs[idx] = p.cpu().numpy()

    # ---- 지표 ----
    present = sorted(set(gts.tolist()))
    present_names = [classes[i] for i in present]
    acc = accuracy_score(gts, preds)
    macro_f1 = f1_score(gts, preds, average='macro', labels=present, zero_division=0)
    per_class_f1 = f1_score(gts, preds, average=None, labels=present, zero_division=0)
    support = Counter(gts.tolist())
    report = classification_report(gts, preds, labels=present, target_names=present_names,
                                   digits=4, zero_division=0)

    # 질병 라벨 vs 일반잎→healthy 가정 분리
    healthy_mask = np.array([s['healthy_assumed'] for s in samples])
    acc_disease = accuracy_score(gts[~healthy_mask], preds[~healthy_mask]) if (~healthy_mask).any() else float('nan')
    acc_healthy = accuracy_score(gts[healthy_mask], preds[healthy_mask]) if healthy_mask.any() else float('nan')

    # 매핑 품질: exact(정확) vs weak(근사/가정) 분리
    quality = np.array([s['quality'] for s in samples])
    exact_mask = quality == 'exact'
    pres_exact = sorted(set(gts[exact_mask].tolist()))
    acc_exact = accuracy_score(gts[exact_mask], preds[exact_mask]) if exact_mask.any() else float('nan')
    f1_exact = f1_score(gts[exact_mask], preds[exact_mask], average='macro', labels=pres_exact,
                        zero_division=0) if exact_mask.any() else float('nan')
    acc_weak = accuracy_score(gts[~exact_mask], preds[~exact_mask]) if (~exact_mask).any() else float('nan')

    # 상위 혼동쌍
    conf_pairs = Counter((int(g), int(p)) for g, p in zip(gts, preds) if g != p)
    top_conf = [(classes[g], classes[p], n) for (g, p), n in conf_pairs.most_common(15)]

    # 크롭 크기별 정확도 (bbox 면적 → 한 변 근사)
    side = np.sqrt(np.array([s['box_area'] for s in samples], dtype=np.float64))
    size_acc = []
    for lo, hi in [(0, 32), (32, 64), (64, 128), (128, 1e9)]:
        m = (side >= lo) & (side < hi)
        if m.any():
            size_acc.append((f'{lo}-{int(hi) if hi < 1e9 else "inf"}px', int(m.sum()),
                             float(accuracy_score(gts[m], preds[m]))))

    # ---- 저장 ----
    cm = confusion_matrix(gts, preds, labels=list(range(len(classes))))
    with open(os.path.join(out_dir, 'confusion.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['gt\\pred'] + classes)
        for i, row in enumerate(cm):
            w.writerow([classes[i]] + row.tolist())

    with open(os.path.join(out_dir, 'per_class.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['pv_class', 'support', 'f1'])
        for idx_c, f1v in zip(present, per_class_f1):
            w.writerow([classes[idx_c], support[idx_c], f'{f1v:.4f}'])

    wrong = gts != preds
    metrics = {
        'model': tag, 'arch': arch_type, 'train_data': os.path.basename(data_dir.rstrip('/')),
        'split': args.split, 'n_samples': int(len(samples)),
        'n_present_classes': len(present), 'input_size': crop,
        'accuracy': float(acc), 'macro_f1_present': float(macro_f1),
        'accuracy_disease_labels': float(acc_disease),
        'accuracy_healthy_assumed': float(acc_healthy),
        'n_exact': int(exact_mask.sum()), 'n_weak': int((~exact_mask).sum()),
        'accuracy_exact': float(acc_exact), 'macro_f1_exact': float(f1_exact),
        'accuracy_weak': float(acc_weak),
        'mean_conf_correct': float(confs[~wrong].mean()) if (~wrong).any() else None,
        'mean_conf_wrong': float(confs[wrong].mean()) if wrong.any() else None,
        'size_bucket_acc': size_acc,
        'top_confusions': top_conf,
    }
    with open(os.path.join(out_dir, 'metrics.json'), 'w') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, 'classification_report.txt'), 'w') as f:
        f.write(report)

    # 혼동행렬 PNG (matplotlib 있으면)
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        cols = sorted(set(present) | set(int(p) for p in preds.tolist()))
        sub = cm[np.ix_(present, cols)].astype(np.float64)
        rn = sub / np.clip(sub.sum(axis=1, keepdims=True), 1, None)
        fig, ax = plt.subplots(figsize=(max(8, len(cols) * 0.5), max(6, len(present) * 0.4)))
        im = ax.imshow(rn, cmap='viridis', vmin=0, vmax=1, aspect='auto')
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([classes[c][:22] for c in cols], rotation=90, fontsize=6)
        ax.set_yticks(range(len(present)))
        ax.set_yticklabels([classes[c][:28] for c in present], fontsize=6)
        ax.set_xlabel('pred'); ax.set_ylabel('gt')
        ax.set_title(f'{tag}  row-normalized confusion  (acc={acc:.3f})', fontsize=9)
        fig.colorbar(im, fraction=0.03)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, 'confusion.png'), dpi=130)
        plt.close(fig)
    except Exception as e:
        print(f'  (confusion.png 스킵: {e})')

    # ---- 콘솔 요약 ----
    print('=' * 72)
    print(f'평가 크롭          : {len(samples):,}  |  존재 PV 클래스 {len(present)}/{len(classes)}')
    print(f'전체 Accuracy      : {acc:.4f}')
    print(f'Macro-F1(존재클래스): {macro_f1:.4f}')
    print(f'  ├ 질병 라벨 정확도     : {acc_disease:.4f}  ({int((~healthy_mask).sum())}장)')
    print(f'  └ 일반잎→healthy 가정  : {acc_healthy:.4f}  ({int(healthy_mask.sum())}장)')
    print(f'매핑 exact/weak     : acc {acc_exact:.4f}(F1 {f1_exact:.4f}, {int(exact_mask.sum())}장) '
          f'/ weak acc {acc_weak:.4f}({int((~exact_mask).sum())}장)')
    if metrics['mean_conf_correct'] is not None:
        print(f'평균 확신도 정답/오답 : {metrics["mean_conf_correct"]:.3f} / {metrics["mean_conf_wrong"]:.3f}')
    print('크롭 크기별 정확도  :', '  '.join(f'{b}:{a:.2f}(n{n})' for b, n, a in size_acc))
    print('-' * 72)
    print('상위 혼동쌍 (gt → pred, 횟수):')
    for g, p, n in top_conf:
        print(f'  {n:4d}  {g:42s} → {p}')
    print('=' * 72)
    print(f'저장: {out_dir}')


if __name__ == '__main__':
    main()
