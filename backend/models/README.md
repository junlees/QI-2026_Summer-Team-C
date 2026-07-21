# models — 작물 질병 진단 모델

PlantVillage 기반 작물–질병 이미지 분류 모델. 학습/평가 파이프라인과 GoogLeNet·ViT
설정, 함정은 [`CLAUDE.md`](CLAUDE.md), 데이터셋 현황·분할 방식은 [`dataset.md`](dataset.md) 참고.

## 대용량 파일 (Google Drive)

데이터셋과 모델 가중치(`.pth`)는 용량이 커서 git에 넣지 않는다
(`.gitignore`로 `dataset/`, `saved/models/`, `*.pth` 제외). 아래 Google Drive에서
받아 각자 로컬에 복원한다.

- **Google Drive 링크:** https://drive.google.com/drive/folders/1ZzLuANU1kaVjakHur2wZtvO5snZ4zFyr?usp=sharing



### 받은 뒤 배치 (경로는 이 README 기준 상대경로)

| 받는 것 | 압축 해제 / 배치 위치 | 비고 |
|---|---|---|
| 데이터셋 (`plantvillage_prepared*` 등) | `dataset/` | ImageFolder 구조(`{train,valid,test}/<class>/*.jpg`, 256×256) |
| 모델 가중치 (`*.pth`) | `saved/models/<name>/<run>/` | 체크포인트 각 ~77MB |

- 학습에 실제로 쓰는 데이터셋: **`plantvillage_prepared2`**(38클래스 → `config.json`),
  **`plantvillage_prepared3`**(25클래스 → `config3.json`, `config_vit3.json`).
- `.zip`(`plantvillage_prepared*.zip`)으로 받았다면 `dataset/` 아래에 풀어 같은 이름의 폴더를 만든다.

### ⚠️ config의 `data_dir` 경로 수정

`config*.json`의 `data_loader.args.data_dir`는 절대경로
(`/mnt/d/Project/QI/AgriSage/dataset/...`)로 지정돼 있다. 데이터셋을 다른 위치에
복원했다면 이 값을 **본인이 푼 실제 경로**로 바꿔야 학습/평가가 동작한다.


# 학습
"$PY" train.py -c config.json

# 평가 (-r 옆의 config.json 자동 로드)
"$PY" test.py -r saved/models/<name>/<run>/model_best.pth
```
