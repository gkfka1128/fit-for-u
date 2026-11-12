"""
팀 웹페이지(fit-for-u.py, 조민상 백엔드 파트) ↔ 규칙 엔진 연결 다리. 웹페이지 쪽 값을 엔진 입력으로 바꾸고, 엔진 출력을 웹페이지 카드 형식으로 돌려준다.

  웹페이지 값                                  →  엔진 입력
  profile.gender 남성/여성                     →  sex M/F
  profile.height·weight                        →  build (BMI <18.5 마름 / <23 보통 / ≥23 통통)
  body_type 역삼각형/삼각형/직사각형/…         →  group 상체형/하체형/균형  (BODY_TYPE)
  weather_data (기상청 초단기실황 + 단기예보)  →  feels_like (기상청 체감온도식) · precip_prob (단기예보 12시간 최대 강수확률, 지금 비 오면 ≥80. 예보 없으면 80/10)
  situation 학교/데이트/출근/…  + profile.style →  style 묶음 (SITUATION_TPO → tpo.py, STYLE_MAP)
  profile.fit 오버핏/레귤러핏/슬림핏            →  핏 선호 가중치 (FitPreference, 👍👎 와 같은 통로)

  엔진 출력 1안 → [{icon, category, name, desc, image, color}, … 4개]  (웹페이지 show_outfit_items 형식 + 이미지)

  out = recommend_for_web(profile, "역삼각형", weather_data, "출근")
  out["outfits"][0]["items"]  → 카드 4개,  out["outfits"][0]["reasons"] → 이유 문장들,  out["outfits"][0]["links"] → 무신사 검색 링크
"""
import io, math, os, sys
from datetime import datetime
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import tint, tpo
from preference import Preference

BODY_TYPE = {"역삼각형": "상체형", "삼각형": "하체형", "직사각형": "균형", "모래시계형": "균형", "균형형": "균형",
             "상체형": "상체형", "하체형": "하체형", "균형": "균형", "상체중심형": "상체형", "하체중심형": "하체형"}
SITUATION_TPO = {"학교": "캠퍼스·일상", "데이트": "데이트", "출근": "출근·면접", "친구와 약속": "친구 약속·나들이",
                 "운동": "운동·야외활동", "여행": "여행·휴가"}
STYLE_MAP = {"캐주얼": [], "미니멀": ["모던"], "스트릿": ["스트리트"], "스포티": ["스포티"], "댄디": ["클래식", "모던"]}
FIT_PREF = {   # 선호 핏 → 속성 가중치 (규칙·날씨를 넘지 않는 편향. 11/11: "선호가 잘 반영 안 됨" → 슬림핏 일치율 19%·오버핏 52% 로 약해서 키우고, 반대 핏은 깎음)
    "오버핏": {"상의|핏|오버사이즈": 1.2, "상의|핏|루즈": 0.9, "상의|핏|타이트": -0.6, "아우터|핏|오버사이즈": 0.8, "아우터|핏|루즈": 0.4, "아우터|핏|타이트": -0.4,
             "하의|핏|와이드": 0.6, "하의|핏|루즈": 0.4, "하의|핏|스키니": -0.4},
    "슬림핏": {"상의|핏|타이트": 1.3, "상의|핏|노멀": 0.3, "상의|핏|루즈": -0.6, "상의|핏|오버사이즈": -1.0, "하의|핏|스키니": 0.9, "하의|핏|노멀": 0.2,
             "하의|핏|와이드": -0.5, "하의|핏|루즈": -0.4, "아우터|핏|타이트": 0.6, "아우터|핏|오버사이즈": -0.6, "아우터|핏|루즈": -0.2},
    "레귤러핏": {"상의|핏|노멀": 0.6, "상의|핏|오버사이즈": -0.6, "상의|핏|타이트": -0.3, "하의|핏|노멀": 0.5, "하의|핏|와이드": -0.1, "하의|핏|스키니": -0.2,
              "아우터|핏|노멀": 0.4, "아우터|핏|오버사이즈": -0.5},
}
def engine_cpref(profile):
    """프로필의 개인화 선택 정보 → 엔진 cpref. 이상한 값은 버린다 (좋아하는 색과 겹치는 피하는 색은 좋아하는 쪽을 뺌)"""
    ok = lambda v: [c for c in (v if isinstance(v, list) else []) if c in tpo.ALL_COLORS][:5]
    no = ok(profile.get("avoid_colors")); like = [c for c in ok(profile.get("like_colors")) if c not in no]
    pc = profile.get("personal_color"); hair = profile.get("hair")
    out = {"like": like, "avoid": no, "personal": pc if pc in tpo.PERSONAL_COLORS else None, "hair": hair if hair in tpo.HAIRS else None}
    return out if any(out.values()) else None


ICON = {"아우터": "🧥", "상의": "👕", "하의": "👖", "신발": "👟"}
CODE_DIR = HERE
_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        from rule_engine import RuleEngine
        _ENGINE = RuleEngine()
    return _ENGINE


class FitPreference(Preference):
    """선호 핏을 취향 가중치로 — 이유 문장은 '오버핏 선호 반영' 처럼"""
    def __init__(self, fit):
        super().__init__(FIT_PREF.get(fit, {})); self.fit = fit

    def explain(self, top, bot, out, colors=None):
        return f"{self.fit} 선호를 반영" if super().explain(top, bot, out, colors) else None


# ---- 👍👎 (React) — 가중치 계산만 여기서 하고, 저장은 회원 DB(members.py, POST /prefs)가 맡는다. 요청마다 pref 를 같이 보낸다.
PREF_MAX_KEYS, PREF_MAX_HISTORY = 400, 30
PREF_PARTS = {"상의", "하의", "아우터"}


def clean_pref(d):
    """브라우저가 보낸 취향 {weights:{"부위|속성|값": 가중치}, history:[...]} 검증 — 이상한 값은 버린다"""
    d = d if isinstance(d, dict) else {}
    w = d.get("weights") if isinstance(d.get("weights"), dict) else {}
    out = {}
    for k, v in list(w.items())[:PREF_MAX_KEYS]:
        parts = k.split("|") if isinstance(k, str) else []
        if len(parts) != 3 or parts[0] not in PREF_PARTS or len(k) > 60: continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v): continue
        out[k] = max(-1.5, min(1.5, float(v)))
    hist = [h for h in (d.get("history") or []) if isinstance(h, (list, tuple)) and len(h) == 2][-PREF_MAX_HISTORY:]
    res = {"weights": out, "history": [[bool(h[0]), str(h[1])[:200]] for h in hist]}
    # 👍👎 누적 횟수 — history 는 최근 30건만 남겨서, 많이 누르면 오래된 👍 가 밀려나며 숫자가 서로 영향을 줬다. 횟수는 따로 센다.
    for k in ("n_like", "n_dislike"):
        v = d.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1_000_000: res[k] = v
    return res


class WebPreference:
    """선호 핏(프로필) + 👍👎 로 쌓인 취향을 합친 것. 엔진은 score · color_score · explain 만 쓴다"""
    def __init__(self, fit, pref=None):
        self.fit = FitPreference(fit); self.user = Preference(**{"weights": (pref or {}).get("weights"), "history": (pref or {}).get("history")})

    def score(self, part, item): return max(-1.5, min(1.5, self.fit.score(part, item) + self.user.score(part, item)))
    def color_score(self, part, color): return self.user.color_score(part, color)
    def explain(self, top, bot, out, colors=None):
        return self.user.explain(top, bot, out, colors) or self.fit.explain(top, bot, out, colors)


def apply_feedback(pref, outfit, like):
    """👍(like=True)/👎 → 새 취향 dict. outfit = /web/recommend 응답의 outfits[i].fb"""
    cp = clean_pref(pref); like = bool(like)
    nl = cp.get("n_like", sum(1 for h in cp["history"] if h[0])); nd = cp.get("n_dislike", sum(1 for h in cp["history"] if not h[0]))
    p = Preference(cp["weights"], cp["history"]); p.feedback(outfit, like)
    return {**clean_pref({"weights": p.w, "history": p.history, "n_like": nl + like, "n_dislike": nd + (not like)}), "summary": p.summary()}


# ---- 이유 문장을 화면용으로: 종류(체형·날씨·취향·상황·데이터)로 묶고 해요체로
_ENDINGS = [("줄임", "줄였어요"), ("뺌", "뺐어요"), ("보임", "보여요"), ("균형", "균형을 맞췄어요"), ("정돈", "정돈했어요"), ("정리", "정리해요"),
            ("만듦", "만들었어요"), ("또렷하게", "또렷하게 했어요"), ("살림", "살렸어요"), ("더함", "더했어요"), ("함", "해요"), ("보이게", "보이게 했어요"),
            ("연장", "연장했어요"), ("맞음", "맞아요"), ("소화", "소화할 수 있어요"), ("줌", "줬어요"), ("위로", "위로 모았어요")]


def _batchim(w):
    c = w[-1] if w else ""
    return "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 != 0


def _yo(t):
    t = t.strip().rstrip(".")
    t = t.replace("골랐습니다", "골랐어요").replace("뺐습니다", "뺐어요")
    for a, b in _ENDINGS:
        if t.endswith(a): return t[: -len(a)] + b
    return t


def friendly_reasons(reasons, eng, body, situation, profile, style):
    body_txt = {r["reason"] for r in eng.body["rules"]} | {r["reason"] for r in eng.body["color_rules"]}
    why = []
    for r in reasons:
        if r.startswith("체감"):
            k, t = "날씨", _yo(r)
        elif r.startswith("추운 날이라"):
            k, t = "날씨", _yo(r)
        elif r.startswith("비 예보라"):
            k, t = "날씨", r + ("을" if _batchim(r) else "를") + " 골랐어요"
        elif r in body_txt:
            k, t = "체형", _yo(r)
        elif "조합 모델" in r:
            part = r.split("선택되는 ")[-1].split(" (")[0] if "선택되는 " in r else "아이템"
            k, t = "데이터", f"실제 코디 96만 벌에서 나머지 옷들과 특히 자주 함께 입은 {part}예요"
        elif r.startswith("남성 착장"):
            name = r.split("자주 보이는 ")[-1]
            k, t = "데이터", f"남성분들이 실제로 많이 입는 {name}{'이에요' if _batchim(name) else '예요'}"
        elif r.endswith("스타일에서 자주 입는 아이템"):
            k, t = "상황", f"'{situation}'에 어울리는 {r.split(' 스타일에서')[0]} 스타일 아이템이에요" if situation else r + "이에요"
        elif r.startswith("상황에 맞춰 고른 "):
            name = r[len("상황에 맞춰 고른 "):]
            k, t = "상황", (f"'{situation}'에 맞춰 고른 {name}{'이에요' if _batchim(name) else '예요'}" if situation else _yo(r))
        elif r.startswith("좋아하시는 ") and r.endswith(" 색을 반영"):
            k, t = "취향", f"좋아하신다고 고른 {r[len('좋아하시는 '):-len(' 색을 반영')]} 색을 넣었어요"
        elif " 톤에 어울리는 " in r and r.split(" 톤에")[0] in tpo.PERSONAL_COLORS:
            nm = r.split("어울리는 ")[1]; k, t = "취향", f"{r.split(' 톤에')[0]} 톤에 어울리는 {nm}{'이에요' if _batchim(nm) else '예요'}"
        elif r.endswith(" 상의") and r.split("에 어울리는 ")[0] in tpo.HAIRS:
            k, t = "취향", f"{r.split('에 어울리는 ')[0]}에 어울리는 {r.split('에 어울리는 ')[1]}예요"
        elif r.startswith("선호하신 ") and " 스타일에 맞춰 고른 " in r:
            st, name = r[len("선호하신 "):].split(" 스타일에 맞춰 고른 ", 1)
            k, t = "취향", f"선호하시는 {st} 스타일에 맞춰 고른 {name}{'이에요' if _batchim(name) else '예요'}"
        elif r.endswith("선호를 반영"):
            k, t = "취향", f"선호하시는 {r.split(' 선호')[0]}으로 맞췄어요"
        elif r.startswith("지난번에"):
            k, t = "취향", r.replace("노멀 핏", "기본 핏").replace("노말", "기본").replace("노멀", "기본") + " (👍 반영)"
        else:
            k, t = "데이터", _yo(r)
        why.append({"kind": k, "text": t})
    have = {x["kind"] for x in why}
    if "체형" not in have:
        why.append({"kind": "체형", "text": f"{body['group']} 체형에 무리 없는 기본 실루엣으로 골랐어요"})
    if "상황" not in have and situation:
        why.append({"kind": "상황", "text": f"'{situation}'에 입기 좋은 아이템으로 골랐어요"})
    # 11/11: 실제로 반영된 이유가 없는데 "선호를 반영했어요"를 붙이면 반영 여부를 알 수 없다 → 핏 선호만 기본 문구로 남기고, 스타일은 위의 구체 이유(K1)가 있을 때만 보여 준다
    if "취향" not in have and profile.get("fit"):
        why.append({"kind": "취향", "text": f"{profile['fit']} 선호를 반영했어요"})
    order = {"체형": 0, "날씨": 1, "취향": 2, "상황": 3, "데이터": 4}
    return sorted(why, key=lambda x: order[x["kind"]])


def feels_like(t, rh=50.0, wind_ms=0.0, month=None):
    """기상청 체감온도. 여름(5~9월)은 습도 반영식(Stull 습구온도), 그 외는 바람 반영식(기온 ≤10°C, 풍속 ≥4.8km/h 일 때)"""
    month = month or datetime.now().month
    if 5 <= month <= 9:
        tw = (t * math.atan(0.151977 * math.sqrt(rh + 8.313659)) + math.atan(t + rh) - math.atan(rh - 1.67633)
              + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)
        return round(-0.2442 + 0.55399 * tw + 0.45535 * t - 0.0022 * tw ** 2 + 0.00278 * tw * t + 3.0, 1)
    v = wind_ms * 3.6
    if t <= 10 and v >= 4.8:
        return round(13.12 + 0.6215 * t - 11.37 * v ** 0.16 + 0.3965 * v ** 0.16 * t, 1)
    return round(float(t), 1)


def engine_weather(weather_data, month=None):
    w = weather_data or {}
    raining = w.get("precipitation_type", 0) != 0 or w.get("rainfall_1h", 0) > 0
    pop = w.get("precip_prob")                                     # 단기예보 강수확률 (kma_forecast) — 있으면 우선, 지금 비가 오면 최소 80
    pop = max(int(pop), 80 if raining else 0) if pop is not None else (80 if raining else 10)
    if w.get("feels_like") is not None:                            # 이미 체감온도가 오면 그대로 (React 쪽 /weather 결과)
        return {"feels_like": float(w["feels_like"]), "precip_prob": pop}
    return {"feels_like": feels_like(float(w.get("temperature", 15)), float(w.get("humidity", 50)), float(w.get("wind_speed", 0)), month),
            "precip_prob": pop}


def engine_body(profile, body_type):
    sex = "F" if profile.get("gender") == "여성" else "M"
    try:
        bmi = float(profile["weight"]) / (float(profile["height"]) / 100) ** 2
        build = "마름" if bmi < 18.5 else "보통" if bmi < 23 else "통통"
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        build = "보통"
    return {"sex": sex, "group": BODY_TYPE.get(body_type, "균형"), "build": build, "leg": "보통"}


# 상황별로 어느 쪽에 비중을 뒀는지 화면에 보여 줄 한 줄 (10/27 중간발표 피드백: "데이트는 포멀, 운동은 스포츠" 처럼 설명). 손으로 쓴 문장 — 실제 선택은 tpo.py 표가 한다
SITUATION_FOCUS = {"학교": "오래 입어도 편한 일상복 쪽", "데이트": "단정하고 깔끔한 쪽 (포멀에 가깝게)", "출근": "격식 있는 단정한 차림",
                   "친구와 약속": "너무 차려입지 않은 세미 캐주얼", "운동": "움직이기 편한 스포츠웨어", "여행": "편하고 활동적인 휴양 차림"}


def situation_summary(situation, sex):
    """상황 → {situation, focus, styles(우선한 K-Fashion 스타일), preferred(점수를 올려 준 아이템), excluded(아예 뺀 아이템)} — 없는 상황이면 None"""
    t = SITUATION_TPO.get(situation)
    if not t: return None
    ex = []
    for part, rule in tpo.EXCLUDE.get(t, {}).items():
        if part == "신발": ex += rule; continue
        for attr, vals in rule.items():
            ex += [v if attr in ("카테고리", "소매기장") else f"{v} {part}" for v in vals]
    return {"situation": situation, "focus": SITUATION_FOCUS.get(situation, ""), "styles": tpo.styles_for(t, sex) or [],
            "preferred": tpo.preferred(t, sex)[:6], "excluded": ex}


PREF_STYLE_REPEAT = int(os.environ.get("FFU_PREF_STYLE_REPEAT", 2))


def engine_style(profile, situation, sex):
    """상황 스타일 + 사용자가 고른 선호 스타일. 엔진은 스타일 lift 를 평균 내므로 선호 스타일을 REPEAT 번 넣어 그만큼 크게 센다
    (한 번만, 그것도 상황 스타일에 이미 있으면 빼고 넣어서 '취향과 다른 코디가 나온다'는 피드백이 있었다)"""
    st = list(tpo.styles_for(SITUATION_TPO.get(situation), sex) or [])
    for s in STYLE_MAP.get(profile.get("style"), []):
        st += [s] * PREF_STYLE_REPEAT
    return st or None


# K-Fashion "우븐" = 니트·저지가 아닌 일반 직물 (상의 39%·하의 45%·아우터 41% 로 가장 흔한 라벨) → 화면에서는 정보가 없어 뺀다.
# 데님·니트·린넨·가죽처럼 뜻이 있는 소재는 그대로 보여준다. 엔진 내부 라벨·점수는 바꾸지 않음.
HIDE_WORDS = {"우븐", "노멀", "노말"}   # 정보 없는 기본값 라벨 (K-Fashion 은 아우터 기장만 "노말" 표기)


def _plain(label):
    ws = [w for w in str(label).split() if w not in HIDE_WORDS]
    return " ".join(w for i, w in enumerate(ws) if not (i + 1 < len(ws) and ws[i + 1].startswith(w)))   # '니트 니트웨어'·'패딩 패딩' → 뒤 단어만


def _desc(x):
    keys = ("핏", "기장", "넥라인", "소매기장", "소재")
    skirt = x.get("카테고리") == "스커트"
    alias = {"맥시": "맥시" if skirt else "롱", "벨보텀": "플레어" if skirt else "벨보텀", "미니": "미니" if skirt or x.get("카테고리") not in ("팬츠", "청바지", "조거팬츠") else "반바지"}
    return " · ".join(alias.get(str(x[k]), str(x[k])) for k in keys if x.get(k) and x[k] not in HIDE_WORDS) or "기본"


def to_cards(o):
    """엔진 1안 → 웹페이지 카드 4개 (아우터 없으면 3개). image = 코드 폴더 기준 절대 경로(AI 형태 컷), color = 입힐 색"""
    gen, colors = o.get("gen") or {}, o.get("colors") or {}
    cards = []
    for part, key in (("아우터", "outer"), ("상의", "top"), ("상의", "layer"), ("하의", "bottom")):   # layer = 추운 날 셔츠 위에 겹친 니트
        x = o.get(key)
        if not x: continue
        cards.append({"icon": ICON[part], "category": {"아우터": "OUTER", "상의": "TOP", "하의": "BOTTOM"}[part], "name": _plain(x["label"]),
                      "desc": ("셔츠 위에 겹쳐 입기 · " if key == "layer" else "") + _desc(x),
                      "image": os.path.join(CODE_DIR, gen[key]) if gen.get(key) else None, "color": colors.get("레이어" if key == "layer" else part)})
    shoe_name = f"{colors['신발']} {o['shoes']}" if colors.get("신발") else o["shoes"]
    cards.append({"icon": ICON["신발"], "category": "SHOES", "name": shoe_name, "desc": "코디·날씨에 맞춘 신발",
                  "image": os.path.join(CODE_DIR, gen["shoes"]) if gen.get("shoes") else None, "color": colors.get("신발")})
    return cards


def card_png(card, size=384):
    """카드 이미지 → 추천 색을 입힌 PNG 바이트 (이미지 없으면 None)"""
    p = card.get("image")
    if not p or not os.path.exists(p): return None
    from PIL import Image
    im = Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
    buf = io.BytesIO(); (tint.tint(im, card["color"]) if card.get("color") else im).save(buf, "PNG"); return buf.getvalue()


def recommend_for_web(profile, body_type, weather_data, situation, eng=None, body=None, pref=None, use_body=True):
    """body: 체형 분석(body_cluster_bridge)이 준 {sex, group, build, leg} — 있으면 body_type 대신 이걸 쓴다
    pref: 👍👎 로 쌓인 취향 {weights, history} — 있으면 선호 핏 위에 더해 반영
    use_body=False: 체형 규칙을 끈 대조군 (만족도 A/B 평가용)"""
    eng = eng or engine()
    body = body or engine_body(profile, body_type); w = engine_weather(weather_data); style = engine_style(profile, situation, body["sex"])
    res = eng.recommend(body, w, style=style, pref=WebPreference(profile.get("fit"), clean_pref(pref) if pref else None), tpo=SITUATION_TPO.get(situation),
                        use_body=use_body, taste=profile.get("style"), cpref=engine_cpref(profile))
    outs = []
    for o in res["outfits"]:
        reasons = [s for s in o["reason"].rstrip(".").split(". ") if s]
        why = friendly_reasons(reasons, eng, body, situation, profile, style)
        no = (engine_cpref(profile) or {}).get("avoid") or []
        if no and not any(c in no for c in (o.get("colors") or {}).values()):      # 피하고 싶은 색을 뺐다는 것을 한 번 알려 줌
            why.append({"kind": "취향", "text": f"피하고 싶다고 하신 {' · '.join(no)} 색은 넣지 않았어요"})
        outs.append({"items": to_cards(o), "reasons": reasons, "why": why,
                     "links": [(q, f"https://www.musinsa.com/search/goods?keyword={quote(q)}") for q in o["query"]], "rules": o["rules"],
                     "fb": {k: o[k] for k in ("outer", "top", "bottom") if o.get(k)}})   # 👍👎 를 보낼 때 그대로 돌려줌
    return {"outfits": outs, "band": res["band"], "rain": res["rain"], "situation": situation_summary(situation, body["sex"]),
            "input": {"body": body, "weather": w, "style": style, "fit": profile.get("fit")}}


# ---- 유사 의상 (11/11 ④) — 추천 카드의 옷 한 벌과 비슷한 옷. 카드 → fb 의 id 로 같은 카테고리에서 속성이 가까운 옷을 찾는다
def _shared_text(k, v, cat=None):
    """유사 의상에서 '같은 속성'을 화면 문구로 (노멀·우븐은 정보가 없어 기본으로, 바지의 '맥시'·'미니'는 카드 표기처럼 롱·반바지로)"""
    v = {"노멀": "기본", "우븐": "일반 직물", "노말": "기본"}.get(v, v)
    if k == "기장" and cat != "스커트": v = {"맥시": "롱", "미니": "반바지"}.get(v, v)
    return f"{v} 핏" if k == "핏" else f"{v} 소재" if k == "소재" else f"{v} 기장" if k == "기장" else str(v)


SIM_PARTS = {"top": "상의", "bottom": "하의", "outer": "아우터"}


def similar_for_web(profile, body_type, weather_data, situation, key, item_id, color=None, eng=None, body=None, pref=None, n=4):
    """key = fb 의 top|bottom|outer, item_id = fb[key]["id"] → {"base": 기준 옷 이름, "items": [카드 …(shared·link 포함)]}"""
    eng = eng or engine()
    part = SIM_PARTS.get(key)
    if not part or not isinstance(item_id, int) or isinstance(item_id, bool): raise ValueError("key 는 top|bottom|outer, item_id 는 정수")
    if not 0 <= item_id < len(eng.items[part]): raise ValueError("item_id 가 범위를 벗어났습니다")
    body = body or engine_body(profile, body_type); w = engine_weather(weather_data)
    wp = WebPreference(profile.get("fit"), clean_pref(pref) if pref else None)
    rows = eng.similar(body, w, part, item_id, color=color if color in tpo.ALL_COLORS else None, n=n, style=engine_style(profile, situation, body["sex"]), pref=wp,
                       tpo=SITUATION_TPO.get(situation), taste=profile.get("style"), cpref=engine_cpref(profile))
    base = eng._fmt((item_id, eng.items[part][item_id]), color if color in tpo.ALL_COLORS else None)
    items = []
    for r in rows:
        x = r["item"]
        items.append({"icon": ICON[part], "category": {"아우터": "OUTER", "상의": "TOP", "하의": "BOTTOM"}[part], "name": _plain(x["label"]), "desc": _desc(x),
                      "image": os.path.join(CODE_DIR, r["gen"]) if r["gen"] else None, "color": x.get("색상"),
                      "shared": [_shared_text(k, v, base.get("카테고리")) for k, v in r["shared"]], "link": f"https://www.musinsa.com/search/goods?keyword={quote(r['query'])}", "query": r["query"]})
    return {"base": _plain(base["label"]), "part": part, "items": items}
