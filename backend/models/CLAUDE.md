# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

PlantVillage 38개 작물–질병 클래스 이미지 분류. ImageNet 사전학습 **GoogLeNet(InceptionV1)** 을 fine-tuning하며, Mohanty et al. 2016 "Using Deep Learning for Image-Based Plant Disease Detection"의 GoogLeNet transfer-learning 실험(Caffe solver 스펙: SGD, base lr 0.005, StepLR step 10/gamma 0.1, momentum 0.9, weight decay 0.0005, batch 24, 30 epoch)을 재현한다. 구조는 [victoresque/pytorch-template](https://github.com/victoresque/pytorch-template)을 이식했다.

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
"$PY" train.py -c config.json
"$PY" train.py -c config_vit3.json   # 25클래스 ViT-B/16 fine-tuning
"$PY" train.py -c config.json -r saved/models/<name>/<run>/checkpoint-epochN.pth   # 재개
"$PY" train.py -c config.json --lr 0.005 --bs 32                                    # CLI 오버라이드

# 최종 평가 (test/ 폴더 전체셋 → Accuracy, Mean F1(macro), per-class F1, classification_report)
"$PY" test.py -r saved/models/<name>/<run>/model_best.pth   # -r만 줘도 옆의 config.json 자동 로드

# TensorBoard (loss/val_accuracy/val_macro_f1/lr 곡선)
"$PY" -m tensorboard.main --logdir saved/log

# 데이터 준비 (원본 → stratified 7:2:1 분할 + train 균형 증강)
"$PY" dataset/prepare_split.py

# 라벨 CSV 재생성
"$PY" dataset/generate_labels.py
```

단일 테스트 스위트 개념은 없다(연구용 파이프라인). 변경 검증은 짧은 파이썬 스니펫으로 모듈 import·모델 forward·데이터로더 1배치를 확인하는 "비학습 무결성 체크"로 한다.

## 아키텍처 (config 구동)

`config.json`이 파이프라인 전체를 선언한다. `ConfigParser.init_obj(name, module)`가 config의 `type`/`args`를 읽어 해당 모듈의 클래스를 **동적 생성**한다 — 새 모델/로더/스케줄러는 코드가 아니라 config에서 갈아끼운다.

- `train.py` — 오케스트레이터: `init_obj`로 data_loader/arch/optimizer/lr_scheduler 생성, loss/metric은 `getattr`로 함수 핸들 확보, `Trainer` 구동. 상단에서 Python/NumPy/Torch seed와 deterministic cuDNN 설정을 고정한다.
- `base/` — 이식된 템플릿 기반 클래스(`BaseModel`, `BaseDataLoader`, `BaseTrainer`). `base_trainer.py`가 모델·optimizer·scheduler·RNG 체크포인트 저장/재개와 config의 `monitor` 기준 best 관리를 담당한다.
- `trainer/trainer.py` — 학습/검증 루프. loss는 샘플 수로 가중하고 accuracy·macro_f1은 epoch 전체 예측으로 정확히 계산해 TensorBoard에 기록한다. lr은 수동 기록.
- `parse_config.py`, `logger/`, `utils/` — 템플릿 그대로.

산출물: `saved/models/{name}/{run}/`(체크포인트+config), `saved/log/{name}/{run}/`(TensorBoard `events` + `info.log`). `info.log`는 **INFO 레벨이라 epoch 요약만** 남고, 배치별 `Train Epoch ... Loss`는 DEBUG라 콘솔/TensorBoard에만 나온다.

## ViT-B/16 fine-tuning 설정

`config_vit3.json`은 ImageNet 사전학습 ViT-B/16 전체 계층을 `prepared3` 25클래스에 fine-tuning한다.

- batch 64, AdamW(lr `1e-4`, weight decay `0.05`), 30 epoch
- 3 epoch linear warmup(`1e-5` → `1e-4`) 후 cosine decay(`1e-6`까지)
- cross-entropy label smoothing `0.1`, gradient clipping norm `1.0`
- CUDA AMP 사용, 초기 loss scale `1024`(batch 64 첫 update overflow 방지)
- best checkpoint 기준: 정확한 `val_macro_f1`

## GoogLeNet 특유의 함정 (핵심)

`model/model.py`의 `GoogLeNetPlant`는 `aux_logits=True`로 로드해야 loss1/loss2/loss3 분류기(`aux1.fc2`, `aux2.fc2`, `fc`)가 존재하며, 이 3개를 38출력으로 교체한다.

- **train()은 `GoogLeNetOutputs` namedtuple(logits, aux_logits2, aux_logits1), eval()은 `Tensor`를 반환한다.** `model/loss.py`·`model/metric.py`는 `torch.is_tensor()`로 두 경우를 분기한다 — 이 분기를 빠뜨리면 학습에서 크래시한다.
- 손실은 `cross_entropy`(raw logits용). 템플릿 기본 `nll_loss`가 아니다. 결합식: `loss3 + 0.3*(loss1 + loss2)`.
- 입력은 **224**(원본 256에서 crop). `transform_input=True`(사전학습 로드 시 자동) + DataLoader의 ImageNet 정규화 조합이 정답 — 둘 중 하나만 쓰면 안 된다.
- 학습·검증의 `macro_f1`은 epoch 전체 예측으로 계산하며, `test.py`도 test 전체셋으로 정확히 계산한다.

## 데이터로더 3-way split

`PlantVillageDataLoader(split='train'|'valid'|'test')` — `data_dir` 아래 `train/`·`valid/`·`test/`(ImageFolder 구조)를 가정한다. `split='train'`만 증강 전처리, 나머지는 평가 전처리(Resize 256→CenterCrop 224). `train.py`는 `split_validation()`으로 valid를, `test.py`는 `split='test'`로 test를 쓴다.

## 데이터셋 & 준비 워크플로우

`dataset/` 아래에 여러 소스가 공존한다:
- `PlantVillage-Dataset/raw/color/` — **원본** 54,305장(38클래스, 256×256). 클래스 불균형 심함(152~5,507장, 36배). `raw/segmented/`(배경 제거)와 `leaf_grouping/`(잎 그룹)도 있음.
- `plantvillage_prepared/` — **현재 config가 사용**. `dataset/prepare_split.py`가 생성.
- `New Plant Diseases Dataset(Augmented)/` — 외부 증강본(train/valid만). 회전·반전 위주로 증강 + 클래스 균등화됨. 증강 후 분할이라 **train/valid 누수 가능성**이 있어 valid 평가가 낙관적.
- `test_different_condition/` — 촬영 조건이 다른 33장(도메인 시프트 데모, 성능 급락).

**`prepare_split.py`의 원칙 (누수 방지):** 원본을 **먼저** stratified 7:2:1로 나눈 뒤 **train만** 클래스당 1,000장으로 균형화(초과 클래스 랜덤 다운샘플 / 미달 클래스 증강으로 채움). valid/test는 원본 그대로 두어 실제 분포를 유지하고 **macro F1**으로 공정 평가한다. 증강은 라벨 보존형(직각 회전 + 좌우/상하 반전 + 약한 밝기/대비만; **색조는 병징 진단정보라 건드리지 않음**). seed 42 고정.

## PlantDoc 교차 평가 & 라벨 매핑 (도메인 시프트)

`test_plantdoc.py`가 PlantVillage 학습 모델을 **PlantDoc 세그먼테이션 크롭**(`dataset/plantdoc_leaf_crops/`, bbox로 잘라낸 실사진 잎, `manifest.csv`에 crop_path·pd_class 등)에 교차 평가한다. PlantDoc은 웹수집 실사진이라 어떤 PV 학습셋에도 없어 **누수 없는 순수 도메인 시프트** 평가다. 결과는 `saved/plantdoc_eval/<name>_<run>/`(metrics.json, per_class.csv, confusion.csv/png, classification_report.txt).

25클래스 같은 서브셋 모델에서는 매핑된 PV 클래스 중 모델 출력에 포함된 클래스만 평가하고 나머지는 `not_in_model:*` 사유로 제외한다.

- 실행: `"$PY" test_plantdoc.py -r saved/models/<name>/<run>/model_best.pth [--split all|train|test]`
- **함정:** GoogLeNet/Inception은 사전학습 로드 시 `transform_input=True`가 켜진 채 학습된다. 추론용으로 `pretrained=False`로 빌드하면 이 값이 꺼지고 `load_state_dict`로 복원되지 않아 입력 분포가 어긋난다(예측이 한 클래스로 붕괴). 빌드 후 `model.backbone.transform_input = True`를 명시할 것(`test_plantdoc.py`·`predict.py`에 반영됨). `test.py`는 config의 `pretrained:true`로 빌드해 안전.
- 결과 요약: 도메인 내 ~99% → PlantDoc ~16%로 붕괴. 예측 대량이 `Corn_(maize)___healthy`(초록잎 흡인)로 쏠림. 살아남는 건 배경독립 텍스처(Squash 흰가루병 등). 누수방지(prepared2) 모델이 근소하게 가장 잘 일반화.

**PlantDoc(28 pd_class) → PlantVillage(38클래스) 권위 매핑** (`test_plantdoc.py`의 `PD2PV` 딕트가 이 표를 그대로 구현). 품질 `weak` = 근사/가정 매핑(정확도 해석 주의). 표에 없는 바 `Potato leaf`(11장)는 평가 제외:

| PD idx | PlantDoc 클래스 | PlantVillage 클래스 | PV idx | 품질 | 비고 |
|---|---|---|---|---|---|
| 0 | Apple Scab Leaf | Apple___Apple_scab | 0 | exact | |
| 1 | Apple leaf | Apple___healthy | 3 | exact | 일반잎→건강 가정 |
| 2 | Apple rust leaf | Apple___Cedar_apple_rust | 2 | exact | |
| 3 | Bell_pepper leaf | Pepper,_bell___healthy | 19 | exact | 일반잎→건강 가정 |
| 4 | Bell_pepper leaf spot | Pepper,_bell___Bacterial_spot | 18 | **weak** | leaf spot↔세균점무늬 근사 |
| 5 | Blueberry leaf | Blueberry___healthy | 4 | exact | 일반잎→건강 가정 |
| 6 | Cherry leaf | Cherry_(including_sour)___healthy | 6 | exact | 일반잎→건강 가정 |
| 7 | Corn Gray leaf spot | Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot | 7 | exact | |
| 8 | Corn leaf blight | Corn_(maize)___Northern_Leaf_Blight | 9 | exact | |
| 9 | Corn rust leaf | Corn_(maize)___Common_rust_ | 8 | exact | |
| 10 | Peach leaf | Peach___healthy | 17 | exact | 일반잎→건강 가정 |
| 11 | Potato leaf early blight | Potato___Early_blight | 20 | exact | |
| 12 | Potato leaf late blight | Potato___Late_blight | 21 | exact | |
| 13 | Raspberry leaf | Raspberry___healthy | 23 | exact | 일반잎→건강 가정 |
| 14 | Soyabean leaf | Soybean___healthy | 24 | **weak** | 철자 Soyabean→Soybean, 건강 가정 |
| 15 | Squash Powdery mildew leaf | Squash___Powdery_mildew | 25 | exact | |
| 16 | Strawberry leaf | Strawberry___healthy | 27 | **weak** | PV 딸기 병징은 Leaf_scorch뿐, 건강 가정 |
| 17 | Tomato Early blight leaf | Tomato___Early_blight | 29 | exact | |
| 18 | Tomato Septoria leaf spot | Tomato___Septoria_leaf_spot | 32 | exact | |
| 19 | Tomato leaf | Tomato___healthy | 37 | exact | 일반잎→건강 가정 |
| 20 | Tomato leaf bacterial spot | Tomato___Bacterial_spot | 28 | exact | |
| 21 | Tomato leaf late blight | Tomato___Late_blight | 30 | exact | |
| 22 | Tomato leaf mosaic virus | Tomato___Tomato_mosaic_virus | 36 | exact | |
| 23 | Tomato leaf yellow virus | Tomato___Tomato_Yellow_Leaf_Curl_Virus | 35 | exact | |
| 24 | Tomato mold leaf | Tomato___Leaf_Mold | 31 | exact | |
| 25 | Tomato two spotted spider mites leaf | Tomato___Spider_mites Two-spotted_spider_mite | 33 | exact | test 0장(train만 2장) |
| 26 | grape leaf | Grape___healthy | 14 | exact | 일반잎→건강 가정 |
| 27 | grape leaf black rot | Grape___Black_rot | 11 | exact | |

매핑은 **PV 38클래스 중 29개만** 커버한다. PlantDoc에 대응이 없는 **9개 PV 클래스**(평가 제외): `Apple___Black_rot`(1), `Cherry_(including_sour)___Powdery_mildew`(5), `Corn_(maize)___healthy`(10), `Grape___Esca_(Black_Measles)`(12), `Grape___Leaf_blight_(Isariopsis_Leaf_Spot)`(13), `Orange___Haunglongbing_(Citrus_greening)`(15), `Peach___Bacterial_spot`(16), `Strawberry___Leaf_scorch`(26), `Tomato___Target_Spot`(34). 이 중 `Corn_(maize)___healthy`는 GT엔 없지만 모델이 예측을 가장 많이 쏟아내는 sink다.

## 규약 / 함정

- **`torch.load(..., weights_only=False)`** 필수(`test.py`, `base/base_trainer.py`). 체크포인트에 `ConfigParser` 객체가 함께 저장되는데 PyTorch 2.6+ 기본값 `weights_only=True`가 이를 거부한다.
- `utils/util.py`의 `MetricTracker`는 `.loc[key, col]` 방식으로 갱신한다(최신 pandas의 chained-assignment `FutureWarning` 폭주 회피).
- 데이터셋을 새로 나누면 **반드시 재학습**한다. 기존 모델을 새 test로 평가하면 그 test가 이전 train에 포함됐을 수 있어 누수가 된다.
- `saved/`, `*.pth`, `dataset/`은 `.gitignore` 처리됨(체크포인트는 각 ~77MB).
- 별도의 요청이 없으면 절대 git commit 하지 말것.
