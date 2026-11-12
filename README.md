# Fit-For-U

체형 · 날씨 · 상황(TPO) · 취향을 함께 고려해 오늘 입을 코디를 추천하는 서비스입니다. (인공지능 수업 팀 프로젝트, 2조)

- **백엔드** (`backend/`) — 규칙 엔진 + K-Fashion 조합 모델로 코디 3안과 추천 이유를 만들고, 회원·저장한 코디·후기·Q&A·👍👎 취향을 SQLite 로 관리하는 파이썬 API (표준 라이브러리 HTTP 서버).
- **웹** (`web/`) — React + Vite 화면. 체형 분석(카메라·사진·측정값·직접 선택), 코디 추천, 비슷한 옷 보기, 좋아하는/피하고 싶은 색·퍼스널 컬러·머리 길이 선택, 저장한 코디, 후기, Q&A.

## 빠른 실행

```bash
# 1) 백엔드 (Python 3.11)
cd backend
pip install -r requirements.txt
python api_server.py --port 8770          # http://127.0.0.1:8770

# 2) 웹 (Node 20+)
cd web
npm install
npm run dev                                # http://localhost:5173  (/api → 127.0.0.1:8770 으로 전달)
```

- 처음 실행하면 `backend/data/members.db` 가 만들어지고 시연 계정 `test` / `1234` 가 들어갑니다. 외부에 열 때는 `FFU_NO_DEMO=1 python api_server.py` 로 시연 계정을 만들지 않게 하세요.
- 날씨(기상청 단기예보)는 `KMA_API_KEY` 환경변수가 있어야 불러옵니다 (키는 포함되어 있지 않습니다). 없으면 화면에서 날씨를 직접 입력할 수 있어요.
- 배포용 빌드: `VITE_API=/api npm run build` 후 `npx vite preview` (개발 서버는 연결이 끊겼다 돌아오면 페이지를 새로고침합니다).
- 테스트: `cd backend && python test_rule_engine.py && python test_web_bridge.py && python test_web_feedback.py && python test_api_server.py`

## 이 저장소에 들어 있는 것 / 없는 것

| 구분 | 상태 |
|---|---|
| 소스 코드 (백엔드·웹), 규칙 JSON(`backend/rules`), 평가 보고서(`backend/runs/*.md`) | 포함 |
| 가공 데이터 JSON 12개 (`backend/data`), 학습 모델 11개 (`backend/models`) | 포함 — 아래 "데이터 출처" 참고 |
| 코디 사진·제품 컷·AI 생성 이미지(`data/gen_items` 등), 원본 데이터셋 | **미포함** — 이미지 칸은 아이콘으로 표시됩니다 |
| 회원 DB, 사용자 취향 기록, 업로드 사진 | **미포함** (사진은 서버에 저장하지 않고 메모리에서만 분석) |
| 체형 분석 모델 (`body_models/`, 팀원 작업물) | **미포함** — 없으면 `/body/*` 만 안내 메시지(400)로 응답하고 나머지는 그대로 동작합니다. 웹에서는 '체형 직접 선택'을 쓰세요 |
| API 키·비밀번호 | 미포함 |

## 데이터 출처

추천 통계(아이템 후보·함께 입는 조합·색·스타일 통계, 조합 학습 모델)는 다음 공개 데이터에서 **가공**한 값입니다. 원본 데이터와 이미지는 이 저장소에 없으며, 원본의 이용 조건은 각 제공처를 따릅니다.

- AI Hub K-Fashion 이미지 · 143.패션상품 및 착용 영상 · 의류 통합 데이터
- Polyvore Outfits · Zappos (신발 통계, 서구·여성 편향 있음)

가공 방법과 한계는 `backend/README.md`, 평가 결과는 `backend/runs/` 를 보세요. (두 README 는 폴더 이름이 `code/`, `web-react/` 이던 시절에 쓰여서 경로가 `code/` · `web-react/` 로 적혀 있습니다. 이 저장소에서는 각각 `backend/` · `web/` 입니다.)

## 알려진 한계

- 추천 가중치(튀는 색·갈색 쏠림·스포티·격식·퍼스널 컬러·머리 길이 표 등)는 학습한 값이 아니라 손으로 정한 설계 값이며, 사용자 설문·A/B 로 검증 중입니다.
- 사진 체형 분석은 실측 보정 전 실험 기능입니다.
- 라이선스 파일은 아직 정하지 않았습니다.
