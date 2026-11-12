"""
👍👎 개인화 (로드맵 8번, 9/21) — 추천마다 좋아요/싫어요를 받아 속성별 취향 가중치를 쌓고 다음 추천에 반영한다.

  원리: 코디 한 벌의 아이템 속성(카테고리·핏·기장·넥라인·소재·색)마다 +0.3(👍) / −0.3(👎). 같은 속성이 반복되면 누적(±1.5 상한).
       아이템 점수에 0.8·Σ(속성 가중치), 색 후보에 0.5·색 가중치 → 규칙·통계 위에 얹히는 부드러운 편향 (하드 필터 아님).
  설명: 이유 문장에 "지난번에 와이드 팬츠를 좋아하셨어요" 처럼 가장 크게 기여한 속성 하나 (규칙 id P1).
  저장: to_json()/from_json() — 데모는 세션에, 서비스는 Backend 사용자 DB 에.
  저관여 원칙과의 관계: 👍👎 는 강제 입력이 아니라 선택. 안 누르면 아무 영향 없음.

  pref = Preference(); pref.feedback(outfit_json, like=True); RuleEngine().recommend(body, weather, pref=pref)
"""
import json, os, re

PREF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prefs")

ATTRS = {"상의": ("카테고리", "핏", "기장", "넥라인", "소매기장", "소재"), "하의": ("카테고리", "핏", "기장", "소재"), "아우터": ("카테고리", "핏", "기장", "소재")}
STEP, CLAMP = 0.3, 1.5
PART_KEY = {"상의": "top", "하의": "bottom", "아우터": "outer"}
KR = {"카테고리": "", "핏": "핏", "기장": "기장", "넥라인": "", "소매기장": "", "소재": "소재", "색상": ""}

class Preference:
    def __init__(self, weights=None, history=None):
        self.w = dict(weights or {})          # "부위|속성|값" → 가중치
        self.history = list(history or [])    # [(like, 라벨 요약)]

    # ---- 피드백
    def feedback(self, outfit, like):
        sign = STEP if like else -STEP
        for part, key in PART_KEY.items():
            it = outfit.get(key)
            if not it: continue
            for a in ATTRS[part] + ("색상",):
                v = it.get(a)
                if v: self._bump(f"{part}|{a}|{v}", sign)
        self.history.append((bool(like), " / ".join(outfit[k]["label"] for k in ("outer", "top", "bottom") if outfit.get(k))))

    def _bump(self, k, d):
        self.w[k] = max(-CLAMP, min(CLAMP, self.w.get(k, 0.0) + d))
        if abs(self.w[k]) < 1e-9: del self.w[k]

    # ---- 점수
    def score(self, part, item):
        """아이템(rule_engine items 원소: {"attrs":…}) 의 속성 가중치 합 (±1.5)"""
        a = item["attrs"]; s = sum(self.w.get(f"{part}|{k}|{a.get(k)}", 0.0) for k in ATTRS[part] if a.get(k))
        return max(-CLAMP, min(CLAMP, s))

    def color_score(self, part, color):
        return self.w.get(f"{part}|색상|{color}", 0.0)

    def explain(self, top, bot, out, colors=None):
        """가장 크게 기여한 속성 하나로 문장. 없으면 None"""
        best = None
        for part, it in (("상의", top), ("하의", bot), ("아우터", out)):
            if not it: continue
            for k in ATTRS[part]:
                v = it["attrs"].get(k)
                if not v: continue
                wv = self.w.get(f"{part}|{k}|{v}", 0.0)
                if wv > 0 and (best is None or wv > best[0]): best = (wv, part, k, v)
            if colors and colors.get(part):
                wv = self.color_score(part, colors[part])
                if wv > 0 and (best is None or wv > best[0]): best = (wv, part, "색상", colors[part])
        if not best: return None
        _, part, k, v = best
        return f"지난번에 {v}{(' ' + KR[k]) if KR.get(k) else ''} {part}를 좋아하셨어요" if k != "카테고리" else f"지난번에 {v}를 좋아하셨어요"

    # ---- 저장
    def to_json(self): return json.dumps({"weights": self.w, "history": self.history}, ensure_ascii=False)
    @classmethod
    def from_json(cls, s):
        d = json.loads(s) if s else {}; return cls(d.get("weights"), d.get("history"))
    def summary(self, n=8):
        """취향 메모 (화면용): 가중치 큰 순"""
        rows = sorted(self.w.items(), key=lambda kv: -abs(kv[1]))[:n]
        return [(k.split("|")[0], k.split("|")[2], round(v, 2)) for k, v in rows]


# ---- 사용자별 저장 (데모·API 공용). 서비스에선 Backend 사용자 DB 로 대체
def _pref_path(user_id):
    uid = re.sub(r"[^0-9A-Za-z가-힣_-]", "", str(user_id or ""))[:40]
    return os.path.join(PREF_DIR, uid + ".json") if uid else None


def load_user(user_id):
    p = _pref_path(user_id)
    if p and os.path.exists(p):
        with open(p, encoding="utf-8") as f: return Preference.from_json(f.read())
    return Preference()


def save_user(user_id, pref):
    p = _pref_path(user_id)
    if not p: return False
    os.makedirs(PREF_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f: f.write(pref.to_json())
    return True
