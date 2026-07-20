# AgriSage

> Agriculture + Sage. "We don't just name the problem. We walk you through it."

작물 사진 한 장으로 병충해를 진단하고, 판단 근거를 설명하며, 사용자 상황에 맞는 방제 방법을 추천하고, 방제 이후까지 확인해주는 AI 기반 농업 지원 서비스입니다.

## 화면 구성 (모바일 퍼스트)

| 파일 | 화면 | 설명 |
|---|---|---|
| [`index.html`](index.html) | 홈 | 인사말, 진단 시작 CTA, 4단계 진단 흐름 안내, 서비스 차별점 카드 |
| [`crop-select.html`](crop-select.html) | 작물 선택 | 14개 작물(사과·체리·포도·오렌지·복숭아·블루베리·딸기·라즈베리·옥수수·감자·고추/피망·호박·콩·토마토)을 각 과일 고유 색으로 표시, 선택 후 다음 단계로 이동 |
| [`diagnose.html`](diagnose.html) | 사진 진단 | 선택한 작물 표시 → 잎사귀 사진 업로드 → AI 진단 결과 / 원인 / 방제 추천 / PLS 안전기준 경고 카드 (데모용 mock 데이터) |

## 사용자 흐름

```
홈 → 작물 선택 → 사진 업로드 → AI 진단 결과 확인
```

## 실행 방법

정적 HTML 파일이므로 브라우저에서 `index.html`을 열거나, 로컬 서버로 띄워 확인할 수 있습니다.

```bash
python -m http.server 8532 --directory AgriSage
```

## 참고

- 이 화면들은 프로토타입/데모이며, 실제 이미지 분류 모델·질병-농약 매핑 DB·PLS 데이터 연동은 포함되어 있지 않습니다.
- PRD 및 기술 요구사항은 팀 문서를 참고하세요.
