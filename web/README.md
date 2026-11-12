# Fit-For-U 웹 (React)

화면 구성·문구·디자인은 조민상님 `fit-for-u.py`(Streamlit)를 옮겼고, 기능은 파이썬 API(`../code/api_server.py`)에 연결했습니다.

| 기능 | 연결된 것 |
|---|---|
| 날씨 | 기상청 단기예보 (`/weather`, 지역 선택 · 현재 위치) |
| 체형 분석 | 승민님 체형 군집 모델 (`/body/photo`, `/body/classify`) — 정면은 3군집, 애매하면 측면을 요청해 5군집 |
| 코디 추천 | 규칙 엔진 + K-Fashion 조합 모델 (`/web/recommend`) |
| 로그인 · 저장한 코디 · 후기 · Q&A · 👍👎 취향 | 회원 DB (`/auth/*`, `/saved`, `/reviews`, `/qna`, `/prefs` → `code/data/members.db`). 비밀번호는 솔트 해시, 로그인은 토큰(14일). 시연 계정 `test` / `1234` |
| 평가 참여 | 평가 프로토콜 §5 — 형태 1문항 · 줄자 실측 · 사진 · 체형 규칙 A/B(블라인드) · 만족도 설문 (`/study/*`, 익명 참가자 번호). 결과표는 `code/eval_study.py` |

## 실행

한 번에: 상위 폴더의 `start_fitforu.bat` 더블클릭 (API 서버와 웹을 켜고 브라우저를 엽니다).

직접 실행할 때:

```bash
# 1) API 서버 (code 폴더, 기상청 키는 .env 의 KMA_API_KEY)
cd ../code
PYTHONUTF8=1 .venv/Scripts/python.exe api_server.py --port 8770
```

```bash
# 2) 웹 (web-react 폴더)
npm install
npm run dev
```

브라우저에서 http://localhost:5173 을 엽니다. API 주소는 `.env.development` 의 `VITE_API` 로 바꿀 수 있습니다.

## 파일

- `src/App.jsx` — 로그인 상태, 헤더·메뉴, 페이지 이동(`#home` 등), 날씨 상태
- `src/pages.jsx` — 로그인/회원가입, 홈, 저장한 코디, 후기, 이용 안내, 마이페이지, Q&A
- `src/analysis.jsx` — 체형 분석 (카메라 촬영 · 사진 업로드 · 측정값 · 직접 선택)
- `src/recommend.jsx` — 코디 추천
- `src/study.jsx` — 평가 참여 (운영자 휴대폰 한 대로 참가자를 차례로 받음)
- `src/api.js` — API 호출 · 로그인 토큰 (브라우저에는 토큰만 남음)

## 알아 둘 점

- 사진은 브라우저에서 긴 변 1600px로 줄여 분석에만 보내고, 서버는 저장하지 않습니다.
- 사진 비율은 실측 보정 전 실험값이고, 군집→체형 이름 연결은 팀 합의 전 임시 기준입니다 (`../code/body_cluster_bridge.py` 의 `CLUSTER_BODY`).
