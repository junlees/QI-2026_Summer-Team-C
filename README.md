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
│   ├── landing.html        # 시작 화면 ("/"), 서비스 소개 + "Log in" 버튼
│   ├── login.html          # 로그인 폼 (제출하면 dashboard.html로)
│   ├── signup.html         # 회원가입 + 인증(관행/유기농) · 재배목적(자가소비/판매)
│   ├── dashboard.html      # 로그인 후 홈: 등록 작물, 진단 CTA, 사후관리 알림 배너
│   ├── crop-select.html    # 작물 등록: 14개 작물 + 재배환경/목적/수확예정일, 등록 목록
│   ├── diagnose.html       # 사진 업로드 (촬영 팁 포함) → diagnosis-result.html로 이동
│   ├── diagnosis-result.html # 진단 결과: 신호등(🟢🟡🔴), 원인/설명, 맞춤 추천, PHI 배너
│   ├── follow-up.html      # 사후관리 체크리스트 (3문항) → 결과 메시지 분기
│   ├── history.html        # 과거 진단 기록 목록 → 기록 조회 모드로 결과 페이지 재사용
│   ├── mypage.html         # 프로필 수정, 등록 작물 관리(수정/삭제), 알림 설정
│   ├── index.html          # (게스트 전용) 홈: 진단 시작 CTA, 4단계 흐름, 차별점 카드
│   ├── js/store.js         # localStorage 기반 mock 프로필/작물/이력 + mock AI 진단
│   ├── js/pwa.js           # 서비스워커 등록 (모든 페이지 공통 포함)
│   ├── sw.js                # 서비스워커: 오프라인 캐싱 (모든 페이지 프리캐시)
│   ├── manifest.webmanifest # PWA 매니페스트 (앱 이름/아이콘/테마색)
│   ├── icons/               # PWA 아이콘 (192/512/maskable/apple-touch/favicon)
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
시작 화면 → 로그인/회원가입 → 대시보드 → 작물 등록 → 사진 업로드
  → 진단 결과(신호등 + 설명 + 맞춤 추천) → 사후관리 체크 → (히스토리에서 재조회)
```

로그인 없이도 `landing.html`의 "Continue as guest"로 기존 `index.html`(단순 홈)
흐름을 그대로 써볼 수 있습니다. 로그인/회원가입 후에는 `dashboard.html`이 홈
역할을 하며, 등록된 작물과 사후관리 알림을 보여줍니다.

로그인 이후 화면들(대시보드/작물 등록/진단/결과/사후관리/히스토리/마이페이지)은
상단 헤더(로고 + Home·Diagnose·History·Profile 탭)를 공통으로 씁니다. 예전에는
이 네비게이션이 홈 화면 하단에만 있었는데, 상단 헤더로 옮기고 전체 화면에 통일해서
적용했습니다.

### 개인화 변수와 신호등 로직

- `certification`(관행/유기농): 계정 단위, 회원가입에서 수집
- `growing_environment`(노지/시설), `purpose`(자가소비/판매): 작물 단위, 작물
  등록에서 수집 (`purpose`는 계정 기본값을 작물별로 덮어쓸 수 있음)
- 진단 confidence가 70% 미만이면 병명을 확정하지 않고 🟡 상태로 전환해 전문가
  상담을 권장하며, severity가 "very high"면 confidence와 무관하게 🔴로 표시합니다.
- 재배목적이 "판매"인 작물은 진단 결과 화면에 PHI(수확 전 안전기간) 강조 배너가
  표시됩니다.

### Mock 데이터

백엔드에 아직 실제 모델/DB가 없어서, `frontend/js/store.js`가 `localStorage`로
프로필·작물·진단 이력을 흉내 내고 `mockDiagnose()`가 무작위로 진단 결과를
반환합니다. 실제 API가 준비되면 이 파일의 함수들을 `fetch()` 호출로 교체하면
됩니다 (엔드포인트 후보는 `CLAUDE.md` 참고).

## 하이브리드 (웹 + 앱)

AgriSage는 PWA(Progressive Web App)로 설정되어 있어서, 브라우저로 접속하는
"웹"과 홈 화면에 설치하는 "앱"을 같은 코드로 제공합니다.

- **모든 페이지**의 `<head>`에 `manifest.webmanifest` 링크, 아이콘, iOS용
  `apple-mobile-web-app-*` 메타 태그가 들어 있고, `js/pwa.js`가 서비스워커
  (`sw.js`)를 등록합니다.
- 브라우저에서: 그냥 URL로 접속하면 평범한 웹사이트로 동작합니다.
- 앱처럼 설치: Chrome/Edge/Android는 주소창의 설치 아이콘 또는 메뉴의
  "앱 설치", iOS Safari는 공유 → "홈 화면에 추가"로 설치할 수 있습니다.
  설치하면 주소창 없이 standalone 창으로 실행되고, 홈 화면 아이콘이 생깁니다.
- `sw.js`가 모든 HTML 페이지와 `css/styles.css`, `js/store.js`를 미리 캐싱해서
  오프라인이거나 네트워크가 불안정해도 이전에 방문한 화면은 열립니다. HTML은
  네트워크 우선(온라인이면 항상 최신), 나머지 정적 파일은 캐시 우선입니다.
- 프리캐시 목록이나 파일 이름을 바꾸면 `frontend/sw.js`의 `CACHE_NAME`
  버전을 올려주세요 (예: `agrisage-v1` → `agrisage-v2`) — 그래야 이미 설치된
  사용자의 기기에서도 새 캐시로 교체됩니다.
- 서비스워커는 HTTPS 또는 `localhost`에서만 등록됩니다. 로컬 개발
  (`http://localhost:5000`)은 문제없이 동작합니다.

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
