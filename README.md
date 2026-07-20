# AgriSage

> Agriculture + Sage. "We don't just name the problem. We walk you through it."

작물 사진 한 장으로 병충해를 진단하고, 판단 근거를 설명하며, 사용자 상황에 맞는 방제 방법을 추천하고, 방제 이후까지 확인해주는 AI 기반 농업 지원 서비스입니다.

## 폴더 구조

```
.
├── backend/                # Flask 서버 (배포 + 모델 연동)
│   ├── app.py              # 앱 진입점, 정적 서빙 + /api/diagnose
│   ├── requirements.txt
│   └── models/             # 진단 모델 코드/가중치 (연동 예정)
├── frontend/               # 정적 화면 (모바일 퍼스트), 스타일은 Tailwind CSS
│   ├── index.html          # 홈: 진단 시작 CTA, 4단계 흐름, 차별점 카드
│   ├── crop-select.html    # 작물 선택 (14개 작물)
│   ├── diagnose.html       # 사진 업로드 → AI 진단 결과 카드
│   ├── src/input.css       # Tailwind 진입점 (@tailwind + 커스텀 컴포넌트 클래스)
│   ├── css/styles.css      # 빌드 결과물 (커밋 안 함, npm run build로 생성)
│   ├── tailwind.config.js  # 커스텀 색상 팔레트 등 테마 설정
│   └── package.json
├── render.yaml             # Render 배포 설정
├── scripts/                # 로컬 환경 세팅 스크립트
│   ├── setup.sh            # macOS / Linux
│   └── setup.ps1           # Windows (PowerShell)
└── README.md
```

## 사용자 흐름

```
홈 → 작물 선택 → 사진 업로드 → AI 진단 결과 확인
```

## 처음 세팅 (다른 환경에서 클론했을 때)

Python 3.11 기준입니다. (`backend/.python-version` 참고)

**macOS / Linux**
```bash
./scripts/setup.sh
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
./scripts/setup.ps1
.\.venv\Scripts\Activate.ps1
```

가상환경 없이 바로 설치해도 됩니다:
```bash
pip install -r backend/requirements.txt
```

## 실행 방법

```bash
python backend/app.py          # http://localhost:5000
```

또는 배포 환경과 동일하게:

```bash
gunicorn --chdir backend app:app
```

## 프론트엔드 스타일 (Tailwind CSS)

`frontend/`는 Node/npm 기반 Tailwind CLI로 빌드합니다. `setup.sh`/`setup.ps1`이
자동으로 처리하지만, 프론트만 따로 작업할 때는:

```bash
cd frontend
npm install
npm run build     # css/styles.css 1회 생성
npm run watch     # 파일 저장할 때마다 자동 재빌드 (개발 중 켜두기)
```

- 각 HTML 파일은 Tailwind 유틸리티 클래스를 그대로 사용합니다. 커스텀 CSS는
  거의 없고, `.crop-card.selected`, `.next-btn.ready`, `.spinner.show`처럼
  JS가 `classList`로 토글하는 상태 클래스만 `frontend/src/input.css`의
  `@layer components`에 `@apply`로 정의되어 있습니다.
- 색상 팔레트(`page`, `app`, `ink`, `muted`, `accent`, `accent-dark`,
  `accent-soft`, `card`, `border`, `warn`)는 `frontend/tailwind.config.js`
  에서 관리합니다. 새 색을 쓸 때는 인라인 hex 대신 여기에 추가하세요.
- `frontend/css/styles.css`는 빌드 산출물이라 git에 커밋하지 않습니다
  (`.gitignore` 참고). 로컬에서 열어보려면 먼저 빌드해야 합니다.

## 참고

- 이 화면들은 프로토타입/데모이며, 실제 이미지 분류 모델·질병-농약 매핑 DB·PLS 데이터 연동은 포함되어 있지 않습니다.
- PRD 및 기술 요구사항은 팀 문서를 참고하세요.
