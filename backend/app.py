"""
Fit-For-U 데모 (Streamlit) — 키·몸무게·성별·나이 [+ 형태 1문항] + 날씨 → 코디 3안 (코디 보드 + 착용 컷 + 이유 + 무신사 검색 링크)
  .\\.venv\\Scripts\\python.exe -m streamlit run app.py --server.port 8501
체형 입력 두 가지: ① 키·몸무게 회귀 + 1문항  ② 정면 사진 → 팀 체형 API(front_profile_v1, 손승민 front_prototype) + 키·몸무게
  ②는 사진을 http://127.0.0.1:8767/analyze 로 보내거나(그 서버가 켜져 있어야 함) API 결과 JSON 을 올린다 → ffu_v2_adapter.
화면 두 가지: 추천 / 만족도 평가(A/B) — 체형 규칙을 켠 추천과 끈 추천을 순서 무작위로 보여 주고 응답을 data/eval/ab_responses.jsonl 에 쌓는다 (분석: eval_ab.py).
상황(TPO) → 스타일 묶음은 tpo.py. 닉네임을 넣으면 👍👎 취향이 data/prefs/ 에 저장돼 다음에도 이어진다.
"""
import io, json, os, random, sys, time, uuid
from urllib.parse import quote

import requests
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from rule_engine import RuleEngine
from preference import Preference, load_user, save_user
import tpo
import body_estimate
from ffu_v2_adapter import recommend_v2
import outfit_board
import tint

st.set_page_config(page_title="Fit-For-U", page_icon="👕", layout="wide")


@st.cache_resource(show_spinner="규칙 엔진 불러오는 중…")
def engine():
    return RuleEngine()


@st.cache_data(show_spinner=False)
def board_png(key, _outfit):
    """코디 보드 JPEG 바이트 — 만드는 데 0.3초쯤 걸려서 같은 코디는 캐시 (_outfit 은 해시 제외)"""
    buf = io.BytesIO(); outfit_board.board(_outfit).save(buf, "JPEG", quality=88); return buf.getvalue()


def board_key(o):
    ph = o.get("photo") or {}
    return json.dumps([o["top"]["label"], o["bottom"]["label"], (o["outer"] or {}).get("label"), o["shoes"], o["query"], ph.get("product"), ph.get("items")], ensure_ascii=False, sort_keys=True)


@st.cache_data(show_spinner="체형 분석 중…")
def _post_photo(api, sex, name, data):
    """팀 체형 API(front_prototype app.py) 호출 → front_profile_v1 dict. 재촬영(422)도 JSON 이 오면 그대로. 실패는 예외라 캐시되지 않음."""
    r = requests.post(api, data={"sex": sex}, files={"photo": (name, data)}, headers={"X-FitForU": "local-prototype"}, timeout=60)
    return r.json()


def analyze_photo(api, sex, name, data):
    try: return _post_photo(api, sex, name, data)
    except ValueError: return {"_error": "체형 분석 서버 응답을 읽을 수 없어요."}     # JSON 아님 (requests 의 JSONDecodeError 도 ValueError)
    except requests.RequestException:
        return {"_error": f"체형 분석 서버에 연결할 수 없어요 ({api}). front_prototype 을 켜거나 결과 JSON 을 올려 주세요."}


@st.cache_data(show_spinner=False, max_entries=2000)
def gen_png(rel, color, crop=None):
    """AI 형태 컷 → 추천 색으로 칠한 PNG 바이트 (384px 로 줄여서 칠함, 같은 (컷, 색)은 캐시).
    crop "v": 위아래 여백을 잘라 납작하게 (상의·신발) / "h": 좌우 여백을 잘라 길쭉하게 (왼쪽 세로 칸의 아우터)"""
    from PIL import Image, ImageOps
    im = Image.open(path(rel)).convert("RGB").resize((384, 384), Image.LANCZOS)
    box = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 12 else 0).getbbox() if crop else None
    if box and crop == "v": im = im.crop((0, max(0, box[1] - 12), 384, min(384, box[3] + 12)))
    if box and crop == "h": im = im.crop((max(0, box[0] - 16), max(0, box[1] - 12), min(384, box[2] + 16), min(384, box[3] + 12)))
    buf = io.BytesIO(); (tint.tint(im, color) if color else im).save(buf, "PNG"); return buf.getvalue()


def path(rel):
    return os.path.join(HERE, rel) if rel else None


EVAL_LOG = os.path.join(HERE, "data", "eval", "ab_responses.jsonl")
TRIAL_FEELS = (-3, 3, 7, 10, 14, 18, 21, 25, 30)          # 평가 모드에서 회차마다 바꿔 보는 체감온도 (8구간 고르게)

eng = engine()
if "pref" not in st.session_state: st.session_state.pref = Preference()
if "sid" not in st.session_state: st.session_state.sid = uuid.uuid4().hex[:12]     # 익명 응답자 id
pref = st.session_state.pref

st.markdown("<style>.block-container{padding-top:2rem;padding-bottom:1rem}</style>", unsafe_allow_html=True)   # 코디 3안이 한 화면에 들어오게

with st.sidebar:
    view = st.radio("화면", ["추천", "만족도 평가 (A/B)"], horizontal=True)
    st.header("나")
    nick = st.text_input("닉네임 (선택)", help="넣으면 👍👎 취향이 이 PC 에 저장돼 다음에도 이어집니다").strip()
    if nick and st.session_state.get("pref_user") != nick:
        st.session_state.pref = load_user(nick); st.session_state.pref_user = nick; pref = st.session_state.pref
    sex = st.radio("성별", ["여성", "남성"], horizontal=True); sx = "F" if sex == "여성" else "M"
    height = st.number_input("키 (cm)", 140, 200, 165 if sx == "F" else 175); weight = st.number_input("몸무게 (kg)", 35, 130, 55 if sx == "F" else 70)
    mode = st.radio("체형 입력", ["키·몸무게 + 1문항", "정면 사진 분석"], horizontal=True)
    front = None; age = ans = None
    if mode == "키·몸무게 + 1문항":
        age = st.selectbox("나이대", body_estimate.AGES)
        answer = st.radio("몸의 형태 (선택)", ["모르겠음", "어깨·가슴이 넓은 편", "골반·엉덩이가 넓은 편", "비슷한 편"], index=0)
        ans = {"모르겠음": None, "어깨·가슴이 넓은 편": "상체", "골반·엉덩이가 넓은 편": "하체", "비슷한 편": "비슷"}[answer]
    else:
        st.caption("정면 전신 사진 → 체형 분석 API. 키·몸무게는 위 값으로 체격(마름/보통/통통)을 정합니다.")
        photo = st.file_uploader("정면 사진", type=["jpg", "jpeg", "png"])
        api = st.text_input("체형 분석 API", "http://127.0.0.1:8767/analyze")
        res_json = st.file_uploader("또는 분석 결과 JSON (front_profile_v1)", type=["json"])
        if photo is not None:
            front = analyze_photo(api, "Female" if sx == "F" else "Male", photo.name, photo.getvalue())
        elif res_json is not None:
            try: front = json.loads(res_json.getvalue().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError): front = {"_error": "JSON 을 읽을 수 없어요."}
    if view == "추천":
        st.header("오늘 날씨")
        feels = st.slider("체감온도 (°C)", -15, 38, 14); precip = st.slider("강수확률 (%)", 0, 100, 10)
    tpos = ["(선택 안 함)"] + list(tpo.TPO)
    tp = st.selectbox("오늘 상황 (선택)", tpos); tp = None if tp == tpos[0] else tp
    styles = ["(선택 안 함)"] + list((eng.style or {}).get("styles", {}))[:23]
    style = st.selectbox("스타일 (선택)", styles, disabled=bool(tp), help="상황을 고르면 상황에 맞는 스타일 묶음을 씁니다")
    style = tpo.styles_for(tp, sx) if tp else (None if style == styles[0] else style)
    if tp: st.caption("→ 스타일 " + " · ".join(style))
    if st.button("취향 초기화"):
        st.session_state.pref = Preference(); pref = st.session_state.pref
        if nick: save_user(nick, pref)

# ---------------------------------------------------------------- 체형 입력 → body
if mode == "키·몸무게 + 1문항":
    est = body_estimate.estimate(sx, height, weight, age, answer=ans)
    body = {k: est[k] for k in ("sex", "group", "build", "leg")}
    bs = est.get("_basis") or {}
    basis = f"체형 입력: {body['group']} · {body['build']} — {bs.get('group', '')} / {bs.get('build', '')}"
else:
    if front is None:
        st.info("왼쪽에서 정면 사진이나 분석 결과 JSON 을 올려 주세요."); st.stop()
    if front.get("_error"):
        st.error(front["_error"]); st.stop()
    out = recommend_v2(front, {"feels_like": 14, "precip_prob": 0}, engine=eng, user={"height_cm": float(height), "weight_kg": float(weight)})
    if out["status"] == "retake_required":
        st.warning("사진을 다시 찍어 주세요: " + " / ".join(e["message"] for e in out["errors"] if e["code"] != "PREDICTION_NOT_OK")); st.stop()
    if out["status"] != "ok":
        st.error("체형 결과를 쓸 수 없어요: " + " / ".join(f"{e['code']} {e['message']}" for e in out["errors"])); st.stop()
    bi = out["body_input"]
    body = {k: bi[k] for k in ("sex", "group", "build", "leg", "waist") if k in bi}
    if out["sex"] != ("female" if sx == "F" else "male"): st.sidebar.warning("분석 결과의 성별이 선택한 성별과 달라 분석 결과를 따릅니다.")
    basis = (f"체형 입력: {bi.get('cluster_label', '군집 ' + str(out['cluster_id']))} → {bi['group']} · 허리 {bi['waist']} · {bi['build']}"
             + (f" (BMI {bi['bmi']})" if bi.get("bmi") else "") + (" · ⚠ 임시 매핑" if bi.get("provisional") else ""))
    for w in out["warnings"]: st.sidebar.caption(f"⚠ {w['message']}")
st.sidebar.caption(basis)

PART = {"outer": "아우터", "top": "상의", "bottom": "하의", "shoes": "신발"}
colored = st.sidebar.toggle("추천 색으로 칠하기", True, help="끄면 원본 라이트 그레이 형태 컷")
show_ds = st.sidebar.toggle("데이터셋 사진도 보기", False, help="K-Fashion·AI Hub 코디 보드와 착용 컷 (기본은 AI 생성 컷만)") if view == "추천" else False


def piece(o, col, tag, key, crop=None):
    gen, colors = o.get("gen") or {}, o.get("colors") or {}
    name = o["shoes"] if key == "shoes" else o[key]["label"]
    if key == "shoes" and colors.get("신발"): name = f"{colors['신발']} {name}"
    if gen.get(key) and os.path.exists(path(gen[key])):
        col.image(gen_png(gen[key], colors.get(PART[key]) if colored else None, crop), width="stretch")
    col.caption(f"**{tag}** {name}")


def outfit_layout(o):
    """왼쪽 세로 칸: 아우터 (없으면 상의) / 오른쪽: 상의 → 하의 → 신발 — 걸쳐 입는 모양대로"""
    left, right = st.columns(2, vertical_alignment="center")
    stack = [("상의", "top", "v"), ("하의", "bottom", None), ("신발", "shoes", "v")]
    if o.get("outer"): piece(o, left, "아우터", "outer", "h")
    else: piece(o, left, *stack.pop(0)[:2], "h")
    for tag, key, crop in stack: piece(o, right, tag, key, crop)


# ---------------------------------------------------------------- 화면 ① 추천
if view == "추천":
    st.markdown("#### Fit-For-U · 오늘의 코디")
    res = eng.recommend(body, {"feels_like": feels, "precip_prob": precip}, style=style, pref=pref)
    st.markdown(f"**체감 {feels}° · {res['band']}**" + (" · 비 예보" if res["rain"] else "") + (f" · {tp}" if tp else ""))
    st.caption("이미지는 AI 생성 형태 컷 (FLUX.1 Kontext dev, 비상업)에 추천 색을 입힌 것 — 실제 상품 사진이 아니며 색은 대표색 근사.")
    for n, (card, o) in enumerate(zip(st.columns(len(res["outfits"])), res["outfits"]), 1):
        ph = o.get("photo") or {}
        with card, st.container(border=True):
            h, b1, b2 = st.columns([3, 1, 1], vertical_alignment="center")   # 👍👎 는 제목 줄에 — 카드 높이 절약
            h.markdown(f"**코디 {n}**")
            for btn, like, k in ((b1, True, "up"), (b2, False, "dn")):
                if btn.button("👍" if like else "👎", key=f"{k}{n}"):
                    pref.feedback(o, like)
                    if nick: save_user(nick, pref)
                    st.rerun()
            outfit_layout(o)
            sents = [x for x in o["reason"].rstrip(".").split(". ") if x]
            st.caption(" · ".join(sents[1:3]) or sents[0])
            with st.expander("자세히"):
                st.write(o["reason"])
                st.markdown("무신사: " + " · ".join(f"[{q}](https://www.musinsa.com/search/goods?keyword={quote(q)})" for q in o["query"]))
                st.caption("규칙 " + ", ".join(o["rules"]))
            if show_ds:
                st.image(board_png(board_key(o), o), width="stretch")
                w = ph.get("wearing") or ph.get("outfit")
                if w: st.image(path(w), caption="착용 컷 (AI Hub)" if ph.get("wearing") else "참고 컷 (K-Fashion)", width="stretch")
    if pref.w:
        st.sidebar.subheader("내 취향 메모" + (f" · {nick}" if nick else ""))
        for part, val, w in pref.summary(): st.sidebar.write(f"{'👍' if w > 0 else '👎'} {part} {val} ({w:+.1f})")
    if show_ds: st.caption("⚠ 사진: K-Fashion·AI Hub(국내, 여성 위주)·UT Zappos50K(미국 카탈로그, 신발). 신발 통계는 미국 Polyvore(여성 편향)이며 여성에게만 반영. 연구·교육용.")
    st.stop()

# ---------------------------------------------------------------- 화면 ② 만족도 평가 (A/B, 블라인드)
st.markdown("#### 만족도 평가 · 어느 쪽 코디가 나에게 더 어울리나요?")
st.caption("두 추천 중 하나만 체형을 고려했습니다 (어느 쪽인지는 숨김). 날씨는 회차마다 바뀝니다. "
           "응답은 이 PC 파일에 익명 id 로 저장됩니다 — 성별·키·몸무게·나이대·형태 답 포함, 이름·사진은 저장하지 않음.")
trial = st.session_state.setdefault("trial", 0)
feels = TRIAL_FEELS[(trial + int(st.session_state.sid, 16)) % len(TRIAL_FEELS)]
weather = {"feels_like": feels, "precip_prob": 10}
on = eng.recommend(body, weather, style=style)
off = eng.recommend(body, weather, style=style, use_body=False)
sig = lambda r: [(o["top"]["id"], o["bottom"]["id"], (o["outer"] or {}).get("id"), o["colors"].get("상의"), o["colors"].get("하의")) for o in r["outfits"]]
a_is_on = random.Random(f"{st.session_state.sid}-{trial}").random() < 0.5
A, B = (on, off) if a_is_on else (off, on)


def log(rec):
    os.makedirs(os.path.dirname(EVAL_LOG), exist_ok=True)
    with open(EVAL_LOG, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")


base = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sid": st.session_state.sid, "trial": trial, "body": body,
        "input": {"sex": sx, "height": height, "weight": weight, "age": age, "answer": ans, "mode": mode},
        "weather": weather, "band": on["band"], "style": style, "tpo": tp}
st.markdown(f"**{trial + 1}회차 · 체감 {feels}° ({on['band']})**")
if sig(on) == sig(off):
    st.info("이번 조건에서는 두 추천이 같았어요 (체형 규칙이 결과를 바꾸지 않음). 기록하고 다음 회차로 넘어갑니다.")
    if st.button("다음 회차 →"):
        log({**base, "identical": True}); st.session_state.trial += 1; st.rerun()
    st.stop()

for col, tag, r in zip(st.columns(2), ("A", "B"), (A, B)):
    with col, st.container(border=True):
        st.markdown(f"**추천 {tag}**")
        for o in r["outfits"]:                                   # 코디마다 한 줄: 아우터·상의·하의·신발
            keys = [(t, k) for t, k in (("아우터", "outer"), ("상의", "top"), ("하의", "bottom"), ("신발", "shoes")) if k == "shoes" or o.get(k)]
            for col, (t, k) in zip(st.columns(4), keys): piece(o, col, t, k)
with st.form(f"ab{trial}"):
    choice = st.radio("내 체형에 더 잘 어울리는 쪽은?", ["A", "비슷함", "B"], horizontal=True, index=None)
    c1, c2 = st.columns(2)
    sa = c1.slider("A 만족도", 1, 5, 3); sb = c2.slider("B 만족도", 1, 5, 3)
    if st.form_submit_button("제출하고 다음 회차"):
        if choice is None: st.warning("A / 비슷함 / B 중 하나를 골라 주세요.")
        else:
            labels = lambda r: [[(o[k] or {}).get("label") for k in ("outer", "top", "bottom")] for o in r["outfits"]]
            log({**base, "identical": False, "a_is_rules": a_is_on, "choice": choice,
                 "prefers_rules": {"A": a_is_on, "B": not a_is_on}.get(choice),          # 비슷함 → None
                 "score_rules": sa if a_is_on else sb, "score_plain": sb if a_is_on else sa,
                 "rules_fired": sorted({x for o in on["outfits"] for x in o["rules"]}),
                 "outfits_rules": labels(on), "outfits_plain": labels(off)})
            st.session_state.trial += 1; st.rerun()
st.caption(f"응답 {trial}회 완료 · 응답자 id {st.session_state.sid}")
