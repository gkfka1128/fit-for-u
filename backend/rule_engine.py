"""
규칙 엔진 — 체형(sex, group, build, leg) + 날씨(feels_like, precip_prob) [+ 스타일, 👍👎 취향] → 코디 3안 + 이유 + 무신사 검색어 + 사진.

  후보 846종(K-Fashion) → ① 성별·날씨·상황 필터 → ② 아이템 점수(체형 규칙 + 인기도 + 남성 lift + 스타일 lift + 취향
     + 상황별 선호 tpo.PREFER + 남성 실루엣 SILHOUETTE)
  → ③ 상위 24 상의 × 16 하의 × 12 아우터 조합 = 아이템 합 + 조합 학습 모델 log P(1위와의 차이를 COMPAT_CAP 에서 포화)
  → ④ 3안(상의·하의 중복 금지, 같은 카테고리·색 반복은 DIV_W·COLOR_DIV_W 만큼 감점)
  → 색(P(색|아이템) + 색 lift + 색 규칙 + 날씨·남성·스타일·취향) → 신발 → ⑤ 이유 문장 · 검색어 · 규칙 id · 사진

  .\\.venv\\Scripts\\python.exe rule_engine.py --sex M --group 상체형 --build 보통 --leg 보통 --feels 9 --precip 10
  .\\.venv\\Scripts\\python.exe rule_engine.py --sex F --group 균형 --build 마름 --leg 롱 --feels 18 --style 모던 --json
⚠ 9/29 복원본: 원본 소스가 유실돼 문서·기록을 기준으로 다시 작성 (구조·점수식은 동일, 세부 수치는 재현 검증 필요).
"""
import argparse, io, itertools, json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); RULES = os.path.join(HERE, "rules")
sys.path.insert(0, HERE)
from kfashion_cooc import ITEM_ATTRS
from train_compat import featurize, GIVEN
import tpo as tpo_rules

PARTS = ("상의", "하의", "아우터")
COLOR_TOP_K = 5


def load(p):
    return json.loads(io.open(p, encoding="utf-8").read())


def _opt(p):
    return load(p) if os.path.exists(p) else None


class RuleEngine:
    # 쏠림 조절 (10/20, freq_report.py 로 측정): 인기도는 실제로 많이 입는 옷을 고르는 안전장치지만, 그대로 두면
    # 가장 흔한 몇 벌이 체형·스타일과 상관없이 1순위를 독차지한다 → 인기도를 일정 수준(분위수)에서 포화시키고,
    # 조합 모델 점수에서 아이템 자체의 흔함(사전확률)을 일부 빼서 "이 조합이라 잘 어울림" 쪽을 본다.
    POP_W = 0.35          # 인기도 가중치
    POP_CAP_Q = 0.5       # 인기도 포화 분위수 — 중앙값보다 흔한 옷은 인기도 점수가 같다 (1.0 = 포화 없음)
    COMPAT_BETA = 0.3     # 조합 점수에서 뺄 log 사전확률 비율 (0 = 그대로, 1 = 순수 lift) — 0.1 이면 블랙 발목 팬츠가 하의 1순위 24%, 0.3 이면 18% (청바지 15% 유지)
    STYLE_NEG = 0.0       # 스타일 lift 가 음수일 때 곱 — 청바지·반팔 티처럼 어디서나 입는 기본템은 특정 스타일 lift 가 -1.5 로 깎여 아예 사라짐
    # 조합 모델 점수 포화 (10/27): log P 는 후보끼리 10~15 차이가 나서(중앙값 -14, 최고 0) 아이템 점수(체형·상황 합 2~3)를 덮었다
    # → '울 코트+터틀넥+슬랙스' 하나가 출근·데이트·친구 약속 1안을 독차지. 최고 조합 대비 차이 d(≤0)를 -CAP·(1-e^(d/CAP)) 로 눌러 쓴다
    #   (가까운 조합끼리는 거의 그대로 비교, 아주 어색한 조합은 최대 CAP 까지만 감점)
    COMPAT_W = float(os.environ.get("FFU_COMPAT_W", 1.0)); COMPAT_CAP = float(os.environ.get("FFU_COMPAT_CAP", 4.0))
    TPO_W = float(os.environ.get("FFU_TPO_W", 1.0))   # 상황 우선 표(tpo.PREFER) 가중치 (10/27)
    DIV_W = 1.0           # 3안 다양성: 앞 안과 같은 카테고리를 다시 쓸 때마다 빼는 점수 (같은 '모양'은 원래대로 아예 금지)
    LAYER_W = float(os.environ.get("FFU_LAYER_W", 0.5))   # 추운 날 차려입는 상황의 셔츠·블라우스 (위에 니트를 겹쳐 줄 수 있는 코디) 가산
    COLOR_DIV_W = 0.35    # 3안 다양성: 앞 안과 같은 부위에 같은 색을 다시 쓸 때마다 빼는 점수
    # 11/11 테스터 피드백 (튀는 색 / 전체적으로 갈색 / 어울리지 않는 옷 / 선호 스타일 / 스포티) — 모두 손으로 정한 값, 설문·A/B 로 검증 필요
    COLOR_LOUD_W = float(os.environ.get("FFU_COLOR_LOUD_W", 1.0))   # 튀는 색 감점 (COLOR_LOUD 표 × 이 값)
    ACCENT_W = 1.5        # 포인트 색(튀는 정도 0.5 이상)이 한 코디에 2개 이상일 때 추가 감점
    CLASH_W = 0.6         # 서로 다른 계열의 유채색 두 개 이상이 섞일 때 감점
    EARTH_W = float(os.environ.get("FFU_EARTH_W", 1.0))              # 갈색계(브라운·베이지·카키)가 3곳 이상 / 브라운이 2곳 이상일 때 감점
    FORMAL_W = float(os.environ.get("FFU_FORMAL_W", 0.6))            # 격식 차이(재킷+조거팬츠 같은 조합) 감점: 1.5 를 넘는 차이 1 당
    SHOE_FORMAL_W = 0.4   # 신발 격식이 옷 평균 격식과 다른 만큼 감점
    TASTE_W = float(os.environ.get("FFU_TASTE_W", 1.0))              # 선호 스타일 표(tpo.TASTE_PREFER) 가중치
    SPORT_NO_OUTER = 0.8  # 스포티·운동 + 선택 날씨(따뜻)에는 아우터 없이 가볍게 입는 안에 가산
    # 11/11 ④ 개인화 (cpref = {"like": [색], "avoid": [색], "personal": 퍼스널 컬러, "hair": 머리 길이})
    LIKE_COLOR_W = 0.9    # 좋아하는 색이 들어간 부위마다 가산 (튀는 색 감점도 면제)
    AVOID_COLOR_PEN = 3.0 # 피하고 싶은 색 — 후보에서 먼저 빼고, 그래도 남으면(대안 없음) 이만큼 감점
    PERSONAL_W = float(os.environ.get("FFU_PERSONAL_W", 1.0))   # 퍼스널 컬러 표(tpo.PERSONAL_COLOR) 가중치
    SIM_W = {"카테고리": 3.0, "핏": 1.0, "기장": 1.0, "소재": 1.0, "넥라인": 1.0, "소매기장": 1.0}   # 유사 의상: 같은 속성 1개당 가산

    def __init__(self):
        self.items = load(os.path.join(DATA, "kfashion_items.json"))
        cooc = load(os.path.join(DATA, "kfashion_cooc.json"))
        self.lift = {k: {(r["a"], r["b"]): r["lift"] for r in v["rows"]} for k, v in cooc.items()}
        self.body = load(os.path.join(RULES, "body_rules.json"))
        self.weather = load(os.path.join(RULES, "weather_rules.json"))
        self.fam = {c: f for f, cs in self.body["color_family"].items() for c in cs}
        # 학습된 조합 호환성 모델 (train_compat.py → models/, git 제외). 없으면 조합 점수 0 — 경고만 출력
        self.compat = {}
        for part in PARTS:
            f = os.path.join(HERE, "models", f"compat_{part}.joblib")
            if os.path.exists(f):
                import joblib
                self.compat[part] = joblib.load(f)
        if not self.compat: print("[rule_engine] models/compat_*.joblib 없음 → 조합 호환성 점수 없이 추천 (train_compat.py 로 생성)", file=sys.stderr)
        self.prior = {p: np.array([it["count"] for it in self.items[p]], dtype=float) for p in self.items}
        for p in self.prior: self.prior[p] /= self.prior[p].sum()
        self.pop_cap = {p: math.log10(float(np.quantile([it["count"] for it in self.items[p]], self.POP_CAP_Q))) for p in self.items}
        self.color = _opt(os.path.join(DATA, "kfashion_color.json"))
        self.style = _opt(os.path.join(DATA, "kfashion_style.json"))
        self.male = _opt(os.path.join(DATA, "kfashion_male.json"))
        self.shoe_stats = _opt(os.path.join(DATA, "polyvore_shoes.json"))
        self.keys = {p: [tuple(it["attrs"].get(a) for a in ITEM_ATTRS[p]) for it in self.items[p]] for p in PARTS}
        self.gen = self._load_gen()
        self.formal = {p: [formality(p, it["attrs"]) for it in self.items[p]] for p in PARTS}

    def _load_gen(self):
        """AI 생성 제품 컷 (gen_items.py, 라이트 그레이 형태 컷) → {(부위, idx): 상대경로}. 속성이 지금 후보와 같은 것만 (후보 재생성 시 어긋남 방지)"""
        man = _opt(os.path.join(DATA, "gen_items", "manifest.json"))
        if not man: return {}
        shoes = [sh["name"] for sh in self.weather["shoes"]["items"]]; out = {}
        for rel, e in man["items"].items():
            part, i = e["part"], e["idx"]
            if not os.path.exists(os.path.join(DATA, "gen_items", rel)): continue
            ok = (part in PARTS and i < len(self.items[part]) and self.items[part][i]["attrs"] == e["attrs"]) or                  (part == "신발" and i < len(shoes) and shoes[i] == e["attrs"].get("카테고리"))
            # 남성 실루엣 컷(gen_items.py --sex M)은 (성별, 부위, idx) 로 — 없으면 공용 컷
            if ok: out[(e["sex"], part, i) if e.get("sex") else (part, shoes[i] if part == "신발" else i)] = "data/gen_items/" + rel
        return out

    # ---------------------------------------------------------------- 날씨 필터
    def band(self, feels):
        for b in self.weather["bands"]:
            if b["min"] <= feels < b["max"]:
                return b
        return self.weather["bands"][-1] if feels < 0 else self.weather["bands"][0]

    def weather_ok(self, part, it, band, rain):
        a = it["attrs"]; mat = a.get("소재")
        if part == "상의":
            if band.get("top_sleeve") and a.get("소매기장") and a["소매기장"] not in band["top_sleeve"]: return False
            if mat in band.get("top_material_exclude", []): return False
            if mat == "니트" and band.get("knit_sleeve_only") and a.get("소매기장") not in band["knit_sleeve_only"]: return False
        elif part == "하의":
            if mat in band.get("bottom_material_exclude", []): return False
            # 반바지(스커트 아닌 미니 기장)는 체감 20도 미만이면 뺌 — 10/22 피드백 "17도 출근에 미니 청바지"
            if a.get("기장") == "미니" and a.get("카테고리") != "스커트" and band["name"] in COLD_FOR_SHORTS: return False
        else:
            if mat in band.get("outer_material_exclude", []): return False
            if a.get("카테고리") in band.get("outer_category_exclude", []): return False   # 추운 날 조끼·가디건만 걸치는 일 방지
        if rain and mat in self.weather["rain"]["material_exclude"]: return False
        return True

    # ---------------------------------------------------------------- 성별
    def sex_ok(self, sex, part, it):
        ex = self.body["sex_exclude"].get(sex, {}).get(part, {})
        return not any(it["attrs"].get(k) in vs for k, vs in ex.items())

    def male_lift(self, part, i):
        if not self.male: return 0.0
        return self.male["item_lift"].get(part, {}).get(str(i), 0.0)

    def style_lift(self, style, part, i):
        """style = 이름 하나 또는 여러 개(TPO → 스타일 묶음). 여러 개면 lift 평균"""
        if not (style and self.style): return 0.0
        ss = _styles(style)
        v = sum(self.style["item_lift"].get(x, {}).get(f"{part}|{i}", 0.0) for x in ss) / len(ss)
        return v if v >= 0 else self.STYLE_NEG * v

    def style_color_lift(self, style, part, color):
        ss = _styles(style)
        return sum(self.style["color_lift"].get(x, {}).get(f"{part}|{color}", 0.0) for x in ss) / len(ss)

    # ---------------------------------------------------------------- 체형 점수
    def body_score(self, body, part, it):
        score, fired = 0.0, []
        for r in self.body["rules"]:
            if r["part"] != part: continue
            if r["sex"] != "any" and r["sex"] != body.get("sex"): continue
            if any(body.get(k) != v for k, v in r["when"].items()): continue
            if it["attrs"].get(r["attr"]) == r["value"]:
                score += r["weight"]; fired.append(r)
        return score, fired

    def item_score(self, body, part, i, it, band, style=None, pref=None, rain=False, use_body=True, tpo=None, taste=None, cpref=None):
        s, fired = self.body_score(body, part, it) if use_body else (0.0, [])
        s += sum(vals.get(it["attrs"].get(k), 0.0) for k, vals in SILHOUETTE.get(body.get("sex"), {}).get(part, {}).items())   # 성별 실루엣
        s += self.POP_W * min(math.log10(it["count"]), self.pop_cap[part])   # 인기도: 실제로 많이 입는 옷 (포화)
        if part == "아우터" and it["attrs"].get("소재") in band.get("outer_material_prefer", []): s += 0.6
        if part == "아우터": s -= band.get("outer_category_penalty", {}).get(it["attrs"].get("카테고리"), 0.0)   # 선선·쌀쌀: 조끼 쏠림 완화 (금지는 아님)
        if part == "상의" and it["attrs"].get("소재") in band.get("top_material_prefer", []): s += 0.4
        if band["name"] in BARE_COLD:                                       # 10/27 여성 점검: 영하에 7부 바지·크롭 상의 (발목·허리 노출)
            a = it["attrs"]
            if part == "하의" and a.get("기장") == "미디" and a.get("카테고리") != "스커트": s -= 0.8
            if part == "상의" and a.get("기장") == "크롭": s -= 0.6
        extra = []
        if rain and part == "아우터" and it["attrs"].get("카테고리") in self.weather["rain"].get("outer_prefer", []):
            s += 0.6; extra.append(("R1", 0.6))                  # 비: 젖어도 되는 점퍼·짚업 우선
        if body.get("sex") == "M":
            m = self.male_lift(part, i)
            if m: s += 0.8 * m
            if m >= 0.3: extra.append(("M1", m, it))
        sl = self.style_lift(style, part, i)
        if sl: s += 0.7 * sl
        if sl >= 0.3: extra.append(("T1", sl))
        tp = tpo_rules.prefer_score(tpo, part, it["attrs"], body.get("sex", "F")) if tpo else 0.0
        if tp: s += self.TPO_W * tp
        if tp >= 0.5: extra.append(("S1", tp, it))
        tw = tpo_rules.taste_score(taste, part, it["attrs"]) if taste else 0.0     # 프로필의 선호 스타일 (캐주얼·미니멀·스트릿·스포티·댄디)
        if tw: s += self.TASTE_W * tw
        if tw >= 0.6: extra.append(("K1", tw, it))
        hw = tpo_rules.hair_neck_score(cpref.get("hair"), it["attrs"]) if (cpref and part == "상의") else 0.0   # 머리 길이 → 목선
        if hw: s += hw
        if hw >= 0.3: extra.append(("H1", hw, it))
        if pref is not None:
            pv = pref.score(part, it)
            if pv: s += 0.8 * pv
            if pv >= 0.3: extra.append(("P1", pv))
        return s, fired, extra

    # ---------------------------------------------------------------- 조합 점수
    def compat_scores(self, combos):
        """combos = [(top, bottom, outer|None)] (각각 (id, item)) → [(log P 합, 노트)]"""
        n = len(combos)
        if not self.compat:
            return [(0.0, [])] * n
        keys = lambda part, x: self.keys[part][x[0]] if x else None
        out = [[0.0, []] for _ in range(n)]
        best = [(0.0, None)] * n
        for part in PARTS:
            m = self.compat.get(part)
            if m is None: continue
            rows, idx = [], []
            for c, (t, b, o) in enumerate(combos):
                slot = {"상의": t, "하의": b, "아우터": o}
                if slot[part] is None: continue
                given = {q: keys(q, slot[q]) for q in GIVEN[part]}
                rows.append(featurize(part, given)); idx.append(c)
            if not rows: continue
            X = _transform(m["vocab"], rows)
            lp = m["clf"].predict_log_proba(X)
            cls = {int(k): j for j, k in enumerate(m["clf"].classes_)}
            for r, c in enumerate(idx):
                slot = {"상의": combos[c][0], "하의": combos[c][1], "아우터": combos[c][2]}[part]
                j = cls.get(slot[0])
                v = float(lp[r, j]) if j is not None else math.log(1e-6)
                ratio = v - math.log(self.prior[part][slot[0]] + 1e-9)
                out[c][0] += v - self.COMPAT_BETA * math.log(self.prior[part][slot[0]] + 1e-9)
                if ratio > best[c][0]: best[c] = (ratio, part)
        for c in range(n):
            if best[c][1] and best[c][0] >= 0.4:
                out[c][1].append(f"이 조합에서 특히 자주 선택되는 {best[c][1]}")
        return [(o[0], o[1]) for o in out]

    # ---------------------------------------------------------------- 색
    def color_choices(self, part, i, extra=()):
        """extra = 사용자가 좋아하는 색 — 그 아이템의 상위 색에 없어도 후보에 넣는다(가장 낮은 확률로)"""
        c = self.color or {}
        ic = c.get("item_color", {}).get(part, {}).get(str(i)) or c.get("color_prior", {}).get(part, {})     # 학습에 코디가 없던 아이템은 부위 전체 색 분포로
        ic = dict(list(ic.items())[:COLOR_TOP_K + 1])
        tot = sum(ic.values()) or 1
        out = [(c, math.log((n + 0.5) / (tot + 2.5))) for c, n in list(ic.items())[:COLOR_TOP_K]]
        have = {c for c, _ in out}
        lo = min((lp for _, lp in out), default=math.log(0.5 / (tot + 2.5)))      # 좋아하는 색은 이 아이템의 후보 중 가장 낮은 색과 같은 수준에서 출발 (학습 확률이 너무 낮으면 가산점이 안 먹음)
        return out + [(c, lo - 0.3) for c in extra if c not in have]

    @staticmethod
    def _loud(part, color):
        """튀는 정도 — 블루·스카이블루 하의는 청바지 색이라 거의 안 깎음"""
        if part == "하의" and color in ("블루", "스카이블루"): return 0.1 if color == "블루" else 0.05
        return COLOR_LOUD.get(color, 0.0)

    def choose_colors(self, body, band, chosen, style=None, pref=None, use_body=True, avoid=(), taste=None, cpref=None):
        """chosen = {부위: (id, item)} → ({부위: 색}, [발동 색 규칙], [색 노트]). avoid = 앞 안들의 {부위: 색} (같은 색 반복을 조금 깎음)"""
        if not self.color:
            return {}, [], []
        lift = self.color["lift"]; parts = [p for p in PARTS if chosen.get(p)]
        cp = cpref or {}; like = set(cp.get("like", ())); no = set(cp.get("avoid", ())); personal = cp.get("personal")
        cand = {p: self.color_choices(p, chosen[p][0], like) for p in parts}
        cand = {p: ([x for x in v if x[0] not in no] or v) for p, v in cand.items()}      # 피하고 싶은 색은 후보에서 먼저 뺀다 (대안이 없을 때만 남김)
        if any(not v for v in cand.values()): return {}, [], []
        pairs = [k for k in ("상의×하의", "아우터×상의", "아우터×하의") if all(q in parts for q in k.split("×"))]
        best = None
        for combo in itertools.product(*[cand[p] for p in parts]):
            col = {p: c for p, (c, _) in zip(parts, combo)}
            s = sum(lp for _, lp in combo); fired = []
            for k in pairs:
                a, b = k.split("×")
                s += 0.7 * math.log(max(lift.get(k, {}).get(f"{col[a]}|{col[b]}", 1.0), 0.05))
            for r in (self.body["color_rules"] if use_body else []):
                if any(body.get(kk) != vv for kk, vv in r["when"].items()): continue
                if r["family"] == "tone_on_tone":
                    if "상의" in col and "하의" in col and col["상의"] == col["하의"]: s += r["weight"]; fired.append(r)
                elif r["part"] in col and self.fam.get(col[r["part"]]) == r["family"]:
                    s += r["weight"]; fired.append(r)
            if "상의" in col and "하의" in col and col["상의"] == col["하의"] and col["상의"] not in TONE_SAME_OK:
                s -= 1.0                                           # 실버·핑크·브라운 위아래 같은 색은 어색 — 톤온톤은 무채색·뉴트럴만 (10/22 점검, 11/11 브라운 제외)
            # 11/11: 튀는 색 / 갈색 쏠림 / 색 충돌
            loud = [0.0 if col[p] in like else self._loud(p, col[p]) for p in parts]    # 좋아한다고 고른 색은 튀어도 감점 안 함
            s -= self.COLOR_LOUD_W * sum(loud)
            if sum(l >= 0.5 for l in loud) > 1: s -= self.ACCENT_W * (sum(l >= 0.5 for l in loud) - 1)
            chroma = {col[p] for p, l in zip(parts, loud) if l >= 0.15}
            if len(chroma) >= 2 and not chroma <= BLUE_FAMILY: s -= self.CLASH_W * (len(chroma) - 1)
            n_earth = sum(col[p] in EARTH for p in parts)
            if n_earth >= 3: s -= 1.5 * self.EARTH_W
            if sum(col[p] == "브라운" for p in parts) >= 2: s -= self.EARTH_W
            pf = band.get("color_prefer")
            if pf:
                for p in parts:
                    if self.fam.get(col[p]) == pf: s += 0.15
            if body.get("sex") == "M" and self.male:
                for p in parts: s += 0.5 * self.male["color_lift"].get(p, {}).get(col[p], 0.0)
            if style and self.style:
                for p in parts: s += 0.5 * self.style_color_lift(style, p, col[p])
            if pref is not None:
                for p in parts: s += 0.5 * pref.color_score(p, col[p])
            if taste:
                for p in parts: s += 0.6 * tpo_rules.taste_color_score(taste, col[p])
            for p in parts:
                if col[p] in like: s += self.LIKE_COLOR_W
                if col[p] in no: s -= self.AVOID_COLOR_PEN
                if personal: s += self.PERSONAL_W * tpo_rules.personal_color_score(personal, p, col[p])
            for prev in avoid:
                s -= self.COLOR_DIV_W * sum(prev.get(p) == col[p] for p in parts)
            if best is None or s > best[0]: best = (s, col, fired)
        return best[1], best[2], []

    # ---------------------------------------------------------------- 신발
    def shoes(self, band, rain, style, sex, top, bottom, outer, avoid=(), tpo=None, taste=None):
        idx = [b["name"] for b in self.weather["bands"]].index(band["name"])
        # 보온 목표 (10/22 촬영 피드백: 체감 9도에 3안 모두 워커 — 실제론 한겨울 전까진 운동화·로퍼를 많이 신음)
        target = {0: 1, 1: 1.5, 2: 2.5, 3: 3, 4: 3, 5: 3, 6: 3.5, 7: 4.5}[idx]
        fam = lambda n: "부츠" if "부츠" in n or n == "워커" else n   # 부츠류는 한 종류로 보고 3안 중복을 피함
        best = None; used_sh1 = False
        fs = [self.formal[p][x[0]] for p, x in (("상의", top), ("하의", bottom), ("아우터", outer)) if x]; mean_f = sum(fs) / len(fs)
        for strict in (True, False):                                  # 선호 스타일(스포티) 제외로 신발이 하나도 안 남으면 그 제외만 푼다
          for sh in self.weather["shoes"]["items"]:
            if rain and sh["name"] in self.weather["rain"]["shoes_exclude"]: continue
            if sex == "M" and sh["name"] in ("펌프스", "플랫 슈즈", "앵클 부츠", "롱 부츠"): continue
            if sh["name"] in tpo_rules.shoes_excluded(tpo): continue   # 운동에 워커·로퍼, 출근에 슬리퍼 등
            if strict and sh["name"] in tpo_rules.taste_shoes_excluded(taste): continue
            s = -abs(sh["warmth"] - target) - self.SHOE_FORMAL_W * abs(SHOE_FORMAL.get(sh["name"], 2.0) - mean_f)   # 11/11: 옷과 신발의 격식 일치
            if style and set(_styles(style)) & set(sh["styles"]): s += 0.6
            if fam(sh["name"]) in {fam(a) for a in avoid}: s -= 0.8   # 3안이 같은 신발만 반복하지 않게
            sh1 = 0.0
            if sex == "F" and self.shoe_stats:
                sh1 = self._shoe_lift(sh["name"], top, bottom, outer)
                s += 0.7 * sh1
            if best is None or s > best[0]: best = (s, sh["name"], sh1)
          if best: break
        return best[1], best[2]

    @staticmethod
    def shoe_color(shoe, colors, band_name):
        """신발 색 (규칙 SC1, 데이터 없음 — 무난한 3색 안에서). 운동화류는 화이트 기본, 가죽·부츠류는 블랙/브라운"""
        warm = {"브라운", "베이지", "카키", "와인", "오렌지", "골드"}
        ref = [colors.get(p) for p in ("하의", "아우터", "상의") if colors.get(p)]
        n_earth = sum(colors.get(p) in EARTH for p in ("상의", "하의", "아우터"))      # 11/11 "전체적으로 갈색": 옷이 이미 갈색계면 신발은 갈색을 피한다
        if shoe in ("스니커즈", "캔버스 스니커즈", "러닝화", "슬리퍼", "샌들"):
            if shoe in ("슬리퍼", "샌들"): return "블랙" if (ref and ref[0] == "블랙") or n_earth >= 2 else "베이지"
            return "블랙" if band_name in ("많이추움", "한파") or (ref and ref[0] == "화이트") else "화이트"
        if n_earth >= 2 or "브라운" in ref: return "블랙"
        return "브라운" if any(c in warm for c in ref[:2]) else "블랙"

    def _shoe_lift(self, shoe, top, bottom, outer):
        L = self.shoe_stats["lift"]; w = {"하의": 1.0, "상의": 0.5, "아우터": 0.5}; tot = wt = 0.0
        for part, it in (("하의", bottom), ("상의", top), ("아우터", outer)):
            if not it: continue
            a = it[1]["attrs"]; ctxs = [f"{part}|{a.get('카테고리')}"]
            if part == "하의":
                ctxs.insert(0, f"하의|{a.get('카테고리')}|핏={a.get('핏')}"); ctxs.insert(1, f"하의|{a.get('카테고리')}|기장={a.get('기장')}")
            for k in ctxs:
                if k in L and shoe in L[k]: tot += w[part] * L[k][shoe]; wt += w[part]; break
        return tot / wt if wt else 0.0

    # ---------------------------------------------------------------- 추천
    def recommend(self, body, weather, n=3, style=None, per_part=(24, 16, 12), pref=None, use_body=True, tpo=None, taste=None, cpref=None):
        """style: 이름 하나 또는 리스트(TPO). use_body=False 는 체형 규칙(아이템·색)을 끈 대조군 — 만족도 A/B 평가용
        tpo: 상황 이름(tpo.TPO) — 주면 그 상황에 안 맞는 아이템·신발을 뺀다 (tpo.EXCLUDE)
        cpref: 개인화 입력 {"like": [좋아하는 색], "avoid": [피하고 싶은 색], "personal": 퍼스널 컬러, "hair": 머리 길이}
        taste: 프로필의 선호 스타일(캐주얼·미니멀·스트릿·스포티·댄디) — tpo.TASTE_PREFER 점수 + 스포티는 일반 의류 제외 (tpo.TASTE_EXCLUDE)"""
        band = self.band(weather["feels_like"]); rain = weather.get("precip_prob", 0) >= self.weather["rain"]["precip_prob"]
        sex = body.get("sex", "F")
        pools = {}
        for part, k in zip(PARTS, per_part):
            cands = []
            for i, it in enumerate(self.items[part]):
                if not self.sex_ok(sex, part, it) or not self.weather_ok(part, it, band, rain): continue
                s, fired, extra = self.item_score(body, part, i, it, band, style, pref, rain, use_body, tpo, taste, cpref)
                if part == "상의" and self._layerable(band, it, tpo): s += self.LAYER_W
                cands.append((s, (i, it), fired, extra))
            fit = [c for c in cands if not tpo_rules.excluded(tpo, part, c[1][1]["attrs"])]
            fit_t = [c for c in fit if not tpo_rules.taste_excluded(taste, part, c[1][1]["attrs"])]
            if taste and len(fit_t) >= 6: cands = fit_t        # 선호 스타일(스포티) 제외 — 후보가 6개 미만이면 풀지 않고 상황 제외만
            elif len(fit) >= n: cands = fit                     # 상황 제외로 후보가 거의 없으면 그 부위만 원래대로
            cands.sort(key=lambda t: -t[0]); pools[part] = cands[:k]
        outers = pools["아우터"] if band["outer"] != "forbid" else []
        outer_opts = outers + ([None] if band["outer"] != "require" else [])
        if not outer_opts: outer_opts = [None]

        raw = []; sport_light = tpo_rules.is_sporty(tpo, taste) and band["name"] == "따뜻" and band["outer"] != "require"
        for (st, top, ft, xt), (sb, bot, fb, xb) in itertools.product(pools["상의"], pools["하의"]):
            for o in outer_opts:
                so, out, fo, xo = o if o else (0.0, None, [], [])
                # 11/11 "코디가 따로 논다": 상의·하의·아우터 격식 차이가 크면(재킷+조거팬츠 등) 감점. 스포티는 아우터 없이 가볍게
                f = [self.formal["상의"][top[0]], self.formal["하의"][bot[0]]] + ([self.formal["아우터"][out[0]]] if out else [])
                pen = self.FORMAL_W * max(0.0, max(f) - min(f) - 1.5) - (self.SPORT_NO_OUTER if sport_light and out is None else 0.0)
                raw.append((st + sb + so - pen, top, bot, out, ft + fb + fo, xt + xb + xo))
        cs_all = self.compat_scores([(t, b, o) for _, t, b, o, _, _ in raw])
        top_cs = max((cs for cs, _ in cs_all), default=0.0)
        sat = lambda cs: -self.COMPAT_CAP * (1 - math.exp((cs - top_cs) / self.COMPAT_CAP))
        combos = [(base + self.COMPAT_W * sat(cs), t, b, o, fired, extra, notes) for (base, t, b, o, fired, extra), (cs, notes) in zip(raw, cs_all)]
        combos.sort(key=lambda c: -c[0])

        # 다양성: 3안이 같은 상의·하의(화면에서 같아 보이는 것 포함)를 공유하지 않게, 아우터도 되도록 겹치지 않게.
        # 10/27: 모양만 다르고 3안이 전부 '니트웨어 + 팬츠' 처럼 같은 종류로 나오던 것 → 같은 카테고리를 다시 쓰면 DIV_W 씩 깎고 고른다 (1안은 그대로)
        picked = []; head = combos[:3000]
        cat = lambda x: x[1]["attrs"].get("카테고리") if x else None
        for strict_outer in (True, False):
            while len(picked) < n:
                best = None
                for c in head:
                    if c in picked or any(_look(c[1]) == _look(p[1]) or _look(c[2]) == _look(p[2]) for p in picked): continue
                    if strict_outer and c[3] and any(p[3] and _look(c[3]) == _look(p[3]) for p in picked): continue
                    adj = c[0] - self.DIV_W * sum((cat(c[1]) == cat(p[1])) + (cat(c[2]) == cat(p[2])) + (bool(c[3]) and cat(c[3]) == cat(p[3])) for p in picked)
                    if best is None or adj > best[0]: best = (adj, c)
                if best is None: break
                picked.append(best[1])
        need = band.get("outer_need_one")                       # 한파: 3안 중 최소 1안은 패딩·코트
        if need and picked and not any(c[3] and c[3][1]["attrs"].get("카테고리") in need for c in picked):
            rest = picked[:-1]
            for c in combos:
                if c[3] and c[3][1]["attrs"].get("카테고리") in need and not any(_look(c[1]) == _look(p[1]) or _look(c[2]) == _look(p[2]) for p in rest):
                    picked = rest + [c]; break

        result = []; used_shoes = []; used_colors = []; used_layers = []
        for sc, top, bot, out, fired, extra, notes in picked:
            chosen = {"상의": top, "하의": bot, "아우터": out}
            colors, cfired, _ = self.choose_colors(body, band, chosen, style, pref, use_body, used_colors, taste, cpref); used_colors.append(colors)
            layer = self.layer(body, band, top, colors, style, pref, rain, use_body, tpo, used_layers, taste, cpref) if self._layerable(band, top[1], tpo) else None
            if layer: used_layers.append(layer[0][0]); colors = {**colors, "레이어": layer[1]}
            shoe, sh1 = self.shoes(band, rain, style, sex, top, bot, out, used_shoes, tpo, taste); used_shoes.append(shoe)
            reasons = [f"체감 {weather['feels_like']:.0f}도({band['name']})라 {band['note']} 위주로 골랐습니다" + (", 비 예보라 물에 약한 소재는 뺐습니다" if rain else "")]
            seen_r = set()
            for r in sorted([r for r in fired if r["weight"] > 0], key=lambda r: -r["weight"]):
                if r["id"] in seen_r: continue
                seen_r.add(r["id"]); reasons.append(r["reason"])
                if len(seen_r) >= 2: break
            ids = {r["id"] for r in fired}
            k1 = [e for e in extra if e[0] == "K1"]
            if k1 and taste:                                   # 선호 스타일이 실제로 점수를 올려 준 아이템만 이유로 (11/11: 이유가 없으면 반영 여부를 알 수 없다는 피드백)
                a = max(k1, key=lambda e: e[1])[2]["attrs"]
                reasons.append(f"선호하신 {taste} 스타일에 맞춰 고른 {_plain_name(a)}"); ids.add("K1")
            if cpref:
                lk = [colors[p] for p in PARTS if colors.get(p) in cpref.get("like", ())]
                if lk: reasons.append(f"좋아하시는 {lk[0]} 색을 반영"); ids.add("L1")
                if cpref.get("personal"):
                    pc = max(((tpo_rules.personal_color_score(cpref["personal"], p, colors[p]), p, colors[p]) for p in PARTS if colors.get(p)), default=None)
                    if pc and pc[0] >= 0.4: reasons.append(f"{cpref['personal']} 톤에 어울리는 {pc[2]} {pc[1]}"); ids.add("PC1")
                h1 = [e for e in extra if e[0] == "H1"]
                if h1 and cpref.get("hair"):
                    reasons.append(f"{cpref['hair']}에 어울리는 {max(h1, key=lambda e: e[1])[2]['attrs'].get('넥라인')} 상의"); ids.add("H1")
            if notes: reasons.append(notes[0] + " (K-Fashion 96만 코디로 학습한 조합 모델)")
            if pref is not None:
                why = pref.explain(top[1], bot[1], out[1] if out else None, colors)
                if why: reasons.append(why); ids.add("P1")
            m1 = [e for e in extra if e[0] == "M1"]
            if m1 and sex == "M":
                a = max(m1, key=lambda e: e[1])[2]["attrs"]
                reasons.append(f"남성 착장 사진에서 특히 자주 보이는 {_plain_name(a)}"); ids.add("M1")
            s1 = [e for e in extra if e[0] == "S1"]
            if s1 and tpo:
                a = max(s1, key=lambda e: e[1])[2]["attrs"]
                reasons.append(f"상황에 맞춰 고른 {_plain_name(a)}"); ids.add("S1")
            if any(e[0] == "T1" for e in extra) and style: reasons.append(f"{'·'.join(dict.fromkeys(_styles(style)))} 스타일에서 자주 입는 아이템"); ids.add("T1")
            if layer:
                reasons.insert(1, f"추운 날이라 {_plain_name(top[1]['attrs'])} 위에 {layer[1]} 니트를 겹쳐 따뜻하면서 단정하게 정돈"); ids.add("Y1")
            if out and any(e[0] == "R1" for e in extra) and out[1]["attrs"].get("카테고리") in self.weather["rain"].get("outer_prefer", []):
                reasons.append(f"비 예보라 젖어도 부담 없는 {out[1]['attrs']['카테고리']}"); ids.add("R1")
            pos_c = [r for r in cfired if r["weight"] > 0]
            if pos_c: reasons.append(sorted(pos_c, key=lambda r: -r["weight"])[0]["reason"])
            ids |= {r["id"] for r in cfired}
            if sh1 >= 0.3: ids.add("SH1")
            reasons = reasons[:6]
            if colors:
                sc_ = self.shoe_color(shoe, colors, band["name"]); no = (cpref or {}).get("avoid", ())
                if sc_ in no: sc_ = next((c for c in ("블랙", "화이트", "그레이", "베이지", "브라운") if c not in no), sc_)
                colors = {**colors, "신발": sc_}
            if colors.get("신발"): ids.add("SC1")
            fo, ft, fb_ = (self._fmt(x, colors.get(p)) for x, p in ((out, "아우터"), (top, "상의"), (bot, "하의")))
            result.append({
                "outer": fo, "top": ft, "bottom": fb_, "shoes": shoe, "score": round(sc, 2), "reason": ". ".join(reasons) + ".",
                "query": [q for q in (self._query(x, colors.get(p)) for x, p in ((out, "아우터"), (top, "상의"), (bot, "하의"))) if q] + ([f"{colors['신발']} {shoe}"] if colors.get("신발") else []),
                "rules": sorted(ids), "colors": colors,
            })
            if layer:
                result[-1]["layer"] = self._fmt(layer[0], layer[1])
                result[-1]["query"].insert(2, self._query(layer[0], layer[1]))
            result[-1]["photo"] = self._photo(top, bot, out, colors, sex, shoe)
            gen = {k: self.gen.get((sex, p, x[0])) or self.gen.get((p, x[0])) for k, p, x in (("outer", "아우터", out), ("top", "상의", top), ("bottom", "하의", bot)) if x}
            if layer: gen["layer"] = self.gen.get((sex, "상의", layer[0][0])) or self.gen.get(("상의", layer[0][0]))
            gen["shoes"] = self.gen.get(("신발", shoe))
            result[-1]["gen"] = {k: v for k, v in gen.items() if v} or None   # AI 생성 형태 컷 (색은 라이트 그레이 — 실제 색은 colors)
        return {"band": band["name"], "rain": rain, "input": {"body": body, "weather": weather}, "outfits": result}

    # ---------------------------------------------------------------- 유사 의상 (11/11 ④ "클릭한 제품과 유사한 의상")
    def similar(self, body, weather, part, item_id, color=None, n=4, style=None, pref=None, tpo=None, taste=None, cpref=None):
        """추천 카드의 옷 한 벌과 비슷한 옷 n 벌 — 같은 카테고리에서 핏·기장·소재·넥라인·소매기장이 같은 만큼 가깝다고 본다
        (날씨·성별·상황·선호 스타일 필터를 그대로 적용, 화면에서 같아 보이는 옷은 뺌). → [{"item": _fmt 결과, "shared": [같은 속성 값], "query": 무신사 검색어, "gen": 형태 컷}]"""
        band = self.band(weather["feels_like"]); rain = weather.get("precip_prob", 0) >= self.weather["rain"]["precip_prob"]; sex = body.get("sex", "F")
        if part not in PARTS or not (0 <= item_id < len(self.items[part])): return []
        base = self.items[part][item_id]; ba = base["attrs"]; no = set((cpref or {}).get("avoid", ())); rows = []
        for i, it in enumerate(self.items[part]):
            a = it["attrs"]
            if i == item_id or a.get("카테고리") != ba.get("카테고리") or not self.sex_ok(sex, part, it) or not self.weather_ok(part, it, band, rain): continue
            if tpo_rules.excluded(tpo, part, a) or tpo_rules.taste_excluded(taste, part, a) or _look((i, it)) == _look((item_id, base)): continue
            shared = [k for k in self.SIM_W if k != "카테고리" and ba.get(k) and ba.get(k) == a.get(k)]
            sim = self.SIM_W["카테고리"] + sum(self.SIM_W[k] for k in shared)
            s = self.item_score(body, part, i, it, band, style, pref, rain, True, tpo, taste, cpref)[0]
            rows.append((sim + 0.25 * s, i, it, shared))
        rows.sort(key=lambda r: -r[0]); out, seen = [], set()
        for _, i, it, shared in rows:
            lk = _look((i, it))
            if lk in seen: continue
            seen.add(lk)
            ch = [c for c, _ in self.color_choices(part, i) if c not in no]
            c = color if color and color not in no else (ch[0] if ch else None)
            out.append({"item": self._fmt((i, it), c), "shared": [(k, it["attrs"][k]) for k in shared], "query": self._query((i, it), c),
                        "gen": self.gen.get((sex, part, i)) or self.gen.get((part, i))})
            if len(out) == n: break
        return out

    # ---------------------------------------------------------------- 레이어드 (10/27)
    # 추운 날(체감 12도 미만) 셔츠·블라우스 코디는 그대로면 코트 하나로 버티는 얇은 차림이라, 조합 모델이 '코트+터틀넥'을 늘 1안으로 골랐다.
    # → 출근·데이트·약속처럼 차려입는 상황에서 셔츠 위에 니트를 한 겹 더 입히고(화면에 상의 2장), 그런 셔츠 코디에 LAYER_W 를 더한다.
    #   LAYER_W 0 / 0.3 / 0.5 → 차려입는 상황 1안이 셔츠·블라우스 6 / 6 / 9 (18개 중). 0.8 은 거의 전부 셔츠라 다양성이 깨짐
    def _layerable(self, band, it, tpo):
        return band["name"] in LAYER_BANDS and it["attrs"].get("카테고리") in LAYER_TOPS and (tpo is None or tpo in LAYER_TPO)

    def layer(self, body, band, top, colors, style=None, pref=None, rain=False, use_body=True, tpo=None, avoid=(), taste=None, cpref=None):
        """셔츠 위에 겹칠 니트 ((id, item), 색) — 터틀넥·크롭은 셔츠 칼라·기장과 안 맞아 뺀다"""
        sex = body.get("sex", "F"); best = None
        for i, it in enumerate(self.items["상의"]):
            a = it["attrs"]
            if a.get("카테고리") != "니트웨어" or a.get("넥라인") in ("터틀넥", "오프숄더", "스퀘어넥") or a.get("기장") == "크롭" or i in avoid: continue
            if a.get("소매기장") not in (None, "긴팔") or not self.sex_ok(sex, "상의", it) or not self.weather_ok("상의", it, band, rain): continue
            sc = self.item_score(body, "상의", i, it, band, style, pref, rain, use_body, tpo, taste, cpref)[0] + (0.5 if a.get("넥라인") == "브이넥" else 0.0)
            if best is None or sc > best[0]: best = (sc, (i, it))
        if not best: return None
        lift = (self.color or {}).get("lift", {}); cbest = None
        for c, lp in self.color_choices("상의", best[1][0]) or [(None, 0.0)]:
            if c is None or c == colors.get("상의") or c in (cpref or {}).get("avoid", ()): continue   # 셔츠와 같은 색이면 겹친 게 안 보임
            s = lp + (0.6 if c in TONE_OK else 0.0) - (0.5 if c == colors.get("아우터") else 0.0)
            if colors.get("하의"): s += 0.5 * math.log(max(lift.get("상의×하의", {}).get(f"{c}|{colors['하의']}", 1.0), 0.05))
            if cbest is None or s > cbest[0]: cbest = (s, c)
        return (best[1], cbest[1]) if cbest else None

    # ---------------------------------------------------------------- 표기
    @staticmethod
    def _fmt(x, color=None):
        if not x: return None
        i, it = x; a = {k: v for k, v in it["attrs"].items() if v}
        fit = a.get("핏") if a.get("핏") not in (None, "노멀") else None
        length = a.get("기장") if a.get("기장") in SHOWN_LENGTH else None
        cat = a.get("카테고리")
        if length == "맥시" and cat != "스커트": length = "롱"     # 바지에 '맥시'는 치마 용어 — 롱 와이드 팬츠처럼
        if fit == "벨보텀" and cat == "스커트": fit = "플레어"      # 치마의 '벨보텀' 라벨 = 아래로 퍼지는 플레어
        if length == "미니" and cat in ("팬츠", "청바지", "조거팬츠"): length, cat = None, "반바지"   # '미니 청바지' → '데님 반바지'
        label = " ".join(v for v in (color, fit, length, a.get("넥라인"), a.get("소매기장"), a.get("소재"), cat) if v)
        out = {"id": i, "label": label}
        if color: out["색상"] = color
        return {**out, **a}

    @staticmethod
    def _query(x, color=None):
        if not x: return None
        a = x[1]["attrs"]; fit = a.get("핏"); cat = a.get("카테고리")
        fit_kr = {"노멀": "", "루즈": "루즈핏", "오버사이즈": "오버핏", "타이트": "슬림핏", "스키니": "스키니", "와이드": "와이드", "벨보텀": "부츠컷"}.get(fit, fit or "")
        if fit == "벨보텀" and cat == "스커트": fit_kr = "플레어"
        if a.get("기장") == "미니" and cat in ("팬츠", "청바지", "조거팬츠"): cat = "데님 반바지" if cat == "청바지" else "반바지"
        return " ".join(v for v in (color, fit_kr, a.get("기장") if a.get("기장") in ("롱", "크롭") else "", cat) if v)

    def _photo(self, top, bot, out, colors, sex, shoe):
        try:
            import kfashion_photos as kp
        except Exception:
            return None
        return kp.outfit_photos(self, top, bot, out, colors, sex, shoe) if hasattr(kp, "outfit_photos") else None


# 성별 실루엣 (10/27, "남녀 추천이 비슷비슷") — 남성 코디에 드문 여성복 소재·디테일을 깎는다. 금지(sex_exclude)까진 아니고 점수만.
# K-Fashion 남성 lift(M1)는 남성 사진이 적어 이런 드문 값은 0 근처로 남아 걸러지지 않음 → 손으로 정한 표. 여성은 지금 후보가 이미 여성복 중심이라 비워 둠
SILHOUETTE = {
    "M": {"상의": {"소재": {"시폰": -1.0, "레이스": -1.5, "실크": -0.4, "헤어 니트": -0.6}, "소매기장": {"7부소매": -0.5, "캡": -1.0},
                  "넥라인": {"유넥": -0.8, "스퀘어넥": -1.0, "보트넥": -0.8}},
          "하의": {"핏": {"벨보텀": -1.5, "스키니": -0.3}, "소재": {"니트": -1.0, "시폰": -1.5, "레이스": -1.5, "벨벳": -0.6, "스판덱스": -0.8}, "기장": {"맥시": -0.4}},
          "아우터": {"소재": {"시폰": -1.0, "퍼": -0.4, "헤어 니트": -0.5}, "핏": {"타이트": -0.4}}},
}
# 11/11 색·격식 표 (손으로 정한 값). 튀는 정도 0~2 — 네온·오렌지·옐로우·레드처럼 눈에 확 띄는 색일수록 크다. 무채색·네이비·베이지·브라운·카키는 0
COLOR_LOUD = {"네온": 2.0, "오렌지": 1.2, "옐로우": 1.1, "레드": 1.0, "퍼플": 1.0, "그린": 0.9, "골드": 0.9, "블루": 0.6, "핑크": 0.35,
              "실버": 0.3, "와인": 0.2, "라벤더": 0.2, "민트": 0.2, "스카이블루": 0.15}
BLUE_FAMILY = {"블루", "스카이블루", "네이비"}               # 서로 같은 계열이라 같이 써도 충돌로 안 봄
EARTH = {"브라운", "베이지", "카키"}                          # 갈색계 — 3곳 이상 겹치면 '전체적으로 갈색'
TONE_SAME_OK = {"블랙", "화이트", "그레이", "네이비", "베이지", "카키"}                           # 위아래 같은 색(톤온톤)이 자연스러운 색 — 브라운 위아래는 칙칙해 제외
FORMAL_CAT = {   # 카테고리 격식 0(운동복)~3(정장)
    "상의": {"셔츠": 3.0, "블라우스": 3.0, "니트웨어": 2.5, "티셔츠": 1.0, "탑": 1.0, "후드티": 0.5},
    "하의": {"팬츠": 2.5, "스커트": 2.5, "청바지": 1.5, "조거팬츠": 0.5, "래깅스": 0.5},
    "아우터": {"코트": 3.0, "재킷": 3.0, "가디건": 2.0, "베스트": 2.0, "점퍼": 1.5, "패딩": 1.5, "짚업": 1.0}}
FORMAL_MAT = {"저지": -0.5, "스판덱스": -0.7, "플리스": -0.8, "데님": -0.3, "패딩": -0.2, "울/캐시미어": 0.4, "실크": 0.5, "트위드": 0.5, "시폰": 0.2, "가죽": 0.3}
SHOE_FORMAL = {"펌프스": 3.5, "옥스포드": 3.5, "로퍼": 3.0, "스웨이드 로퍼": 3.0, "첼시 부츠": 3.0, "앵클 부츠": 2.5, "롱 부츠": 2.5, "플랫 슈즈": 2.5,
               "워커": 1.5, "샌들": 1.5, "스니커즈": 1.0, "캔버스 스니커즈": 1.0, "슬리퍼": 0.5, "러닝화": 0.0}


def formality(part, a):
    """아이템 격식 (카테고리 기본값 + 소재 보정)"""
    return FORMAL_CAT[part].get(a.get("카테고리"), 2.0) + FORMAL_MAT.get(a.get("소재"), 0.0)


LAYER_BANDS = ("추움", "많이추움", "한파")                    # 체감 12도 미만
LAYER_TOPS = ("셔츠", "블라우스")
LAYER_TPO = ("출근·면접", "데이트", "친구 약속·나들이")
TONE_OK = {"블랙", "화이트", "그레이", "네이비", "베이지", "브라운", "카키"}   # 위아래 같은 색이어도 자연스러운 색
SHOWN_LENGTH = ("롱", "크롭", "미니", "미디", "맥시", "하프")   # 이름에 나오는 기장 (발목·노멀은 안 나옴)
BARE_COLD = ("많이추움", "한파")                              # 체감 9도 미만
COLD_FOR_SHORTS = ("선선", "쌀쌀", "추움", "많이추움", "한파")


def _look(x):
    """화면에서 같아 보이는지 — 기본값 라벨(노멀·우븐·없음)을 같게 본 속성 묶음. 색은 나중에 정해져 빼고 본다"""
    if not x: return None
    a = x[1]["attrs"]; d = lambda v, base: None if v in base else v
    return (a.get("카테고리"), d(a.get("핏"), (None, "노멀")), a.get("기장") if a.get("기장") in SHOWN_LENGTH else None, a.get("넥라인"), a.get("소매기장"), d(a.get("소재"), (None, "우븐")))


def _plain_name(a):
    """'코듀로이 팬츠'·'셔츠' 처럼 짧은 이름 (우븐은 정보가 없어 뺌)"""
    return " ".join(v for v in (a.get("소재") if a.get("소재") not in (None, "우븐") else None, a.get("카테고리")) if v)


def _styles(style):
    return [style] if isinstance(style, str) else list(style or [])


def _transform(vocab, rows):
    from scipy import sparse
    ri, ci = [], []
    for i, r in enumerate(rows):
        for f in r:
            j = vocab.get(f)
            if j is not None: ri.append(i); ci.append(j)
    return sparse.csr_matrix((np.ones(len(ri), dtype=np.float32), (ri, ci)), shape=(len(rows), len(vocab)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sex", default="M", choices=["M", "F"]); ap.add_argument("--group", default="균형", choices=["상체형", "균형", "하체형"])
    ap.add_argument("--build", default="보통", choices=["마름", "보통", "통통"]); ap.add_argument("--leg", default="보통", choices=["롱", "보통", "숏"])
    ap.add_argument("--feels", type=float, default=12); ap.add_argument("--precip", type=int, default=10)
    ap.add_argument("--style", default=None); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = RuleEngine().recommend({"sex": a.sex, "group": a.group, "build": a.build, "leg": a.leg}, {"feels_like": a.feels, "precip_prob": a.precip}, style=a.style)
    if a.json: print(json.dumps(r, ensure_ascii=False, indent=1)); return
    print(f"체감 {a.feels:.0f}° → {r['band']}" + (" · 비" if r["rain"] else ""))
    for k, o in enumerate(r["outfits"], 1):
        print(f"\n[{k}] 점수 {o['score']}  규칙 {','.join(o['rules'])}")
        for tag, key in (("아우터", "outer"), ("상의", "top"), ("하의", "bottom")):
            if o[key]: print(f"  {tag}: {o[key]['label']}")
        print(f"  신발: {o['shoes']}\n  검색어: {' / '.join(o['query'])}\n  이유: {o['reason']}")


if __name__ == "__main__":
    main()
