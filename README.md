# QI-2026_Summer-Team-C

Pace Runner — 러너를 위한 실시간 자세 코칭 랜딩 페이지.

## 로컬 실행

```bash
npm install
npm start
```

`http://localhost:3000` 에서 확인할 수 있습니다.

## Render 배포

이 저장소에는 `render.yaml`이 포함되어 있어 Render에서 Blueprint로 바로 배포할 수 있습니다.

1. Render 대시보드에서 "New +" → "Blueprint" 선택
2. 이 GitHub 저장소 연결
3. `render.yaml` 설정이 자동으로 인식되어 Node 웹 서비스로 배포됨

수동으로 Web Service를 생성하는 경우:
- Build Command: `npm install`
- Start Command: `npm start`
- Health Check Path: `/healthz`

## 참고

- `login.html`의 로그인 폼은 프론트엔드 데모용이며 실제 인증 백엔드는 연결되어 있지 않습니다.
