# code — K-Fashion / Rule Engine (문하람)

환경: Python 3.11, `.venv` (torch cu128, scikit-learn, open_clip_torch, scipy, pandas, pyarrow, streamlit, joblib). 원본 데이터는 `../Data/`.
실행은 모두 `.\.venv\Scripts\python.exe <스크립트>` (Windows). 산출물은 `data/`·`models/`·`runs/` 에 생기고 Git 에서는 제외한다.

## 재생성 순서 (처음부터)
| # | 명령 | 결과 | 시간 |
|---|---|---|---|
| 1 | `kfashion_attrs.py` | data/kfashion_labels.pkl · kfashion_attrs.* (라벨 108.9만) | 2분 |
| 2 | `kfashion_cooc.py` | data/kfashion_items.json (후보 846종) · cooc | 1분 |
| 3 | `make_rules.py` | rules/body_rules.json · weather_rules.json | 즉시 |
| 4 | `train_compat.py` | models/compat_*.joblib · runs/compat_eval.md | 6분 |
| 5 | `clothes_meta.py` → `clothes_male.py` | data/clothes_meta.csv · 남성 lift | 2분 |
| 6 | `kfashion_color.py` · `kfashion_style.py` | 색·스타일 통계 + 평가 | 2분 |
| 7 | `polyvore_shoes.py` · `zappos_thumbs.py` | 신발 통계·컷 (⚠ 서구·여성 편향) | 1분 |
| 8 | `kfashion_photos.py` → `product_attrs.py scan` → `kfashion_color_thumbs.py` | 착장 색인 · 아이템 컷 · 색별 컷 | 3분 |
| 9 | `product_attrs.py feats` `train` `assign` `wearing` | 143 제품 컷 속성 분류기 · 제품 컷 · 착용 컷 색인 | 15분 (GPU) |
| 10 | `clothes_wear.py` | 남성 단품 착용 컷 | 2분 |
| 11 | `body_thresholds.py` · `baseline_body.py` | 체형 3분위 기준 · 키·몸무게 회귀 | 1분 |

## 실행
- 추천 CLI: `rule_engine.py --sex M --group 상체형 --build 보통 --leg 보통 --feels 9 --precip 10` (`--style 모던`, `--json`)
- 테스트: `test_rule_engine.py` (2,592안 · 6.5만 검사, 약 1.5분)
- 통합 JSON v2 연결: `ffu_v2_adapter.py --prediction contracts/ffu_v2/04_prediction.example.json --feels 12 --precip 10` — K-Means 예측 JSON → 코디. 군집 매핑은 `rules/cluster_map.json` (체형 파트와 합의 후 채움). 테스트 `test_ffu_v2_adapter.py`
- 정면 체형 API(`front_profile_v1`, 팀 레포 `body_analysis/front_prototype`) 도 같은 어댑터로: `ffu_v2_adapter.py --prediction contracts/front_v1/front_profile.example_M.json --feels 12 --height 175 --weight 70`. 남성 군집은 손승민 확인(10/13). 여성은 상·하체(group)를 `upper_hip_ratio` 3분위로 정하고, 군집(굴곡/직선/중간)은 허리 규칙 K1~K5 에만 씀 — 임시 매핑(경고 `CLUSTER_MAP_PROVISIONAL`). 키·몸무게(`--height --weight`, 함수는 `user=`)로 체격을 정함
- 데모의 "정면 사진 분석" 모드: 사진을 팀 API(`http://127.0.0.1:8767/analyze`, front_prototype 실행 필요)로 보내거나 결과 JSON 업로드 + 사이드바 키·몸무게
- 데모: `python -m streamlit run app.py --server.port 8501` — 화면 "추천" / "만족도 평가 (A/B)". 상황(TPO) 선택(`tpo.py`), 닉네임 넣으면 👍👎 취향 저장(`data/prefs/`)
- 추천 API (Backend 용, 표준 라이브러리만): `api_server.py --port 8770` → `POST /recommend` (body·user·front_profile 중 하나 + weather + style/tpo + user_id), `POST /feedback`, `GET /meta` `/health` `/image?path=&color=`. 테스트 `test_api_server.py`
- 회원 DB (`members.py`, SQLite `data/members.db`): 회원·저장한 코디·후기·Q&A·👍👎 취향 + 평가 참여 기록. 비밀번호 PBKDF2 솔트 해시, 토큰은 해시만 저장, 로그인 실패 5회/10분 제한. API 는 허용 출처만 CORS (`--origin` 으로 추가)
- 평가 참여 결과 (평가 프로토콜 §5): 웹 "🧪 평가 참여" 화면 → `eval_study.py` → runs/study_eval.md (1문항·사진 vs 줄자 실측 일치율, A/B, 만족도). 참가자 기록 삭제 요청은 `members.py delete-study <번호>`
- 만족도 A/B (평가 프로토콜 D): 데모의 평가 화면이 체형 규칙 켬/끔 추천을 블라인드로 보여 주고 `data/eval/ab_responses.jsonl` 에 저장 → `eval_ab.py` → runs/ab_eval.md
- 신뢰성 지표 (재현율·민감도): `metrics_report.py` → runs/metrics_report.md (제약 위반률 · 규칙별 민감도, 약 1.5분)
- AI 형태 컷: `gen_items.py` (ComfyUI FLUX.1 Kontext dev, 860장 `data/gen_items/`) → 화면에서 `tint.py` 로 추천 색 입힘
  - 남성 실루엣 컷: `gen_items.py --sex M` → `data/gen_items/m/` (셔츠·니트·팬츠·청바지·재킷·코트 등 남녀 모양이 다른 340종. 티·후드·조거·패딩은 공용 컷). 엔진은 남성이면 `m/` 컷을 먼저 씀
    - 10/27 점검: 데님 반바지(핫팬츠처럼 짧음)·롱 조끼/가디건(원피스·가운처럼 나옴)·롱 재킷 묘사 수정 후 `--changed` 로 재생성, 배경·모양 불량 컷은 `--reseed m/outer/072.png,...` (seed +100)
- 추천 다양성 (10/27): 상황별 선호 아이템 `tpo.PREFER` (공통 + 성별 표, 화면 "우선한 아이템"), 남성 실루엣 감점 `rule_engine.SILHOUETTE` (시폰·레이스·벨보텀·니트 하의 등),
  조합 모델 점수 포화(`FFU_COMPAT_CAP`, 기본 4) — 상황 6개 × 체감 5단계 × 핏 3 × 남녀에서 상황끼리 같은 1안 22/450 → 0, 남녀 같은 1안 4/90 → 0
- 레이어드 (10/27): 체감 12도 미만 출근·데이트·약속에서 셔츠·블라우스 코디는 위에 니트를 겹쳐 줌 (응답 `layer`, 화면 상의 카드 2장, 규칙 id `Y1`, 가산 `FFU_LAYER_W` 기본 0.5)
- 여성 점검 (10/27): 체감 9도 미만 7부 바지·크롭 상의 감점, 이름 정리 ('미니 청바지' → '데님 반바지', 치마 '벨보텀' → '플레어')
- 다리 비율(leg) 실험 `calibrate_leg.py` → `runs/leg_calib.md`: 사진의 골반~발목 비율과 실측 허리높이/키 순위상관 남 -0.01 · 여 0.05 (2,181명) → 사진으로는 판단 불가, leg 는 '보통' 유지
- 코디 보드 샘플: `outfit_board.py` → runs/_peek/
- 분류기 평가: `product_attrs_eval.py` → runs/product_attrs_eval.md

## 파일
`rule_engine.py` 엔진 · `train_compat.py` 조합 모델 · `preference.py` 👍👎 · `kfashion_photos.py` 사진 조회 · `outfit_board.py` 코디 보드 · `product_attrs.py` 143 제품 컷 · `app.py` 데모.
체형 실험(⚠ 다른 파트): `body_*.py` `train_body.py` `validate_body.py` `baseline_body.py` `smpl_convert.py`.
자세한 설계: `../md파일/파트_KFashion_RuleEngine.md`, 복원 기록: `../md파일/복원_260929.md`.

## 팀 저장소(som1018/Fit-For-U)에서 받은 경우
실행에 필요한 가공 데이터 `data/*.json`(K-Fashion·AI Hub 통계, 8.7MB)과 모델 `models/*.joblib`(0.4MB)은 같이 들어 있다. 생성 옷 이미지(`data/gen_items`, 524MB)만 빠져 있어 카드에 그림 없이 글로 나온다 (받으면 `recommend_engine/data/gen_items/` 에 풀기).

```powershell
# 1) 추천 엔진 API (Python 3.11)
cd recommend_engine
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe api_server.py --port 8770      # 기상청 키는 환경변수 KMA_API_KEY (없으면 날씨 직접 입력)
# 2) 웹 화면 (Node 20+) — 다른 터미널에서 (저장소 루트의 web_react/)
cd ../web_react                                       # recommend_engine 옆 폴더
npm install
npm run dev                                           # http://localhost:5173 , /api → 127.0.0.1:8770 · 시연 계정 test / 1234
```

- 테스트: `test_rule_engine.py` `test_api_server.py` `test_web_bridge.py` 등 — 이미지·`../fit-for-u_연동` 이 없으면 해당 검사만 건너뜀
- 원본 사진·라벨(`clothes_meta.csv`, `kfashion_labels.pkl` 등)은 없어서 데이터 재생성 스크립트(`kfashion_*.py`, `clothes_*.py`)는 실행 불가
- `body_features.py`·`body_photo3d.py`·`validate_body.py`·`train_body.py` 는 초기 실험용 `body_measure.py`(현재 없음)에 의존 — 추천·웹 실행에는 필요 없음
