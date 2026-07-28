# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

PlantVillage 38개 작물–질병 클래스 이미지 분류. ImageNet 사전학습 **GoogLeNet(InceptionV1)** 을 fine-tuning하며, Mohanty et al. 2016 "Using Deep Learning for Image-Based Plant Disease Detection"의 GoogLeNet transfer-learning 실험(Caffe solver 스펙: SGD, base lr 0.005, StepLR step 10/gamma 0.1, momentum 0.9, weight decay 0.0005, batch 24, 30 epoch)을 재현한다. 이후 5작물 서브셋(25클래스)·17클래스(prepared5)·12클래스(prepared6) 서브셋과 ViT-B/16 fine-tuning 및 from-scratch(ImageNet 미사용) 변종으로 확장했다(config3~6·config_vit3~6·config_vit6_scratch, prepared3~6). 구조는 [victoresque/pytorch-template](https://github.com/victoresque/pytorch-template)을 이식했다.

## 환경 (필수)

**반드시 conda `env1`을 사용한다.** base 환경에는 torch가 없어 `import torch`에서 즉시 실패한다.

```bash
PY=/home/kntst/anaconda3/envs/env1/bin/python   # torch 2.9.1+cu128, torchvision 0.24.1
```

- GPU: RTX 4070 Ti SUPER 16GB (CUDA 12.8). CPU 16코어.
- 데이터가 WSL2 `/mnt/d`(9p 마운트)에 있어 이미지 I/O가 느리다 → `num_workers`, `pin_memory`, `persistent_workers`로 대응(이미 `base/base_data_loader.py`에 반영).

## 주요 명령

```bash
# 학습 (config.json이 모든 하이퍼파라미터 제어). train은 사용자가 직접 실행.
"$PY" train.py -c config6.json                   # 예시. config별 arch/데이터셋/epochs는 아래 "config 목록" 표 참조
"$PY" train.py -c config.json -r saved/models/<name>/<run>/checkpoint-epochN.pth   # 재개
"$PY" train.py -c config.json --lr 0.005 --bs 32                                    # CLI 오버라이드

# 최종 평가 (test/ 폴더 전체셋 → Accuracy, Mean F1(macro), per-class F1, classification_report)
"$PY" test.py -r saved/models/<name>/<run>/model_best.pth   # -r만 줘도 옆의 config.json 자동 로드

# 추론 (predict.py: PlantVillage식 잎사진 직접 분류 / predict_leaf.py: 실사진→잎 검출→중앙 잎 크롭 256×256→분류)
#   잎 검출 함수들(vegetation_mask_exg/find_center_leaf 등)은 leaf_detect.py로 분리됨 — predict_leaf.py가 import해서 사용
"$PY" predict.py <image ...> -r saved/models/<name>/<run>/model_best.pth [-k 5]
"$PY" predict_leaf.py <image ...> -r saved/models/<name>/<run>/model_best.pth [--method auto] [--save-crop] [--debug]

# TensorBoard (loss/val_accuracy/val_macro_f1/lr 곡선)
"$PY" -m tensorboard.main --logdir saved/log

# 데이터 준비 (스크립트별 분할·증강 상세는 dataset.md §5)
"$PY" dataset/prepare_split2.py   # raw/color → prepared2 (잎그룹 7:1.5:1.5 누수방지·강한 증강, config.json이 사용)
#   prepare_split3/4/5.py → prepared3(25) / prepared4(25, 증강 완화) / prepared5(17)
"$PY" dataset/prepare_split.py    # (구버전) raw/color → prepared, 이미지단위 7:2:1, 누수 있음

# 라벨 CSV 재생성
"$PY" dataset/generate_labels.py
```

### config 목록 (모두 `train.py -c <config>` — arch/데이터셋/epochs만 다름)

| config | arch | 클래스 | 사전학습 | epochs | 데이터셋 | data_dir 위치 |
|---|---|---|---|---|---|---|
| `config.json` | GoogLeNet | 38 | ✓ | 30 | prepared2 | AgriSage |
| `config3.json` | GoogLeNet | 25 | ✓ | 30 | prepared3 | AgriSage |
| `config4.json` | GoogLeNet | 25 | ✓ | 10 | prepared4 | AgriSage |
| `config5.json` | GoogLeNet | 17 | ✓ | 20 | prepared5 | AgriSage |
| `config6.json` | GoogLeNet | 12 | ✓ | 10 | prepared6 | **repo** |
| `config_vit3.json` | ViT-B/16 | 25 | ✓ | 30 | prepared3 | AgriSage |
| `config_vit4.json` | ViT-B/16 | 25 | ✓ | 10 | prepared4 | AgriSage |
| `config_vit5.json` | ViT-B/16 | 17 | ✓ | 20 | prepared5 | AgriSage |
| `config_vit6.json` | ViT-B/16 | 12 | ✓ | 10 | prepared6 | **repo** |
| `config_vit6_scratch.json` | ViT-B/16 | 12 | ✗ (from-scratch) | 20 | prepared6 | **repo** |

GoogLeNet은 `googlenet_loss`(aux 포함)+SGD(StepLR), ViT는 `cross_entropy`(label smoothing)+AdamW+warmup cosine+AMP. **data_dir 위치**(config6~는 repo, 그 외는 AgriSage)와 StepLR 단축 함정은 "규약 / 함정" 참조.

단일 테스트 스위트 개념은 없다(연구용 파이프라인). 변경 검증은 짧은 파이썬 스니펫으로 모듈 import·모델 forward·데이터로더 1배치를 확인하는 "비학습 무결성 체크"로 한다.

## 아키텍처 (config 구동)

`config.json`이 파이프라인 전체를 선언한다. `ConfigParser.init_obj(name, module)`가 config의 `type`/`args`를 읽어 해당 모듈의 클래스를 **동적 생성**한다 — 새 모델/로더/스케줄러는 코드가 아니라 config에서 갈아끼운다.

- `train.py` — 오케스트레이터: `init_obj`로 data_loader/arch/optimizer/lr_scheduler 생성, loss/metric은 `getattr`로 함수 핸들 확보, `Trainer` 구동. 상단에서 Python/NumPy/Torch seed와 deterministic cuDNN 설정을 고정한다.
- `leaf_detect.py` — **torch 없이 import되는** 잎 검출 모듈(cv2/numpy/PIL만). predict_leaf.py의 검출 함수들(ExG Otsu → GrabCut 폴백 → 연결요소 → 중심 최근접 선택)을 이식했고, `detect_and_crop_leaf(image_path, ...)` 고수준 API가 추가됐다 — `backend/ai/pipeline.py`가 진단 전처리로 호출한다(JSON 직렬화 가능한 dict 반환, EXIF 회전을 픽셀에 반영해 bbox가 브라우저 표시 방향과 일치). **torch/predict/test_external을 import하지 말 것** — Flask 백엔드가 싸게 import하는 것이 목적.

  검출 품질 관련 설계(실사진 120장 라벨셋 기준 top-1 55.8% → 67.5%, 크롭 없는 원본 65.8%보다도 높음. 각 항목은 그 측정으로 정당화된 것이라 되돌리지 말 것. 재측정 스크립트는 커밋하지 않았으니 파라미터를 건드릴 땐 `new test dataset`의 12클래스로 다시 재보고 판단할 것):
  - **정사각 크롭은 레터박스**(`square_bbox_around` + `crop_square`). 정사각 bbox를 이미지 안으로 밀어 넣으면(clamp) 프레임을 채운 잎의 끝이 잘려 나가는데, 이게 정확도 손실의 최대 원인이었다(같은 pad에서 +8.4%p). 밖으로 나간 영역은 `LETTERBOX_FILL`(ImageNet 평균색 ≈ 정규화 후 0)로 채운다 — 검정/edge-replicate보다 일관되게 좋았다. pad는 0.15~0.3이 평탄 구간이라 기존 기본값 0.15 유지. **`find_center_leaf`가 돌려주는 bbox는 이미지 밖으로 나갈 수 있으니 numpy 슬라이스 금지, `crop_square()`를 쓸 것.**
  - **`leaf_bbox`(잎만 감싼 tight 박스)를 `bbox`(분류기가 본 정사각)와 별도 반환** — 프론트 오버레이는 항상 이미지 안에 있는 `leaf_bbox`를 그린다.
  - **구멍 메우기**(`_fill_holes`): 병반은 ExG에 안 잡혀 잎 안쪽이 뚫리는데, 그 자리를 잎으로 되돌린다.
  - **변색부 확장**(`_refine_bbox_grabcut`): 시드(식생 마스크)를 GC_FGD로 고정한 mask-init GrabCut으로 황화·갈변 부위까지 잎 범위를 넓힌다. 확장이 3배를 넘거나 화면 90%를 넘으면 원래 bbox 유지.
  - **조각난 잎 재결합**(`+merge`): 커널 닫기로 선택 잎이 1.5배 이상 자라면 '조각난 한 잎'으로 보고 채택(포도 Esca처럼 변색이 심한 잎 대응). **커널은 짧은 변의 2.5%** — 이보다 키우면 잎 사이 간격까지 이어붙여 군락 전체를 '잎 하나'로 삼킨다(0.05에서 실측 확인). 0.025는 라벨셋 최고 정확도를 유지하면서 삼킴을 절반으로 줄인 값이다.
  - **검출은 축소본에서**(`DETECT_MAX_SIDE=1024`): 형태학 연산과 GrabCut 비용은 화소수·커널크기와 함께 폭증해, 원본 해상도로 돌리면 12MP 폰 사진 한 장이 gunicorn 타임아웃(120s)을 넘길 수 있었다. 좌표만 원본 배율로 되돌리고 **크롭 자체는 원본 해상도에서** 잘라 화질 손실이 없다. 12MP 기준 10배 빨라졌고 비식생 사진의 GrabCut 폴백도 0.85s로 묶인다.
  - **GrabCut 시드 고정**(`GRABCUT_SEED`): `cv2.grabCut`의 GMM 초기화는 OpenCV 전역 RNG를 써서, 시드를 안 심으면 같은 사진을 다시 진단할 때마다 bbox가 달라진다. 두 grabCut 호출 직전에 시드를 심는다.
  - **watershed 과분할 방지**: 겹친 잎 분할은 유지하되 게이트를 3중으로 걸었다 — 볼록도(면적/볼록껍질 ≥ 0.62면 잎 하나), 미세 코어 제거(최대 코어의 10% 미만), 지배 조각(최대 조각이 덩어리의 80% 이상이면 결과 폐기). 재결합된 덩어리와 화면 80% 초과 클로즈업도 분할 대상에서 뺀다. 실측 202장에서 watershed 발동이 63건 → 3건으로 줄었고, 그 63건 대부분이 단일 잎을 쪼개 bbox를 엉뚱한 조각에 그리던 오작동이었다.
- `weights/` — 배포용 슬림 체크포인트. `classification_model.pth`(38MB: state_dict + arch/epoch 메타만, optimizer/ConfigParser 없음 — `ckpt['state_dict']` 인덱싱은 여전히 필요)는 PlantVillage_GoogLeNet_6 checkpoint-epoch4의 사본으로, **"`*.pth` 커밋 금지" 규칙의 유일한 예외**다(.gitignore에 `!weights/classification_model.pth` 명시). `classes.json`(prepared6 12클래스, ImageFolder 정렬 순서)이 함께 있어 추론 시 학습 데이터셋 없이 클래스명을 복원한다 — `backend/ai/pipeline.py`가 체크포인트 옆의 이 파일을 자동 사용.
- `base/` — 이식된 템플릿 기반 클래스(`BaseModel`, `BaseDataLoader`, `BaseTrainer`). `base_trainer.py`가 모델·optimizer·scheduler·RNG 체크포인트 저장/재개와 config의 `monitor` 기준 best 관리를 담당한다.
- `trainer/trainer.py` — 학습/검증 루프. loss는 샘플 수로 가중하고 accuracy·macro_f1은 epoch 전체 예측으로 정확히 계산해 TensorBoard에 기록한다. lr은 수동 기록.
- `parse_config.py`, `logger/`, `utils/` — 템플릿 그대로.

산출물: `saved/models/{name}/{run}/`(체크포인트+config), `saved/log/{name}/{run}/`(TensorBoard `events` + `info.log`). `info.log`는 **INFO 레벨이라 epoch 요약만** 남고, 배치별 `Train Epoch ... Loss`는 DEBUG라 콘솔/TensorBoard에만 나온다.

## ViT-B/16 fine-tuning 설정

`config_vit3.json`은 ImageNet 사전학습 ViT-B/16 전체 계층을 `prepared3` 25클래스에 fine-tuning한다. `config_vit4.json`은 동일 설정을 `prepared4`(증강 완화판 25클래스)에 **epochs 10**으로 돌리는 증강 A/B 비교용이다(아래 하이퍼파라미터는 config_vit3 기준, epoch만 다름). `config_vit5.json`(prepared5 17클래스·20ep)·`config_vit6.json`(prepared6 12클래스·10ep)도 같은 fine-tuning 설정이다. `config_vit6_scratch.json`은 **`pretrained:false`로 ImageNet 없이 처음부터** 학습하는 변종(prepared6 12클래스·20ep, total_epochs도 20)으로 사전학습 효과 격리용이다 — 도메인 내는 ~99%로 근접하나 실사진 일반화가 크게 무너진다(아래 "실사진 교차평가" 참조).

- batch 64, AdamW(lr `1e-4`, weight decay `0.05`), 30 epoch
- 3 epoch linear warmup(`1e-5` → `1e-4`) 후 cosine decay(`1e-6`까지)
- cross-entropy label smoothing `0.1`, gradient clipping norm `1.0`
- CUDA AMP 사용, 초기 loss scale `1024`(batch 64 첫 update overflow 방지)
- best checkpoint 기준: 정확한 `val_macro_f1`

## GoogLeNet 특유의 함정 (핵심)

`model/model.py`의 `GoogLeNetPlant`는 `aux_logits=True`로 로드해야 loss1/loss2/loss3 분류기(`aux1.fc2`, `aux2.fc2`, `fc`)가 존재하며, 이 3개를 `num_classes` 출력으로 교체한다(config에 따라 38/25/17 — 하드코딩된 38은 `__init__` 기본값뿐이고 in_features는 기존 레이어에서 동적으로 읽는다). ViT는 `heads.head` 단일 헤드만 교체한다.

- **train()은 `GoogLeNetOutputs` namedtuple(logits, aux_logits2, aux_logits1), eval()은 `Tensor`를 반환한다.** `model/loss.py`·`model/metric.py`는 `torch.is_tensor()`로 두 경우를 분기한다 — 이 분기를 빠뜨리면 학습에서 크래시한다.
- 손실은 `cross_entropy`(raw logits용). 템플릿 기본 `nll_loss`가 아니다. 결합식: `loss3 + 0.3*(loss1 + loss2)`.
- 입력은 **224**(원본 256에서 crop). `transform_input=True`(사전학습 로드 시 자동) + DataLoader의 ImageNet 정규화 조합이 정답 — 둘 중 하나만 쓰면 안 된다.
- 학습·검증의 `macro_f1`은 epoch 전체 예측으로 계산하며, `test.py`도 test 전체셋으로 정확히 계산한다.

## 데이터로더 3-way split

`PlantVillageDataLoader(split='train'|'valid'|'test')` — `data_dir` 아래 `train/`·`valid/`·`test/`(ImageFolder 구조)를 가정한다. `split='train'`만 증강 전처리, 나머지는 평가 전처리(Resize 256→CenterCrop 224). `train.py`는 `split_validation()`으로 valid를, `test.py`는 `split='test'`로 test를 쓴다.

## 데이터셋 & 준비 워크플로우

**데이터셋 인벤토리·분할·증강·config 매핑의 정본은 `dataset.md`**(모든 prepared 버전, 원본/소스, 외부 교차도메인 §3, 스크립트 §5, config↔dataset 매핑 §6). 여기서는 학습에 직결되는 원칙만 요약하고 상세는 dataset.md를 본다.

- **config↔준비셋**: prepared2(38)→config.json, prepared3(25)→config3/config_vit3, prepared4(25)→config4/config_vit4, prepared5(17)→config5/config_vit5, prepared6(12)→config6/config_vit6/config_vit6_scratch. 구 `plantvillage_prepared`(이미지 단위 분할)는 **누수가 있어 미연결**. `prepared6`은 **prepared5의 부분집합**(Apple black_rot + Tomato bacterial/early/late/target 5클래스 제거 → 12클래스)이라 prepared5의 누수방지 분할·1,400장 균형화·완화 증강을 그대로 상속한다(부분집합이라 재분할 불필요). ⚠️ prepared6은 **repo(`dataset/`)에만** 있고 AgriSage엔 없다(경로 주의 — "규약/함정" 참조).
- **누수 방지 원칙**: prepared2 이후는 `leaf-map.json`으로 **물리적 잎 단위 그룹**을 만들어 한 잎의 모든 크롭이 한 split에만 들어가게 분할한다(prepared2/3은 7:1.5:1.5, prepared5는 7:2:1). 이미지 단위(구 `prepare_split.py`)로 나누면 같은 잎의 여러 각도 크롭이 train/valid/test에 흩어져 누수된다.
- **균형화·평가**: train만 클래스당 균형화(prepared2/3/4는 1,000장, prepared5는 1,400장; 초과 다운샘플/미달 증강), valid/test는 원본 분포를 유지해 **macro F1**으로 공정 평가한다. seed 42 고정.
- **증강**: prepared2/3은 강한 Keras식 7종(회전·플립·shift·shear·zoom·밝기·channel shift), prepared4/5는 완화판(channel shift·shear 제거, 밝기 ±10%). **색조는 병징 진단정보라 건드리지 않는다.**

## 외부 교차도메인 평가 (도메인 시프트)

`test_external.py`가 PlantVillage 학습 모델을 **촬영 조건이 다른 외부 실사진 데이터셋**(PlantPathology / GVLiD 포도 / TomatoLeafMulticlass / Multi-Crop)에 교차 평가한다. 외부 데이터는 어떤 PV 학습셋에도 없어 **누수 없는 순수 도메인 시프트** 평가다. (이전의 PlantDoc 교차평가를 대체 — PlantDoc은 라벨 품질이 낮아 제거함.)

- **매핑**: `dataset/external_test_mapping.csv`(`dataset, src_path, pv_class, quality`)가 외부 클래스 폴더를 PV 클래스에 **이름으로** 매칭한다. `test_external.py`는 체크포인트 config의 `data_dir/train`에서 모델의 클래스 목록을 읽어, 매핑된 PV 클래스 중 **모델에 존재하는 것만** 평가하고 나머지는 `not_in_model:*`로 제외한다 → **17/25/38클래스 모델 공용**(인덱스가 아니라 이름 기준이라 서브셋 모델에 자동 정렬).
- **매핑 원칙**: PV에 1:1로 대응하는 **exact 매핑만** 채택. 복합병·PV에 없는 병/작물·모호한 라벨은 제외. 근사 매핑은 `quality=weak`로 등록하고 `--quality`로 필터(현재 CSV는 exact 16행, PV 25클래스 중 16개 커버·7,270장). 상세 표는 `dataset.md` §3.
- **실행**: `"$PY" test_external.py -r saved/models/<name>/<run>/model_best.pth [--dataset gvlid] [--quality exact]`. 결과는 `saved/external_eval/<name>_<run>/`(metrics.json, per_class.csv, per_dataset.csv, confusion.csv/png, classification_report.txt).
- **함정:** GoogLeNet/Inception은 사전학습 로드 시 `transform_input=True`가 켜진 채 학습된다. 추론용으로 `pretrained=False`로 빌드하면 이 값이 꺼지고 `load_state_dict`로 복원되지 않아 입력 분포가 어긋난다(예측이 한 클래스로 붕괴). `test_external.py`의 `build_model`이 빌드 후 `backbone.transform_input=True`를 명시한다(ViT는 이 속성이 없어 자동 무시). `test.py`는 config의 `pretrained:true`로 빌드해 안전.
- 지표: 전체 accuracy, macro-F1(존재 클래스), per-class F1, **per-dataset accuracy**, 질병 vs healthy 정확도, 예측 분포(sink), 상위 혼동쌍, 평균 확신도(정답/오답).

## 실사진 교차평가 (new test dataset)

`dataset/new test dataset/`는 웹수집 **실사진** 소규모 수동셋으로, `apple/grape/tomato` → 병명 **2단계 폴더**(각 클래스 ~10장, 대부분 **비정사각**)다. crop/disease를 PV 클래스명에 매핑해 평가하며, 어떤 PV 학습셋에도 없어 누수 없는 도메인 시프트 평가다(`test_external.py`와 목적 동일, 이쪽은 소규모 수동셋 + 애드혹 스크립트, 결과는 `saved/newtest_eval/`).

- **비정사각 입력은 레터박스로 전처리**한다: 강제 정사각 리사이즈(잎 왜곡) 대신 비율 유지 리사이즈 후 정사각 캔버스에 여백 패딩. 여백색은 검정 또는 ImageNet 평균색(정규화 후 ≈0)이며 모델·데이터에 따라 최적이 갈린다.
- **핵심 발견**: 도메인 내 ~99% → 실사진 ~40~70%로 붕괴. ViT는 초기 에폭이 도메인 시프트에 더 강하다(과적합 전). **ImageNet 사전학습이 실사진 일반화에 결정적** — from-scratch ViT는 도메인 내 ~99%인데 실사진은 ~31%로 무너진다(사전학습판 ~70%). 즉 사전학습의 가치는 도메인 내 정확도가 아니라 도메인 시프트 견고성에 있다.
- ⚠️ 데이터 주의: `tomato/healthy`에는 도메인 내 샘플이 일부 섞여 있어 그 클래스 수치는 낙관 편향(수동 보강분).

## 규약 / 함정

- **`torch.load(..., weights_only=False)`** 필수(`test.py`, `base/base_trainer.py`). 체크포인트에 `ConfigParser` 객체가 함께 저장되는데 PyTorch 2.6+ 기본값 `weights_only=True`가 이를 거부한다.
- `utils/util.py`의 `MetricTracker`는 `.loc[key, col]` 방식으로 갱신한다(최신 pandas의 chained-assignment `FutureWarning` 폭주 회피).
- **`utils/util.py`의 `pandas` import는 `MetricTracker.__init__` 안 지연 import다 — 모듈 최상단으로 되돌리지 말 것.** 추론 경로가 `backend/ai/pipeline.py` → `predict` → `model.model` → `base/__init__` → `base_trainer` → `logger` → `utils` 순으로 이 모듈을 끌어오는데, 배포 컨테이너(`backend/requirements.txt`)에는 학습 전용 패키지인 pandas가 없다. 최상단 import면 Cloud Run에서 `_load_classifier()`가 `ModuleNotFoundError`로 죽어 **모든 진단이 500**이 된다(env1엔 pandas가 있어 로컬에선 멀쩡해 보인다). 학습 전용 패키지를 이 체인의 모듈에 새로 추가할 때도 같은 규칙을 지킬 것 — 검증은 `ai.pipeline.classify_image()`를 한 번 돌린 뒤 requirements.txt에 없는 패키지가 `sys.modules`에 들어왔는지 보면 된다.
- 데이터셋을 새로 나누면 **반드시 재학습**한다. 기존 모델을 새 test로 평가하면 그 test가 이전 train에 포함됐을 수 있어 누수가 된다.
- **data_dir 경로 불일치**: `config.json`~`config5`는 `/mnt/d/Project/QI/AgriSage/dataset/`를, `config6`~(config6/config_vit6/config_vit6_scratch)는 repo `backend/models/dataset/`를 가리킨다. 데이터셋이 두 위치에 나뉘어 있고 **prepared6은 repo에만** 있으니, 새 config를 만들 땐 데이터가 실제 있는 경로를 확인할 것.
- **StepLR 단축 학습 함정**: `epochs`와 `step_size`가 같으면(예: config4의 epochs 10·step_size 10) LR 감쇠가 마지막 에폭 뒤에 걸려 학습 중 **한 번도 적용되지 않는다**(사실상 lr 고정). 짧게 돌릴 땐 step_size를 줄일 것(config6은 step 4로 조정).
- `saved/`, `*.pth`, `dataset/`은 `.gitignore` 처리됨(체크포인트는 각 ~77MB). **유일한 예외**: 배포용 `weights/classification_model.pth`(38MB 슬림본) — 위 "아키텍처" 참조. 다른 체크포인트를 커밋하려 하지 말 것.
- 슬림 체크포인트에는 ConfigParser가 없어 어떤 `weights_only` 설정으로도 로드되지만, 학습 산출 체크포인트(saved/)는 여전히 `weights_only=False`가 필요하다.
- `leaf_detect.py`는 `backend/ai/pipeline.py`가 런타임에 import한다 — 시그니처를 바꾸면 백엔드 진단 API가 깨진다. torch를 import에 추가하지 말 것.
- 별도의 요청이 없으면 절대 git commit 하지 말것.
