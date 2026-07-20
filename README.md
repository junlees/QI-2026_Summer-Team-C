# AgriSage — 로컬 데모

작물 잎 사진으로 병충해를 진단하고, 설명 → 맞춤 방제 추천 → PLS 안전기준 체크 →
사후관리까지 이어지는 AgriSage PRD의 MVP 구현체입니다. `agrisage/` 디렉터리에
독립된 프로젝트로 구성되어 있습니다.

## 구성

```
agrisage/
  data/
    dataset/    PlantVillage 원본에서 추출한 8클래스 샘플 (140장/클래스)
    split/      train/val/test 분할 (70/15/15)
  backend/
    model/      학습 스크립트(train.py), 학습된 가중치(best_model.pt), classes.json
    app/        FastAPI 앱 (main.py) + 도메인 모듈
      classifier.py  FR-1 이미지 분류 추론
      explain.py     FR-2 LLM 기반 결과 설명 (Anthropic API, 키 없으면 템플릿 폴백)
      db.py          FR-3 질병-농약 매핑 DB 로더
      pls.py         FR-4 PLS(안전사용기간) 자동 체크
      followup.py    FR-5 사후관리 closed-loop (인메모리)
    data/pesticide_db.json  데모용 질병-농약 매핑 DB
  frontend/
    index.html  업로드 → 진단 → 설명 → 추천 → PLS → 사후관리 단일 페이지 UI
```

## 실행 방법

```bash
cd agrisage/backend
source .venv/bin/activate   # 이미 생성된 가상환경
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

브라우저에서 http://localhost:8000 접속. `/api/health`로 헬스체크 가능.

LLM 설명(FR-2)을 실제 Claude API로 받으려면 서버 실행 전 환경변수를 설정하세요:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

키가 없으면 자동으로 템플릿 기반 설명으로 동작합니다 (오프라인 테스트 가능).

질병-농약 매핑(FR-3)과 사후관리 케이스(FR-5)를 Postgres에 영속 저장하려면
서버 실행 전 `DATABASE_URL`을 설정하세요:

```bash
export DATABASE_URL=postgresql://user:password@host/dbname

cd agrisage/backend
python3 db/seed.py   # 스키마 생성 + pesticide_db.json 데이터 적재 (최초 1회)
```

`DATABASE_URL`이 없으면 자동으로 `pesticide_db.json` + 인메모리 저장소로 동작합니다
(오프라인 데모 가능, 서버 재시작 시 사후관리 케이스는 초기화됨).

## 데이터셋 준비 (최초 1회)

원본 이미지(1,120장)와 학습된 가중치(`best_model.pt`)는 저장소 용량 문제로
git에 포함하지 않았습니다. 아래 명령으로 PlantVillage 공개 저장소에서 필요한
8개 클래스만 받아옵니다 (git sparse-checkout, 약 1GB 다운로드 후 필요한 파일만
남기고 정리):

```bash
cd /tmp && git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/spMohanty/PlantVillage-Dataset.git pv
cd pv && git sparse-checkout set \
  "raw/color/Tomato___healthy" "raw/color/Tomato___Late_blight" \
  "raw/color/Tomato___Bacterial_spot" "raw/color/Potato___healthy" \
  "raw/color/Potato___Early_blight" "raw/color/Potato___Late_blight" \
  "raw/color/Apple___healthy" "raw/color/Apple___Apple_scab"

cd <repo>/agrisage/data/dataset
for d in /tmp/pv/raw/color/*/; do
  cls=$(basename "$d")
  mkdir -p "$cls"
  ls "$d" | shuf --random-source=<(yes 42) -n 140 | while read f; do
    cp "$d$f" "$cls/"
  done
done
rm -rf /tmp/pv
```

그다음 train/val/test로 분할(70/15/15)하고 모델을 학습합니다:

```bash
python3 agrisage/data/make_split.py   # data/split/ 생성

cd agrisage/backend
source .venv/bin/activate   # 없으면: python3 -m venv .venv && pip install -r requirements.txt
python3 model/train.py      # best_model.pt, classes.json, metrics.json 생성
```

## 이번 구현의 범위와 한계 (PRD 대비)

| 항목 | PRD 명시 | 이번 구현 |
|---|---|---|
| 분류 모델 | InceptionV3, ImageNet Pretrained Transfer Learning, 38클래스, 8.7만장+ | 이 세션 환경에서 `download.pytorch.org`, `huggingface.co` 등 사전학습 가중치 호스트가 네트워크 정책상 차단되어 있어, 동일한 CNN 구조를 **처음부터 학습**. PlantVillage에서 3개 작물 8클래스(사과/감자/토마토 × 질병 2~3종 + 건강), 클래스당 140장(총 1,120장)만 사용. Test accuracy **86.9%** |
| 질병-농약 DB | 사전 구축, 실제 등록 데이터 기반 | 데모용 예시 DB(`pesticide_db.json`), 3개 작물 5개 질병만 커버. **실제 배포 전 농촌진흥청 농약안전정보시스템 데이터로 교체/검증 필요** |
| LLM 설명 | 분류 결과만 근거로 설명 생성, 환각 방지 | Anthropic API 연동 완료 (system prompt로 "새 진단 금지" 강제). 키 미설정 시 템플릿 폴백 |
| PLS 체크 | 수확 예정일 vs 안전사용기간 비교, 경고 | 구현 완료 (`pls.py`), safe/violation/invalid 3단계 |
| 사후관리 | N일 후 알림 발송, 재사진 → 개선 판단 | 알림 발송(push/SMS)은 미구현 — 케이스 생성 및 재사진 업로드 시 즉시 판정만 구현 (데모용 인메모리 저장, 서버 재시작 시 초기화) |
| Out of Scope 항목 (구매 연동, 멀티턴 문진 등) | 제외 명시 | 동일하게 미구현 |

## 로컬 테스트 결과 요약

- `/api/pipeline`에 토마토 역병 테스트 이미지 업로드 → 71% 신뢰도로 정확히 분류,
  방제 제품 2종 추천, PLS 체크에서 구리수화제(PHI 3일)는 안전, 메탈락실엠(PHI 7일)은
  위반으로 정확히 구분됨을 확인.
- 사과 건강 이미지 → 97.7% 신뢰도로 정확히 건강 분류, 방제 추천/PLS 섹션 자동 숨김.
- 유기농 필터(`organic_only=true`) → 유기농 인증 제품만 필터링 확인.
- 사후관리 케이스 생성 후 건강한 재사진 업로드 → "improved" 판정 확인.
