"""
추천 HTTP API (입출력 계약 §4 "POST /recommend") — 표준 라이브러리만 사용 (FastAPI 설치 없이). Backend 가 Python 모델·데이터를 안 끌어안고 호출만 하게.

  .\\.venv\\Scripts\\python.exe api_server.py --port 8770          (기본 127.0.0.1 — 외부 공개는 별도 판단)

엔드포인트
  GET  /health                      → {"ok": true}
  GET  /meta                        → 스타일·TPO·날씨 구간 목록 (입력 UI 용)
  POST /recommend                   → 코디 3안 (rule_engine 출력 + body_input)
       체형은 셋 중 하나:  "body": {sex, group, build, leg}
                          "user": {sex: "M"|"F", height_cm, weight_kg, age?: "20대"…, answer?: "상체"|"하체"|"비슷"}
                          "front_profile": front_profile_v1 JSON (+ "user" 의 키·몸무게로 체격)
       "weather": {feels_like, precip_prob}   필수
       "style": "모던" | ["모던", …] | null,  "tpo": "출근·면접" | null  (tpo 가 있으면 style 보다 우선)
       "user_id": 있으면 저장된 👍👎 취향을 불러와 반영
  POST /feedback                    → {"user_id", "outfit": 추천 1안 JSON, "like": true|false} → 취향 저장
  GET  /image?path=data/gen_items/top/000.png&color=네이비   → 추천 색으로 칠한 AI 형태 컷 PNG

회원 (members.py, data/members.db) — 로그인 뒤 "Authorization: Bearer <token>" 이 필요
  POST /auth/signup {id, pw, profile} · /auth/login {id, pw} → {token, user} · /auth/logout
  GET /me · POST /me {profile}      GET /saved · POST /saved {snap} · POST /saved/delete {id}
  GET /prefs · POST /prefs {pref|null}      GET /reviews · POST /reviews {stars, text}      GET /qna · POST /qna {title, content} · POST /qna/delete {id}

평가 참여 (평가 프로토콜 §5, 익명 참가자 번호 — 회원과 연결하지 않음, 사진은 분석 숫자만 남김)
  POST /study/start {consent: true, profile: {sex, age, height, weight, answer}, tape?} → {pid}
  POST /study/tape {pid, tape: {chest, waist, hip, shoulder}}      POST /study/photo {pid, front, side?}
  POST /study/pair {pid, round, weather, situation} → 체형 규칙 켬/끔 코디를 A/B 로 (어느 쪽인지는 서버만 앎)
  POST /study/answer {pid, pair_id, choice: A|B|same, score_a, score_b}      POST /study/survey {pid, wear, shoes, understand, negative, comment?}
"""
import argparse, base64, binascii, functools, io, json, os, random, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import body_estimate, kma_forecast, tint, tpo
import ffu_web_bridge, body_cluster_bridge
from ffu_v2_adapter import recommend_v2
from preference import Preference, load_user, save_user
from rule_engine import RuleEngine
import members

ENGINE = None
MEMBERS = None
ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}   # 브라우저가 직접 부를 수 있는 출처 (터널은 Vite 프록시로 같은 출처라 필요 없음)
REGIONS = {"서울": (60, 127), "천안": (63, 110), "세종": (66, 103), "수원": (60, 121), "인천": (55, 124), "대전": (67, 100),
           "대구": (89, 90), "부산": (98, 76), "광주": (58, 74), "울산": (102, 84), "제주": (52, 38)}
GEN_ROOT = os.path.realpath(os.path.join(HERE, "data", "gen_items"))
MAX_BODY = 1 << 20
MAX_PHOTO_BODY = 34 << 20                                  # /body/photo: 사진 2장(각 12MB 이하) base64


class BadRequest(ValueError):
    pass


class Unauthorized(Exception):
    pass


def _num(d, k, lo, hi):
    v = d.get(k)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
        raise BadRequest(f"{k} 는 {lo}~{hi} 사이 숫자여야 합니다")
    return float(v)


def _weather(req):
    w = req.get("weather")
    if not isinstance(w, dict): raise BadRequest("weather 가 필요합니다 ({feels_like, precip_prob})")
    return {"feels_like": _num(w, "feels_like", -40, 50), "precip_prob": _num(w, "precip_prob", 0, 100) if "precip_prob" in w else 0.0}


def _style(req, sex):
    if req.get("tpo"):
        st = tpo.styles_for(req["tpo"], sex)
        if not st: raise BadRequest(f"알 수 없는 tpo: {req['tpo']} (가능: {', '.join(tpo.TPO)})")
        return st
    st = req.get("style")
    known = set((ENGINE.style or {}).get("styles", {}))
    for x in ([st] if isinstance(st, str) else st or []):
        if x not in known: raise BadRequest(f"알 수 없는 style: {x}")
    return st or None


def recommend(req):
    weather = _weather(req)
    pref = load_user(req["user_id"]) if req.get("user_id") else None
    user = req.get("user") if isinstance(req.get("user"), dict) else None
    if isinstance(req.get("front_profile"), dict):
        fp = req["front_profile"]; sex = {"Male": "M", "Female": "F"}.get(fp.get("sex"), "F")
        u = {"height_cm": _num(user, "height_cm", 100, 230), "weight_kg": _num(user, "weight_kg", 25, 250)} if user else None
        out = recommend_v2(fp, weather, style=_style(req, sex), engine=ENGINE, pref=pref, user=u)
        if out.get("status") != "ok": return 422, out
        return 200, {**out["recommendation"], "body_input": out["body_input"], "warnings": out.get("warnings", []), "status": "ok"}
    if user:
        sex = user.get("sex")
        if sex not in ("M", "F"): raise BadRequest("user.sex 는 M 또는 F")
        age = user.get("age", "20대")
        if age not in body_estimate.AGES: raise BadRequest(f"user.age 는 {body_estimate.AGES} 중 하나")
        ans = user.get("answer")
        if ans not in (None, "상체", "하체", "비슷"): raise BadRequest("user.answer 는 상체/하체/비슷/null")
        est = body_estimate.estimate(sex, _num(user, "height_cm", 100, 230), _num(user, "weight_kg", 25, 250), age, answer=ans)
        body = {k: est[k] for k in ("sex", "group", "build", "leg")}
    elif isinstance(req.get("body"), dict):
        b = req["body"]
        allowed = {"sex": ("M", "F"), "group": ("상체형", "균형", "하체형"), "build": ("마름", "보통", "통통"), "leg": ("롱", "보통", "숏")}
        body = {"sex": b.get("sex"), "group": b.get("group", "균형"), "build": b.get("build", "보통"), "leg": b.get("leg", "보통")}
        if "waist" in b: allowed["waist"] = ("굴곡", "보통", "직선"); body["waist"] = b["waist"]
        for k, ok in allowed.items():
            if body[k] not in ok: raise BadRequest(f"body.{k} 는 {ok} 중 하나")
    else:
        raise BadRequest("body · user · front_profile 중 하나가 필요합니다")
    res = ENGINE.recommend(body, weather, style=_style(req, body["sex"]), pref=pref, tpo=req.get("tpo"))
    return 200, {**res, "body_input": body, "status": "ok"}


def _load_key():
    """KMA_API_KEY — 환경변수, 없으면 code/.env → ../fit-for-u_연동/.env (키는 출력·로그에 남기지 않음)"""
    if os.environ.get("KMA_API_KEY"): return os.environ["KMA_API_KEY"]
    for p in (os.path.join(HERE, ".env"), os.path.join(HERE, "..", "fit-for-u_연동", ".env")):
        try:
            for line in open(p, encoding="utf-8-sig"):
                k, _, v = line.strip().partition("=")
                if k.strip() == "KMA_API_KEY" and v.strip(): return v.strip().strip("\"'")
        except OSError:
            continue
    return None


def weather(q):
    """GET /weather?region=서울  |  ?lat=37.5&lon=127.0  |  ?nx=60&ny=127  → 단기예보 요약 + 엔진 입력(feels_like, precip_prob)"""
    g = lambda k: (q.get(k) or [None])[0]
    if g("lat") and g("lon"):
        try: lat, lon = float(g("lat")), float(g("lon"))
        except ValueError: raise BadRequest("lat, lon 은 숫자여야 합니다")
        if not kma_forecast.in_korea(lat, lon): raise BadRequest("국내 위치만 지원합니다")
        nx, ny = kma_forecast.latlon_to_grid(lat, lon)
        near = min(REGIONS, key=lambda r: (REGIONS[r][0] - nx) ** 2 + (REGIONS[r][1] - ny) ** 2)
    elif g("nx") and g("ny"):
        try: nx, ny = int(g("nx")), int(g("ny"))
        except ValueError: raise BadRequest("nx, ny 는 정수여야 합니다")
        near = None
    else:
        near = g("region") or "서울"
        if near not in REGIONS: raise BadRequest(f"알 수 없는 지역: {near}")
        nx, ny = REGIONS[near]
    key = _load_key()
    if not key: raise BadRequest("서버에 KMA_API_KEY 가 설정되지 않았습니다")
    try:
        fc = kma_forecast.fetch_forecast(key, g("provider") or "data_go_kr", nx, ny)
    except kma_forecast.ForecastError as e:
        raise BadRequest(str(e))
    w = ffu_web_bridge.engine_weather({"temperature": fc["temp"] if fc["temp"] is not None else 15, "humidity": fc["humidity"] or 50,
                                       "wind_speed": fc["wind"] or 0, "precip_prob": fc["precip_prob"]})
    return {"grid": [nx, ny], "region": near, "forecast": fc, "weather": w}


def web_recommend(req):
    """POST /web/recommend — 팀 웹페이지 입력 형식. {profile:{gender,height,weight,style,fit}, body_type, weather:{feels_like|temperature…, precip_prob}, situation, user_id?}
    → 카드 3안 (items[].image 는 /image URL — 추천 색이 칠해진 AI 형태 컷)"""
    profile = req.get("profile") if isinstance(req.get("profile"), dict) else {}
    w = req.get("weather") if isinstance(req.get("weather"), dict) else None
    if not w: raise BadRequest("weather 가 필요합니다")
    wd = dict(w)
    if "feels_like" in wd: wd["feels_like"] = _num(wd, "feels_like", -40, 50)
    body = None
    if isinstance(req.get("body"), dict):             # /body/classify 결과를 그대로 넘기면 body_type 대신 사용
        b = req["body"]
        if b.get("sex") not in ("M", "F") or b.get("group") not in ("상체형", "균형", "하체형") or b.get("build") not in ("마름", "보통", "통통"):
            raise BadRequest("body 는 {sex: M|F, group: 상체형|균형|하체형, build: 마름|보통|통통} 형식입니다")
        body = {"sex": b["sex"], "group": b["group"], "build": b["build"], "leg": b.get("leg", "보통")}
    out = ffu_web_bridge.recommend_for_web(profile, req.get("body_type"), wd, req.get("situation"), eng=ENGINE, body=body,
                                           pref=req.get("pref") if isinstance(req.get("pref"), dict) else None)
    return 200, {**_web_out(out), "status": "ok"}


def web_similar(req):
    """POST /web/similar — 추천 카드의 옷과 비슷한 옷. {profile, body?|body_type, weather, situation, key: top|bottom|outer, item_id: 추천 응답 fb[key].id, color?, pref?}
    → {base, part, items: [{name, desc, image(/image URL), color, shared[], link}]}"""
    profile = req.get("profile") if isinstance(req.get("profile"), dict) else {}
    w = req.get("weather") if isinstance(req.get("weather"), dict) else None
    if not w: raise BadRequest("weather 가 필요합니다")
    wd = dict(w)
    if "feels_like" in wd: wd["feels_like"] = _num(wd, "feels_like", -40, 50)
    body = None
    if isinstance(req.get("body"), dict):
        b = req["body"]
        if b.get("sex") not in ("M", "F") or b.get("group") not in ("상체형", "균형", "하체형") or b.get("build") not in ("마름", "보통", "통통"):
            raise BadRequest("body 는 {sex: M|F, group: 상체형|균형|하체형, build: 마름|보통|통통} 형식입니다")
        body = {"sex": b["sex"], "group": b["group"], "build": b["build"], "leg": b.get("leg", "보통")}
    try:
        out = ffu_web_bridge.similar_for_web(profile, req.get("body_type"), wd, req.get("situation"), req.get("key"), req.get("item_id"),
                                             color=req.get("color") if isinstance(req.get("color"), str) else None, eng=ENGINE, body=body,
                                             pref=req.get("pref") if isinstance(req.get("pref"), dict) else None)
    except ValueError as e:
        raise BadRequest(str(e))
    _web_cards(out["items"])
    return 200, {**out, "status": "ok"}


def _web_cards(items):
    """카드의 image(코드 폴더 기준 경로) → 추천 색을 입힌 /image URL"""
    for c in items:
        img = c.pop("image", None)
        c["image"] = None if not img else "/image?path=" + os.path.relpath(img, HERE).replace(os.sep, "/") + (("&color=" + quote(c["color"])) if c.get("color") else "")
    return items


def _web_out(out):
    for o in out["outfits"]:
        _web_cards(o["items"])
        o["links"] = [{"query": q, "url": u} for q, u in o["links"]]
    return out


def body_classify(req):
    """POST /body/classify — 승민님 체형 모델(군집) → 엔진 체형. {sex, preset?(기본 auto), ratios:{U,W,H[,D,J]} | measures:{chest_width|bust_width, waist_width, hip_width, stature[, waist_depth, hip_depth]}}
    ⚠ 군집→체형 연결은 임시 (body_cluster_bridge.CLUSTER_BODY)"""
    try:
        return 200, body_cluster_bridge.classify_body(req.get("sex"), ratios=req.get("ratios"), measures=req.get("measures"),
                                                      preset=req.get("preset", "auto"))
    except ValueError as e:
        raise BadRequest(str(e))


def body_photo(req):
    """POST /body/photo — {sex, preset?(기본 auto: 정면→3군집, 측면 포함→5군집), front: base64, side?: base64}. 사진은 메모리에서만 처리, 저장·로그 없음.
    ⚠ 카메라 비율은 보정 전 proxy (승민님 모델 experimental 경로) · 군집→체형 연결은 임시"""
    def img(k):
        v = req.get(k)
        if v in (None, ""): return None
        if not isinstance(v, str): raise BadRequest(f"{k} 는 base64 문자열")
        try: return base64.b64decode(v.split(",", 1)[1] if v.startswith("data:") else v, validate=True)
        except (binascii.Error, ValueError): raise BadRequest(f"{k} 의 base64 가 올바르지 않습니다")
    front, side = img("front"), img("side")
    if not front: raise BadRequest("front(정면 사진)가 필요합니다")
    try:
        return 200, body_cluster_bridge.classify_photos(req.get("sex"), front, side, preset=req.get("preset", "auto"))
    except ValueError as e:
        raise BadRequest(str(e))


def web_feedback(req):
    """POST /web/feedback — {pref?: {weights, history}, outfit: /web/recommend 의 outfits[i].fb, like: true|false} → 새 pref (+summary).
    서버는 저장하지 않는다 (React 시연은 회원 데이터가 브라우저에 있음)"""
    o = req.get("outfit")
    if not isinstance(o, dict) or not isinstance(req.get("like"), bool) or not o or set(o) - {"outer", "top", "bottom"} \
            or any(not isinstance(v, dict) or not isinstance(v.get("label"), str) for v in o.values()):
        raise BadRequest("outfit(추천 결과의 fb), like(true/false) 가 필요합니다")
    o = {k: {a: x for a, x in v.items() if isinstance(x, (str, int)) and not isinstance(x, bool)} for k, v in o.items()}
    return 200, {**ffu_web_bridge.apply_feedback(req.get("pref"), o, req["like"]), "status": "ok"}


def feedback(req):
    if not req.get("user_id") or not isinstance(req.get("outfit"), dict) or not isinstance(req.get("like"), bool):
        raise BadRequest("user_id, outfit, like(true/false) 가 필요합니다")
    pref = load_user(req["user_id"]); pref.feedback(req["outfit"], req["like"])
    if not save_user(req["user_id"], pref): raise BadRequest("user_id 형식이 올바르지 않습니다")
    return 200, {"ok": True, "summary": pref.summary()}


# ---------------------------------------------------------------- 회원 (members.py)
def _id(req, k="id"):
    v = req.get(k)
    if not isinstance(v, int) or isinstance(v, bool): raise BadRequest(f"{k} 는 정수")
    return v


def auth_signup(req, _uid):
    MEMBERS.signup(req.get("id"), req.get("pw"), req.get("profile"))
    return 200, {"ok": True}


def auth_login(req, _uid):
    tok = MEMBERS.login(req.get("id"), req.get("pw"))
    if not tok: return 401, {"error": "아이디 또는 비밀번호를 확인해주세요."}
    return 200, {"token": tok, "user": MEMBERS.get_user(req["id"])}


def me_update(req, uid):
    return 200, {"user": MEMBERS.update_user(uid, req.get("profile"))}


def saved_add(req, uid):
    MEMBERS.add_saved(uid, req.get("snap")); return 200, {"saved": MEMBERS.list_saved(uid)}


def saved_delete(req, uid):
    MEMBERS.delete_saved(uid, _id(req)); return 200, {"saved": MEMBERS.list_saved(uid)}


def prefs_set(req, uid):
    p = req.get("pref")
    if p is not None and not isinstance(p, dict): raise BadRequest("pref 는 {weights, history} 또는 null")
    MEMBERS.set_pref(uid, ffu_web_bridge.clean_pref(p) if p else None); return 200, {"pref": MEMBERS.get_pref(uid)}


def review_add(req, uid):
    MEMBERS.add_review(uid, req.get("stars"), req.get("text")); return 200, {"reviews": MEMBERS.list_reviews()}


def qna_add(req, uid):
    MEMBERS.add_qna(uid, req.get("title"), req.get("content")); return 200, {"qna": MEMBERS.list_qna()}


def qna_delete(req, uid):
    MEMBERS.delete_qna(uid, _id(req)); return 200, {"qna": MEMBERS.list_qna()}


# ---------------------------------------------------------------- 평가 참여 (평가 프로토콜 §5)
STUDY_ANSWER = {"상체": "상체형", "균형": "균형", "하체": "하체형", "모름": None}
STUDY_SITUATIONS = ("학교", "데이트", "출근", "친구와 약속", "운동", "여행")
TAPE = {"chest": (50, 200), "waist": (40, 200), "hip": (50, 200), "shoulder": (25, 70)}   # cm


def _tape(t):
    if t is None: return None
    if not isinstance(t, dict): raise BadRequest("tape 는 {chest, waist, hip, shoulder} (cm)")
    return {k: _num(t, k, lo, hi) for k, (lo, hi) in TAPE.items() if t.get(k) not in (None, "")} or None


def _score(req, k):
    v = req.get(k)
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5: raise BadRequest(f"{k} 는 1~5 정수")
    return v


def _study_body(s):
    """참가자 체형 — 상·하체는 본인 응답(앱과 같은 1문항, 모르면 사진 결과 → 균형), 체격은 BMI"""
    p = s["profile"]
    bmi = p["weight"] / (p["height"] / 100) ** 2
    group = STUDY_ANSWER.get(p["answer"]) or (s.get("photo") or {}).get("group") or "균형"
    return {"sex": p["sex"], "group": group, "build": "마름" if bmi < 18.5 else "보통" if bmi < 23 else "통통", "leg": "보통"}


def _study_profile(s):
    p = s["profile"]
    return {"gender": "남성" if p["sex"] == "M" else "여성", "height": p["height"], "weight": p["weight"], "style": "캐주얼", "fit": None}


def _study_args(req):
    s = MEMBERS.study_get(req.get("pid"))
    sit = req.get("situation")
    if sit not in STUDY_SITUATIONS: raise BadRequest(f"situation 은 {STUDY_SITUATIONS} 중 하나")
    w = _weather(req)
    return s, sit, w


def study_start(req, _uid):
    if req.get("consent") is not True: raise BadRequest("참여 동의가 필요합니다")
    p = req.get("profile") if isinstance(req.get("profile"), dict) else {}
    prof = {"sex": p.get("sex"), "age": p.get("age"), "height": _num(p, "height", 120, 220), "weight": _num(p, "weight", 30, 200), "answer": p.get("answer")}
    if prof["sex"] not in ("M", "F"): raise BadRequest("sex 는 M 또는 F")
    if prof["age"] not in body_estimate.AGES: raise BadRequest(f"age 는 {body_estimate.AGES} 중 하나")
    if prof["answer"] not in STUDY_ANSWER: raise BadRequest(f"answer 는 {tuple(STUDY_ANSWER)} 중 하나")
    return 200, {"pid": MEMBERS.study_start(prof, _tape(req.get("tape"))), "status": "ok"}


def study_tape(req, _uid):
    s = MEMBERS.study_get(req.get("pid"))
    MEMBERS.study_set(s["pid"], "tape", _tape(req.get("tape"))); return 200, {"ok": True}


def study_photo(req, _uid):
    s = MEMBERS.study_get(req.get("pid"))
    code, res = body_photo({**req, "sex": s["profile"]["sex"]})
    prev = s.get("photo") or {}
    MEMBERS.study_set(s["pid"], "photo", {"attempts": prev.get("attempts", 0) + 1, "status": res.get("status"), "preset": res.get("preset"),
                                          "cluster": res.get("cluster"), "group": (res.get("body") or {}).get("group"), "ratios": res.get("ratios"),
                                          "quality": res.get("quality"), "warnings": res.get("warnings")})
    return code, res


def study_pair(req, _uid):
    """체형 규칙 켬/끔 코디 1벌씩 → 순서 무작위 A/B. 어느 쪽이 규칙인지는 응답에 넣지 않는다 (블라인드)"""
    s, sit, w = _study_args(req)
    rnd = req.get("round")
    if not isinstance(rnd, int) or isinstance(rnd, bool) or not 1 <= rnd <= 20: raise BadRequest("round 는 1~20")
    body, prof = _study_body(s), _study_profile(s)
    on = ffu_web_bridge.recommend_for_web(prof, None, w, sit, eng=ENGINE, body=body)
    off = ffu_web_bridge.recommend_for_web(prof, None, w, sit, eng=ENGINE, body=body, use_body=False)
    a, b = on["outfits"][0], off["outfits"][0]
    sig = lambda o: [(c["name"], c.get("color")) for c in o["items"]]
    identical = sig(a) == sig(b)
    a_is_rules = random.random() < 0.5
    meta = {"body": body, "weather": w, "situation": sit, "band": on["band"], "rules_fired": a["rules"],
            "outfit_rules": [c["name"] for c in a["items"]], "outfit_plain": [c["name"] for c in b["items"]]}
    pair_id = MEMBERS.study_pair(s["pid"], rnd, a_is_rules, identical, meta)
    A, B = (a, b) if a_is_rules else (b, a)
    return 200, {"pair_id": pair_id, "round": rnd, "identical": identical, "band": on["band"], "A": _web_cards(A["items"]), "B": _web_cards(B["items"])}


def study_answer(req, _uid):
    if req.get("choice") not in ("A", "B", "same"): raise BadRequest("choice 는 A, B, same 중 하나")
    MEMBERS.study_answer(req.get("pid"), req.get("pair_id"), req["choice"], _score(req, "score_a"), _score(req, "score_b"))
    return 200, {"ok": True}


def study_recommend(req, _uid):
    """설문용 — 참가자 체형으로 평소와 같은 추천 3안"""
    s, sit, w = _study_args(req)
    out = ffu_web_bridge.recommend_for_web(_study_profile(s), None, w, sit, eng=ENGINE, body=_study_body(s))
    return 200, {**_web_out(out), "status": "ok"}


def study_survey(req, _uid):
    if not isinstance(req.get("negative"), bool): raise BadRequest("negative 는 true/false")
    c = req.get("comment", "")
    if not isinstance(c, str) or len(c) > 300: raise BadRequest("comment 는 300자 이하")
    MEMBERS.study_survey(req.get("pid"), {"wear": _score(req, "wear"), "shoes": _score(req, "shoes"), "understand": _score(req, "understand"),
                                          "negative": req["negative"], "comment": c.strip()})
    return 200, {"ok": True}


def image(q):
    rel = (q.get("path") or [""])[0]; color = (q.get("color") or [None])[0]
    full = os.path.realpath(os.path.join(HERE, rel))
    if not full.startswith(GEN_ROOT + os.sep) or not full.endswith(".png") or not os.path.exists(full):
        raise BadRequest("path 는 data/gen_items/ 아래 PNG 여야 합니다")
    return _tinted_png(full, color)


@functools.lru_cache(maxsize=1024)                         # 색 입히기가 한 장에 수백 ms — 같은 (컷, 색) 은 다시 계산하지 않음
def _tinted_png(full, color):
    from PIL import Image
    im = Image.open(full).convert("RGB")
    buf = io.BytesIO(); (tint.tint(im, color) if color else im).save(buf, "PNG"); return buf.getvalue()


PUBLIC_POST = {"/recommend": recommend, "/feedback": feedback, "/web/recommend": web_recommend, "/web/similar": web_similar, "/web/feedback": web_feedback,
               "/body/classify": body_classify, "/body/photo": body_photo}
# (req, uid) 를 받는 경로. None 이면 로그인 없이도 됨
MEMBER_POST = {"/auth/signup": (auth_signup, False), "/auth/login": (auth_login, False),
               "/auth/logout": (lambda req, uid: (200, {"ok": True}), True), "/me": (me_update, True),
               "/saved": (saved_add, True), "/saved/delete": (saved_delete, True), "/prefs": (prefs_set, True),
               "/reviews": (review_add, True), "/qna": (qna_add, True), "/qna/delete": (qna_delete, True),
               "/study/start": (study_start, True), "/study/tape": (study_tape, True), "/study/photo": (study_photo, True),
               "/study/pair": (study_pair, True), "/study/answer": (study_answer, True), "/study/recommend": (study_recommend, True),
               "/study/survey": (study_survey, True)}
MEMBER_GET = {"/me": lambda uid: {"user": MEMBERS.get_user(uid)}, "/saved": lambda uid: {"saved": MEMBERS.list_saved(uid)},
              "/prefs": lambda uid: {"pref": MEMBERS.get_pref(uid)}, "/reviews": lambda uid: {"reviews": MEMBERS.list_reviews()},
              "/qna": lambda uid: {"qna": MEMBERS.list_qna()}}
PHOTO_PATHS = {"/body/photo", "/study/photo"}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        o = self.headers.get("Origin")
        if o in ORIGINS: self.send_header("Access-Control-Allow-Origin", o); self.send_header("Vary", "Origin")

    def _send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8"):
        data = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        if ctype == "image/png": self.send_header("Cache-Control", "public, max-age=86400")   # 컷은 바뀌지 않으므로 브라우저도 캐시
        else: self.send_header("Cache-Control", "no-store")                                   # 회원 정보 응답은 캐시하지 않음
        self._cors(); self.end_headers(); self.wfile.write(data)

    def _token(self):
        h = self.headers.get("Authorization") or ""
        return h[7:].strip() if h.startswith("Bearer ") else None

    def _uid(self):
        uid = MEMBERS.user_of(self._token()) if MEMBERS else None
        if not uid: raise Unauthorized()
        return uid

    def do_OPTIONS(self):
        self.send_response(204); self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization"); self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/health": return self._send(200, {"ok": True})
            if u.path == "/meta":
                return self._send(200, {"styles": list((ENGINE.style or {}).get("styles", {})), "tpo": list(tpo.TPO),
                                        "bands": [{k: b[k] for k in ("name", "min", "max", "note")} for b in ENGINE.weather["bands"]]})
            if u.path == "/weather": return self._send(200, weather(parse_qs(u.query)))
            if u.path == "/regions": return self._send(200, {"regions": REGIONS})
            if u.path == "/image": return self._send(200, raw=image(parse_qs(u.query)), ctype="image/png")
            if u.path in MEMBER_GET: return self._send(200, MEMBER_GET[u.path](self._uid()))
            self._send(404, {"error": "not found"})
        except BadRequest as e:
            self._send(400, {"error": str(e)})
        except Unauthorized:
            self._send(401, {"error": "로그인이 필요합니다"})
        except Exception as e:            # do_POST 와 같이 응답은 꼭 보냄 (경로·스택 비노출)
            self._send(500, {"error": f"내부 오류: {type(e).__name__}"})

    def do_POST(self):
        path = urlparse(self.path).path
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: n = -1
        if n < 0: return self._send(400, {"error": "Content-Length 가 올바르지 않습니다"})
        if n > (MAX_PHOTO_BODY if path in PHOTO_PATHS else MAX_BODY): return self._send(413, {"error": "요청이 너무 큽니다"})
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(req, dict): raise BadRequest("JSON 객체를 보내 주세요")
            if path in PUBLIC_POST: return self._send(*PUBLIC_POST[path](req))
            if path not in MEMBER_POST: return self._send(404, {"error": "not found"})
            fn, need = MEMBER_POST[path]
            if MEMBERS is None: raise Unauthorized()
            uid = self._uid() if need else None
            if path == "/auth/logout": MEMBERS.logout(self._token())
            self._send(*fn(req, uid))
        except (BadRequest, members.Invalid, json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Unauthorized:
            self._send(401, {"error": "로그인이 필요합니다"})
        except members.Throttled as e:
            self._send(429, {"error": str(e)})
        except Exception as e:            # 엔진 내부 오류는 메시지만 (경로·스택 비노출)
            self._send(500, {"error": f"내부 오류: {type(e).__name__}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    global ENGINE, MEMBERS
    ap = argparse.ArgumentParser(); ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--origin", action="append", default=[], help="브라우저에서 직접 부를 출처 추가 (예: https://fitforu.example.com)")
    a = ap.parse_args()
    ORIGINS.update(a.origin)
    ENGINE = RuleEngine()
    MEMBERS = members.Members()
    print(f"Fit-For-U 추천 API — http://{a.host}:{a.port}  (POST /recommend · /feedback, GET /health · /meta · /image)", flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
