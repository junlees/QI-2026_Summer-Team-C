# 데이터셋 정리 (dataset.md)

AgriSage `dataset/` 폴더의 데이터셋 현황 정리. 최종 갱신: 2026-07-23.
모든 학습용 데이터는 **ImageFolder 구조**(`{train,valid,test}/<class>/*.jpg`, 256×256 RGB)이며,
224 리사이즈·ImageNet 정규화는 디스크가 아니라 `data_loader`가 담당한다.

---

## 1. 학습용 준비 데이터셋 (현재 핵심)

| 데이터셋 | 클래스 | train / valid / test | 분할 방식 | 증강(train) | 생성 스크립트 | 연결 config |
|---|---|---|---|---|---|---|
| `plantvillage_prepared` | 38 | 38,004 / 10,859 / 5,450 | 이미지 단위 7:2:1 | 약함(직각회전·플립·밝기/대비) | `prepare_split.py` | (구버전, 현재 미연결) |
| **`plantvillage_prepared2`** ⭐ | 38 | 38,000 / 8,132 / 8,204 | **잎그룹 7:1.5:1.5 (누수방지)** | 강함(Keras식 7종) | `prepare_split2.py` | `config.json` |
| **`plantvillage_prepared3`** ⭐ | 25 | 25,000 / 4,731 / 4,689 | prepared2 상속(5작물 서브셋) | prepared2 상속(강한 7종) | `prepare_split3.py` | `config3.json`, `config_vit3.json` |
| **`plantvillage_prepared4`** | 25 | 25,000 / 4,731 / 4,689 | prepared3 상속(동일 분할) | **완화**(channel shift·shear 제거, 밝기 ±10%) | `prepare_split4.py` | `config4.json`, `config_vit4.json` |
| **`plantvillage_prepared5`** | 17 | 23,800 / 4,990 / 2,530 | **잎그룹 7:2:1** (원본 재분할) | 완화(prepared4식), train 1,400/class | `prepare_split5.py` | (미연결) |
| `plantvillage_subset_5k` | 38 | 5,016 / 1,426 / 716 | 소규모 빠른 실험용 | — | `build_pv_subsets.py`/`make_subset.py` | (미연결) |

### 핵심: `prepared` vs `prepared2` (누수)
- `prepared`는 **이미지 단위** 분할이라, PlantVillage가 같은 물리적 잎을 여러 각도로 찍은 크롭들이
  train/valid/test로 흩어져 **데이터 누수**가 발생 → valid/test 성능이 낙관적으로 부풀려짐.
- `prepared2`는 `leaf-map.json`으로 **물리적 잎 단위 그룹**을 만들어 한 잎의 모든 크롭이 한 split에만
  들어가도록 분할(그룹 무겹침 검증 통과). 커버리지 75.7%, 미매핑 이미지는 `fallback_<source-id>` 싱글턴.
- 증강 7종(train만, Keras ImageDataGenerator식): 회전·플립·shift·shear·zoom·밝기·channel shift.
  train은 클래스당 **1000장**으로 균형화(대형 다운샘플/소형 증강), valid/test는 원본 분포 유지(macro-F1 공정 평가).

### `prepared3` (5작물 25클래스)
- `prepared2`에서 **apple / corn / grape / potato / tomato** 5작물의 클래스 폴더만 복사(재분할 없이 누수방지 분할 상속).
- 클래스 구성: Apple 4 + Corn_(maize) 4 + Grape 4 + Potato 3 + Tomato 10 = **25**.
- ⚠️ 25클래스라 **클래스 인덱스가 0~24로 새로 매겨짐**(prepared2의 38-인덱스와 다름) → `num_classes: 25` 필요.

### `prepared4` (prepared3와 동일 분할, 증강만 완화)
- `prepare_split4.py`가 prepared3의 valid/test를 그대로 복사하고, train도 **원본(비-`_aug`) 이미지는 그대로 복사**한 뒤 클래스당 **1,000장**이 될 때까지 부족분만 새 증강으로 채운다 → 분할·원본·다운샘플 선택이 prepared3와 **완전 동일**, 오직 train 증강분만 다르다(증강 기법 A/B 비교용). seed 42.
- 증강 변경(prepared2/3의 강한 7종 대비): **channel shift 제거 · shear 제거 · 밝기 ±15%→±10%**. 유지: 회전 ±20°·shift ±10%·zoom 0.85~1.15·좌우/상하 반전.
- 클래스 구성은 prepared3와 동일한 **25클래스**, train 25,000 / valid 4,731 / test 4,689. 학습 시 `num_classes: 25`, `data_dir`를 prepared4로 → `config4.json`(GoogLeNet)·`config_vit4.json`(ViT). 두 config는 prepared3용(config3/config_vit3)과 동일 계열이나 **epochs 10**으로 축소됨.

### `prepared5` (17클래스, 7:2:1, train 1,400/class)
- **원본 raw/color에서 새로 분할**(비율이 7:2:1로 달라 prepared2/3/4의 7:1.5:1.5 분할을 재사용할 수 없음).
- 클래스 **17개**: Apple 4 + Grape 4 + Tomato 9 (**Corn·Potato 작물 전체 + Tomato mosaic virus 제외**). 인덱스 0~16으로 새로 매겨짐 → `num_classes: 17`.
- 잎-그룹 단위 **7:2:1** 분할(`leaf-map.json` 조인, 그룹 무겹침 검증 `verify_no_leakage` 통과), train 클래스당 **1,400장**으로 균형화(초과 클래스 다운샘플/미달 클래스 증강), valid/test는 자연 분포 유지. seed 42.
- 증강: **완화(prepared4 방식)** — channel shift·shear 제거, 밝기 ±10%.
- train 23,800 / valid 4,990 / test 2,530. 학습 시 `num_classes: 17`, `data_dir`를 prepared5로. **전용 config는 아직 없음**(config5 미작성).

---

## 2. 원본 / 소스

`dataset/PlantVillage-Dataset/`
- `raw/color/` — **원본** 54,305장, 38클래스, 256×256 RGB. 클래스 불균형 심함(152~5,507장, 약 36배).
- `raw/segmented/` — 배경 제거본(파일명 `_final_masked`). `raw/grayscale/`도 있음.
- `leaf_grouping/` — 잎 그룹 CSV → `leaf-map.json`(40,328 keys → 7,946 물리적 잎 그룹). `prepare_split2.py`의 누수방지 분할 근거.
  - 조인: 파일명 `<uuid>___<source-id>.JPG`의 source-id를 `leaf-map.json`에 조회. canonical 알고리즘은 `plant_village.py:184-210`.

---

## 3. 외부 교차도메인 테스트셋 (도메인 시프트)

PlantVillage(실험실 촬영)와 **촬영 조건이 다른 실사진 데이터셋**들을 PlantVillage 라벨에 매칭해
**누수 없는 도메인 시프트 평가**에 사용. 매핑은 `dataset/external_test_mapping.csv`에 있고
`test_external.py`가 소비한다(클래스 **이름**으로 매칭 → 25/38클래스 모델 공용).

| 폴더 | 작물 | 원본 클래스 → 매핑 |
|---|---|---|
| `PlantPathology_sorted/` | Apple | Apple_Scab / Cedar_Apple_Rust / Healthy (Complex_MultipleDiseases 제외) |
| `GVLiD GrapeVine.../` | Grape | Black rot / esca / leaf blight / healthy — **PV 포도 4클래스 완전 매칭** |
| `TomatoLeafMulticlass_sorted/` | Tomato | Bacterial_Spot / Early_Blight / Late_Blight / Leaf_Mold / Target_Spot (Black_Spot·unknown_0 제외) |
| `Multi-Crop Leaf Disease.../` | Corn·Potato·Tomato | Maize healthy / Potato Healthy / Tomato healthy / Tomato septoria (Cashew·Rice·streak·Fungi·Nematode·verticillium 제외) |

- **매핑 규모**: exact 매핑 16개 행 → **PV 25클래스 중 16개 커버, 7,270장**. 미커버 9클래스(Apple Black_rot,
  Corn 병해 2종, Grape 없음, Potato 병해 2종, Tomato Spider_mites·YLCV·mosaic).
- **매핑 원칙**: PV에 1:1로 대응하는 **exact 매핑만** 채택. 복합병(Complex_MultipleDiseases)·PV에 없는 병
  (Tomato verticillium wilt, Maize streak virus 등)·PV에 없는 작물(Cashew, Rice)·모호한 라벨
  (Potato Fungi, Tomato Black_Spot)은 제외. 근사 매핑(예: Maize leaf blight→Northern_Leaf_Blight)은
  `quality=weak`로 CSV에 추가하고 `--quality`로 필터 가능(현재는 exact만 등록).
- `Tomato Leaf Dataset .../` (Annotated, images+labels 객체탐지 원본)은 `TomatoLeafMulticlass_sorted`의
  소스라 **중복이므로 매핑 제외**.
- **실행**: `"$PY" test_external.py -r saved/models/<name>/<run>/model_best.pth [--dataset gvlid] [--quality exact]`.
  결과는 `saved/external_eval/<name>_<run>/`(metrics.json, per_class.csv, per_dataset.csv, confusion.csv/png).
- **함정**: GoogLeNet/Inception은 `transform_input=True`로 학습됨 → 추론 시 명시 필요(`test_external.py`에 반영, ViT는 해당 없음).

---

## 4. 외부 / 기타

| 폴더 | 내용 |
|---|---|
| `New Plant Diseases Dataset(Augmented)/` | Kaggle 외부 증강본(train/valid만, ~2,000/cls). 증강 후 분할이라 **train/valid 누수 가능성** → valid 평가 낙관적. |
| `labels.csv` + `generate_labels.py` | 라벨 메타 CSV(위 Kaggle 증강본 대상). 학습 파이프라인과 무관. |
| `vertex_*` (스크립트 산출) | Google Vertex AI import용 매핑. |

---

## 5. 스크립트 (`dataset/*.py`)

| 스크립트 | 역할 |
|---|---|
| `prepare_split.py` | raw/color → `prepared` (이미지단위 7:2:1, 누수 있음) |
| `prepare_split2.py` | raw/color → `prepared2` (잎그룹 7:1.5:1.5 누수방지 + 강한 증강) |
| `prepare_split3.py` | prepared2 → `prepared3` (5작물 25클래스 서브셋 복사) |
| `prepare_split4.py` | prepared3 → `prepared4` (동일 분할, train 증강만 완화 재생성, 클래스당 1,000) |
| `prepare_split5.py` | raw/color → `prepared5` (17클래스 잎그룹 7:2:1, train 1,400, 완화 증강) |
| `build_pv_subsets.py`, `make_subset.py` | 소규모 서브셋(subset_5k 등) 생성 |
| `make_vertex_import.py`, `generate_labels.py` | Vertex import·라벨 CSV 유틸 |
| `external_test_mapping.csv` (데이터) | 외부 교차도메인 테스트셋 → PV 클래스 매핑(§3, `test_external.py`가 소비) |

---

## 6. 규약 / 주의

- **누수 방지**가 최우선: 새로 학습·평가할 때는 `prepared2`(38)/`prepared3`(25)/`prepared4`(25)/`prepared5`(17)를 사용(모두 누수방지 잎그룹 분할). 구 `prepared`는 누수 있음.
- **데이터셋을 새로 나누면 반드시 재학습**한다. 기존 모델을 새 test로 평가하면 그 test가 이전 train에 포함됐을 수 있어 누수가 된다.
- `dataset/`·`saved/`·`*.pth`는 `.gitignore` 처리됨.
- 학습 config 대응: `config.json`→prepared2(38, GoogLeNet), `config3.json`→prepared3(25, GoogLeNet), `config_vit3.json`→prepared3(25, ViT), `config4.json`→prepared4(25, GoogLeNet), `config_vit4.json`→prepared4(25, ViT). prepared5(17)용 config는 아직 없음.
- 상세 파이프라인/함정은 `CLAUDE.md` 참조.
