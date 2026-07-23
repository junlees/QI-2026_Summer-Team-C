"""외부 교차도메인 테스트셋 평가 — PlantVillage 학습 모델의 도메인 시프트 성능.

`dataset/external_test_mapping.csv`의 (dataset, src_path, pv_class, quality) 매핑으로 여러 외부
데이터셋(PlantPathology / GVLiD / TomatoLeafMulticlass / Multi-Crop)의 클래스 폴더를
PlantVillage 클래스에 **이름으로** 매칭해 교차 평가한다. 모델의 클래스 목록(config의
`data_dir/train`)에 존재하는 PV 클래스만 평가하고 나머지는 `not_in_model`로 제외한다
→ 25클래스/38클래스 모델 공용(체크포인트가 아는 클래스에 자동 정렬).

외부 데이터는 어떤 PlantVillage 학습셋에도 포함된 적 없어 **누수 없는 순수 도메인 시프트** 평가다.

지표: 전체 accuracy, macro-F1(존재 클래스), per-class F1, per-dataset accuracy,
      질병 vs healthy 정확도, 예측 분포(sink), 상위 혼동쌍, 평균 확신도(정답/오답).
산출: `saved/external_eval/<name>_<run>/` 에 metrics.json + per_class.csv + per_dataset.csv
      + confusion.csv(+png) + classification_report.txt.

사용:
  PY=/home/kntst/anaconda3/envs/env1/bin/python
  "$PY" test_external.py -r saved/models/<name>/<run>/model_best.pth
  "$PY" test_external.py -r ... --dataset gvlid          # 특정 소스만
  "$PY" test_external.py -r ... --quality exact          # exact 매핑만(기본 all)
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
DEFAULT_MAPPING = os.path.join(PROJ, 'dataset', 'external_test_mapping.csv')
IMG_EXT = ('.jpg', '.jpeg', '.png', '.bmp')


# ---------------------------------------------------------------- 전처리(arch별 입력 크기)
def build_transform(arch_type):
    # InceptionV3는 299 입력, 그 외(GoogLeNet/ResNet/ViT)는 224. 학습 평가 전처리와 동일 계열.
    resize, crop = (342, 299) if 'Inception' in arch_type else (256, 224)
    trsfm = transforms.Compose([
        transforms.Resize(resize),
        transforms.CenterCrop(crop),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    return trsfm, crop


# ---------------------------------------------------------------- 데이터셋
class ExternalCrops(Dataset):
    """매핑 기반 이미지 로더 — (tensor, gt_idx, sample_idx) 반환."""

    def __init__(self, samples, trsfm):
        self.samples = samples
        self.trsfm = trsfm

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        s = self.samples[i]
        img = Image.open(s['path']).convert('RGB')
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
    # 함정: GoogLeNet/Inception은 사전학습 로드 시 transform_input=True로 학습됐다.
    # pretrained=False로 빌드하면 기본 False라 입력 분포가 어긋난다(예측 붕괴). state_dict에
    # 없는 값이라 load로 복원되지 않으므로 명시적으로 켜서 학습과 일치시킨다(ViT는 이 속성 없음→무시).
    if hasattr(model, 'backbone') and hasattr(model.backbone, 'transform_input'):
        model.backbone.transform_input = True
    ckpt = torch.load(ckpt_path, map_location='cpu', weights_only=False)  # ConfigParser 임베드 → False
    model.load_state_dict(ckpt['state_dict'])
    return model.eval().to(device)


def list_images(folder):
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(IMG_EXT):
                out.append(os.path.join(root, fn))
    return sorted(out)


def load_samples(mapping_path, cls2idx, dataset_filter, quality_filter):
    with open(mapping_path, newline='') as f:
        rows = list(csv.DictReader(f))
    samples, skipped = [], Counter()
    for r in rows:
        if dataset_filter and r['dataset'] != dataset_filter:
            continue
        if quality_filter != 'all' and r['quality'] != quality_filter:
            skipped['quality_filtered:' + r['quality']] += 1
            continue
        pv = r['pv_class']
        if pv not in cls2idx:                       # 서브셋 모델의 범위 밖(예: 38클래스 전용)
            skipped['not_in_model:' + pv] += 1
            continue
        folder = os.path.join(PROJ, 'dataset', r['src_path'])
        if not os.path.isdir(folder):
            skipped['missing_dir:' + r['src_path']] += 1
            continue
        imgs = list_images(folder)
        if not imgs:
            skipped['empty_dir:' + r['src_path']] += 1
            continue
        for p in imgs:
            samples.append({
                'path': p, 'gt_idx': cls2idx[pv], 'pv': pv,
                'dataset': r['dataset'], 'quality': r['quality'],
                'healthy_assumed': pv.endswith('healthy'),
            })
    return samples, skipped


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description='외부 교차도메인 테스트셋 평가')
    ap.add_argument('-r', '--resume', required=True, help='체크포인트(.pth)')
    ap.add_argument('-c', '--config', default=None, help='config.json (기본: resume 옆)')
    ap.add_argument('-m', '--mapping', default=DEFAULT_MAPPING, help='매핑 CSV')
    ap.add_argument('--dataset', default=None, help='특정 소스만 평가(예: gvlid). 기본 전체')
    ap.add_argument('--quality', default='all', choices=['all', 'exact', 'weak'],
                    help='매핑 품질 필터(기본 all)')
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
    out_dir = args.out or os.path.join(PROJ, 'saved', 'external_eval', tag)
    os.makedirs(out_dir, exist_ok=True)

    trsfm, crop = build_transform(arch_type)
    samples, skipped = load_samples(args.mapping, cls2idx, args.dataset, args.quality)
    if not samples:
        raise RuntimeError('선택한 필터와 모델 클래스에 대응하는 외부 샘플이 없습니다.')

    ds_counts = Counter(s['dataset'] for s in samples)
    print(f'모델      : {tag}  (arch={arch_type}, 입력 {crop})')
    print(f'학습 데이터: {os.path.basename(data_dir.rstrip("/"))}  ({len(classes)}클래스)')
    print(f'매핑      : {os.path.relpath(args.mapping, PROJ)}  (quality={args.quality}'
          f'{", dataset="+args.dataset if args.dataset else ""})')
    print(f'외부 평가  : {len(samples):,}장  {dict(ds_counts)}')
    if skipped:
        print(f'제외      : {sum(skipped.values())}  {dict(skipped)}')

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = build_model(cfg, args.resume, device)

    dl = DataLoader(ExternalCrops(samples, trsfm), batch_size=args.batch, shuffle=False,
                    num_workers=args.workers, pin_memory=True)
    preds = np.zeros(len(samples), dtype=np.int64)
    gts = np.array([s['gt_idx'] for s in samples], dtype=np.int64)
    confs = np.zeros(len(samples), dtype=np.float32)
    with torch.no_grad():
        for x, _y, idx in tqdm(dl, desc='Evaluating'):
            prob = torch.softmax(model(x.to(device)), dim=1)   # eval() → logits → softmax
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

    # 질병 vs healthy 분리
    healthy_mask = np.array([s['healthy_assumed'] for s in samples])
    acc_disease = accuracy_score(gts[~healthy_mask], preds[~healthy_mask]) if (~healthy_mask).any() else float('nan')
    acc_healthy = accuracy_score(gts[healthy_mask], preds[healthy_mask]) if healthy_mask.any() else float('nan')

    # 매핑 품질 exact/weak 분리
    quality = np.array([s['quality'] for s in samples])
    exact_mask = quality == 'exact'
    acc_exact = accuracy_score(gts[exact_mask], preds[exact_mask]) if exact_mask.any() else float('nan')
    acc_weak = accuracy_score(gts[~exact_mask], preds[~exact_mask]) if (~exact_mask).any() else float('nan')

    # per-dataset 정확도
    ds_arr = np.array([s['dataset'] for s in samples])
    per_dataset = {}
    for dname in sorted(set(ds_arr.tolist())):
        m = ds_arr == dname
        per_dataset[dname] = {'n': int(m.sum()), 'accuracy': float(accuracy_score(gts[m], preds[m]))}

    # 예측 분포(sink) & 상위 혼동쌍
    pred_dist = Counter(classes[int(p)] for p in preds)
    conf_pairs = Counter((int(g), int(p)) for g, p in zip(gts, preds) if g != p)
    top_conf = [(classes[g], classes[p], n) for (g, p), n in conf_pairs.most_common(15)]

    wrong = gts != preds

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

    with open(os.path.join(out_dir, 'per_dataset.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['dataset', 'n', 'accuracy'])
        for dname, d in per_dataset.items():
            w.writerow([dname, d['n'], f'{d["accuracy"]:.4f}'])

    metrics = {
        'model': tag, 'arch': arch_type, 'train_data': os.path.basename(data_dir.rstrip('/')),
        'n_classes_model': len(classes), 'input_size': crop,
        'mapping': os.path.relpath(args.mapping, PROJ), 'quality_filter': args.quality,
        'dataset_filter': args.dataset, 'n_samples': int(len(samples)),
        'n_present_classes': len(present),
        'accuracy': float(acc), 'macro_f1_present': float(macro_f1),
        'accuracy_disease': float(acc_disease), 'accuracy_healthy': float(acc_healthy),
        'n_exact': int(exact_mask.sum()), 'n_weak': int((~exact_mask).sum()),
        'accuracy_exact': float(acc_exact), 'accuracy_weak': float(acc_weak),
        'per_dataset': per_dataset,
        'mean_conf_correct': float(confs[~wrong].mean()) if (~wrong).any() else None,
        'mean_conf_wrong': float(confs[wrong].mean()) if wrong.any() else None,
        'pred_dist_top': pred_dist.most_common(10),
        'top_confusions': top_conf,
        'skipped': dict(skipped),
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
    print(f'외부 평가          : {len(samples):,}  |  존재 PV 클래스 {len(present)}/{len(classes)}')
    print(f'전체 Accuracy      : {acc:.4f}')
    print(f'Macro-F1(존재클래스): {macro_f1:.4f}')
    print(f'  ├ 질병 라벨 정확도 : {acc_disease:.4f}  ({int((~healthy_mask).sum())}장)')
    print(f'  └ healthy 정확도  : {acc_healthy:.4f}  ({int(healthy_mask.sum())}장)')
    if metrics['mean_conf_correct'] is not None:
        print(f'평균 확신도 정답/오답 : {metrics["mean_conf_correct"]:.3f} / {metrics["mean_conf_wrong"]:.3f}')
    print('데이터셋별 정확도  :', '  '.join(f'{k}:{v["accuracy"]:.3f}(n{v["n"]})' for k, v in per_dataset.items()))
    print('-' * 72)
    print('상위 혼동쌍 (gt → pred, 횟수):')
    for g, p, n in top_conf:
        print(f'  {n:4d}  {g:42s} → {p}')
    print('=' * 72)
    print(f'저장: {out_dir}')


if __name__ == '__main__':
    main()
