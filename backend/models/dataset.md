# 데이터셋 정리 (dataset.md)

AgriSage `dataset/` 폴더의 데이터셋 현황 정리. 최종 갱신: 2026-07-21.
모든 학습용 데이터는 **ImageFolder 구조**(`{train,valid,test}/<class>/*.jpg`, 256×256 RGB)이며,
224 리사이즈·ImageNet 정규화는 디스크가 아니라 `data_loader`가 담당한다.

---

## 1. 학습용 준비 데이터셋 (현재 핵심)

| 데이터셋 | 클래스 | train / valid / test | 분할 방식 | 증강(train) | 생성 스크립트 | 연결 config |
|---|---|---|---|---|---|---|
| `plantvillage_prepared` | 38 | 38,004 / 10,859 / 5,450 | 이미지 단위 7:2:1 | 약함(직각회전·플립·밝기/대비) | `prepare_split.py` | (구버전, 현재 미연결) |
| **`plantvillage_prepared2`** ⭐ | 38 | 38,000 / 8,132 / 8,204 | **잎그룹 7:1.5:1.5 (누수방지)** | 강함(Keras식 7종) | `prepare_split2.py` | `config.json` |
| **`plantvillage_prepared3`** ⭐ | 25 | 25,000 / 4,731 / 4,689 | prepared2 상속(5작물 서브셋) | prepared2 상속 | `prepare_split3.py` | `config3.json`, `config_vit3.json` |
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

---

## 2. 원본 / 소스

`dataset/PlantVillage-Dataset/`
- `raw/color/` — **원본** 54,305장, 38클래스, 256×256 RGB. 클래스 불균형 심함(152~5,507장, 약 36배).
- `raw/segmented/` — 배경 제거본(파일명 `_final_masked`). `raw/grayscale/`도 있음.
- `leaf_grouping/` — 잎 그룹 CSV → `leaf-map.json`(40,328 keys → 7,946 물리적 잎 그룹). `prepare_split2.py`의 누수방지 분할 근거.
  - 조인: 파일명 `<uuid>___<source-id>.JPG`의 source-id를 `leaf-map.json`에 조회. canonical 알고리즘은 `plant_village.py:184-210`.

---

## 3. PlantDoc (교차 평가 / 도메인 시프트)

PlantDoc는 **웹수집 실사진**이라 어떤 PlantVillage 학습셋에도 없어 **누수 없는 순수 도메인 시프트** 평가에 사용.

| 폴더 | 내용 |
|---|---|
| `PlantDoc-Object-Detection-Dataset/` | Pascal-VOC 객체탐지(bbox). 크롭 생성 소스. |
| **`plantdoc_leaf_crops/`** ⭐ | bbox로 잘라낸 잎 크롭 **8,889장**(train 8,437 / test 452), 29 pd_class, 가변 크기 RGB. `manifest.csv`에 pd_class→pv_class 매핑 내장. `test_plantdoc.py`가 사용. |
| `PlantDoc-Dataset-master/` | 원본 PlantDoc 분류(전체 이미지), train 28cls / test 27cls. |
| `PlantDoc_cleaned/` | `clean_plantdoc.py`로 필터링한 전체 이미지(현재 test만). |

- **라벨 매핑**: PlantDoc 28 pd_class → PlantVillage 38클래스(29개 커버). 권위 표는 **`CLAUDE.md`의 "PlantDoc 교차 평가 & 라벨 매핑"** 섹션과 `test_plantdoc.py`의 `PD2PV` 딕트에 있음(품질 exact/weak).
- **결과 요약**: 도메인 내 ~99% → PlantDoc ~16%로 붕괴. 예측 대량이 `Corn_(maize)___healthy`(초록잎 흡인)로 쏠림. 결과는 `saved/plantdoc_eval/<model>/`.
- **함정**: GoogLeNet은 `transform_input=True`로 학습됨 → 추론 시 명시 필요(ViT는 해당 없음).

---

## 4. 외부 / 기타

| 폴더 | 내용 |
|---|---|
| `New Plant Diseases Dataset(Augmented)/` | Kaggle 외부 증강본(train/valid만, ~2,000/cls). 증강 후 분할이라 **train/valid 누수 가능성** → valid 평가 낙관적. |
| `test_different_condition/` | 촬영 조건이 다른 33장(도메인 시프트 데모, 성능 급락). |
| `labels.csv` + `generate_labels.py` | 라벨 메타 CSV(위 Kaggle 증강본 대상). 학습 파이프라인과 무관. |
| `vertex_*` (스크립트 산출) | Google Vertex AI import용 매핑. |

---

## 5. 스크립트 (`dataset/*.py`)

| 스크립트 | 역할 |
|---|---|
| `prepare_split.py` | raw/color → `prepared` (이미지단위 7:2:1, 누수 있음) |
| `prepare_split2.py` | raw/color → `prepared2` (잎그룹 7:1.5:1.5 누수방지 + 강한 증강) |
| `prepare_split3.py` | prepared2 → `prepared3` (5작물 25클래스 서브셋 복사) |
| `crop_plantdoc_leaves.py` | PlantDoc OD → `plantdoc_leaf_crops` (bbox 크롭 + manifest) |
| `clean_plantdoc.py` | PlantDoc 전체이미지 필터링 → `PlantDoc_cleaned` |
| `build_pv_subsets.py`, `make_subset.py` | 소규모 서브셋(subset_5k 등) 생성 |
| `filter_matched_subset.py`, `make_vertex_import.py`, `generate_labels.py` | 매칭 서브셋·Vertex import·라벨 CSV 유틸 |

---

## 6. 규약 / 주의

- **누수 방지**가 최우선: 새로 학습·평가할 때는 `prepared2`(38) 또는 `prepared3`(25)를 사용. 구 `prepared`는 누수 있음.
- **데이터셋을 새로 나누면 반드시 재학습**한다. 기존 모델을 새 test로 평가하면 그 test가 이전 train에 포함됐을 수 있어 누수가 된다.
- `dataset/`·`saved/`·`*.pth`는 `.gitignore` 처리됨.
- 학습 config 대응: `config.json`→prepared2(38, GoogLeNet), `config3.json`→prepared3(25, GoogLeNet), `config_vit3.json`→prepared3(25, ViT).
- 상세 파이프라인/함정은 `CLAUDE.md` 참조.
