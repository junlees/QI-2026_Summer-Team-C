# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

PlantVillage 38개 작물–질병 클래스 이미지 분류. ImageNet 사전학습 **GoogLeNet(InceptionV1)** 을 fine-tuning하며, Mohanty et al. 2016 "Using Deep Learning for Image-Based Plant Disease Detection"의 GoogLeNet transfer-learning 실험(Caffe solver 스펙: SGD, base lr 0.005, StepLR step 10/gamma 0.1, momentum 0.9, weight decay 0.0005, batch 24, 30 epoch)을 재현한다. 이후 5작물 25클래스·17클래스 서브셋과 ViT-B/16 fine-tuning 변종으로 확장했다(config3/4·config_vit3/4, prepared3/4/5). 구조는 [victoresque/pytorch-template](https://github.com/victoresque/pytorch-template)을 이식했다.

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
"$PY" train.py -c config.json                    # prepared2 38클래스 GoogLeNet
"$PY" train.py -c config3.json                   # prepared3 25클래스 GoogLeNet
"$PY" train.py -c config_vit3.json               # prepared3 25클래스 ViT-B/16 fine-tuning
"$PY" train.py -c config4.json                   # prepared4 25클래스 GoogLeNet (증강 완화·epochs 10)
"$PY" train.py -c config_vit4.json               # prepared4 25클래스 ViT-B/16 (증강 완화·epochs 10)
"$PY" train.py -c config.json -r saved/models/<name>/<run>/checkpoint-epochN.pth   # 재개
"$PY" train.py -c config.json --lr 0.005 --bs 32                                    # CLI 오버라이드

# 최종 평가 (test/ 폴더 전체셋 → Accuracy, Mean F1(macro), per-class F1, classification_report)
"$PY" test.py -r saved/models/<name>/<run>/model_best.pth   # -r만 줘도 옆의 config.json 자동 로드

# 추론 (predict.py: PlantVillage식 잎사진 직접 분류 / predict_leaf.py: 실사진→잎 검출→중앙 잎 크롭 256×256→분류)
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

단일 테스트 스위트 개념은 없다(연구용 파이프라인). 변경 검증은 짧은 파이썬 스니펫으로 모듈 import·모델 forward·데이터로더 1배치를 확인하는 "비학습 무결성 체크"로 한다.

## 아키텍처 (config 구동)

`config.json`이 파이프라인 전체를 선언한다. `ConfigParser.init_obj(name, module)`가 config의 `type`/`args`를 읽어 해당 모듈의 클래스를 **동적 생성**한다 — 새 모델/로더/스케줄러는 코드가 아니라 config에서 갈아끼운다.

- `train.py` — 오케스트레이터: `init_obj`로 data_loader/arch/optimizer/lr_scheduler 생성, loss/metric은 `getattr`로 함수 핸들 확보, `Trainer` 구동. 상단에서 Python/NumPy/Torch seed와 deterministic cuDNN 설정을 고정한다.
- `base/` — 이식된 템플릿 기반 클래스(`BaseModel`, `BaseDataLoader`, `BaseTrainer`). `base_trainer.py`가 모델·optimizer·scheduler·RNG 체크포인트 저장/재개와 config의 `monitor` 기준 best 관리를 담당한다.
- `trainer/trainer.py` — 학습/검증 루프. loss는 샘플 수로 가중하고 accuracy·macro_f1은 epoch 전체 예측으로 정확히 계산해 TensorBoard에 기록한다. lr은 수동 기록.
- `parse_config.py`, `logger/`, `utils/` — 템플릿 그대로.

산출물: `saved/models/{name}/{run}/`(체크포인트+config), `saved/log/{name}/{run}/`(TensorBoard `events` + `info.log`). `info.log`는 **INFO 레벨이라 epoch 요약만** 남고, 배치별 `Train Epoch ... Loss`는 DEBUG라 콘솔/TensorBoard에만 나온다.

## ViT-B/16 fine-tuning 설정

`config_vit3.json`은 ImageNet 사전학습 ViT-B/16 전체 계층을 `prepared3` 25클래스에 fine-tuning한다. `config_vit4.json`은 동일 설정을 `prepared4`(증강 완화판 25클래스)에 **epochs 10**으로 돌리는 증강 A/B 비교용이다(아래 하이퍼파라미터는 config_vit3 기준, epoch만 다름).

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

- **현재 config가 쓰는 준비셋**: `config.json`→`plantvillage_prepared2`(38클래스), `config3.json`/`config_vit3.json`→`prepared3`(25), `config4.json`/`config_vit4.json`→`prepared4`(25). 구 `plantvillage_prepared`(이미지 단위 분할)는 **누수가 있어 미연결**이며, `prepared5`(17)는 아직 전용 config가 없다.
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

## 규약 / 함정

- **`torch.load(..., weights_only=False)`** 필수(`test.py`, `base/base_trainer.py`). 체크포인트에 `ConfigParser` 객체가 함께 저장되는데 PyTorch 2.6+ 기본값 `weights_only=True`가 이를 거부한다.
- `utils/util.py`의 `MetricTracker`는 `.loc[key, col]` 방식으로 갱신한다(최신 pandas의 chained-assignment `FutureWarning` 폭주 회피).
- 데이터셋을 새로 나누면 **반드시 재학습**한다. 기존 모델을 새 test로 평가하면 그 test가 이전 train에 포함됐을 수 있어 누수가 된다.
- `saved/`, `*.pth`, `dataset/`은 `.gitignore` 처리됨(체크포인트는 각 ~77MB).
- 별도의 요청이 없으면 절대 git commit 하지 말것.
