"""
회원·저장한 코디·후기·Q&A·취향 + 평가 참여 기록 — SQLite (data/members.db, Git 제외). 표준 라이브러리만.

  비밀번호: PBKDF2-SHA256 20만 회 + 사람마다 다른 솔트.  로그인: 무작위 토큰 (DB 에는 SHA-256 만, 14일 만료).
  로그인 실패가 10분에 5번 넘으면 그 아이디는 잠시 막는다.
  평가 참여(study_*)는 회원과 연결하지 않는 익명 참가자 번호로만 남긴다. 사진은 받지 않고 분석 결과 숫자만.

  ms = Members()                    # 기본 data/members.db, 테스트는 Members(":memory:")
  ms.signup("abc", "pw12345678", {...});  tok = ms.login("abc", "pw12345678");  uid = ms.user_of(tok)

  참가자 기록 삭제 요청:  .\\.venv\\Scripts\\python.exe members.py delete-study P1A2B3C
"""
import hashlib, hmac, json, os, re, secrets, sqlite3, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "members.db")
ITER = 200_000
TOKEN_DAYS = 14
FAIL_MAX, FAIL_WINDOW = 5, 600

STYLES = ("캐주얼", "미니멀", "스트릿", "스포티", "댄디")
FITS = ("오버핏", "레귤러핏", "슬림핏")
COLORS = ("블랙", "화이트", "그레이", "실버", "네이비", "블루", "스카이블루", "민트", "그린", "카키", "베이지", "브라운",
          "레드", "와인", "핑크", "라벤더", "퍼플", "옐로우", "오렌지", "골드", "네온")
PERSONALS = ("", "봄웜", "여름쿨", "가을웜", "겨울쿨")       # "" = 모름·선택 안 함
HAIRS = ("", "짧은 머리", "단발·중간", "긴 머리")
MAX_COLORS = 5
ID_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
IMG_PREFIX = "/image?path=data/gen_items/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, pw TEXT NOT NULL, profile TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS saved (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, key TEXT NOT NULL, snap TEXT NOT NULL, created REAL NOT NULL,
                                  UNIQUE (user_id, key));
CREATE TABLE IF NOT EXISTS prefs (user_id TEXT PRIMARY KEY, pref TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, name TEXT NOT NULL, stars INTEGER NOT NULL,
                                    text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS qna (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
                                answer TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS study_sessions (pid TEXT PRIMARY KEY, created REAL NOT NULL, profile TEXT NOT NULL, tape TEXT, photo TEXT);
CREATE TABLE IF NOT EXISTS study_pairs (pair_id TEXT PRIMARY KEY, pid TEXT NOT NULL, round INTEGER NOT NULL, a_is_rules INTEGER NOT NULL,
                                        identical INTEGER NOT NULL, meta TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS study_ab (pair_id TEXT PRIMARY KEY, pid TEXT NOT NULL, choice TEXT, score_a INTEGER, score_b INTEGER, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS study_survey (pid TEXT PRIMARY KEY, answers TEXT NOT NULL, created REAL NOT NULL);
"""


class Invalid(ValueError):
    """입력이 잘못됨 → 400"""


class Throttled(Exception):
    """로그인 실패가 너무 많음 → 429"""


def _hash_pw(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    return f"pbkdf2${ITER}${salt.hex()}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, ITER).hex()}"


def _check_pw(pw, stored):
    try:
        _, it, salt, h = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, h)


def _tok_hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def _text(d, k, n, required=False):
    v = d.get(k, "")
    if not isinstance(v, str): raise Invalid(f"{k} 는 문자열이어야 합니다")
    v = v.strip()
    if required and not v: raise Invalid(f"{k} 를 입력해 주세요")
    if len(v) > n: raise Invalid(f"{k} 는 {n}자 이하로 입력해 주세요")
    return v


def _num(d, k, lo, hi):
    v = d.get(k)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi: raise Invalid(f"{k} 는 {lo}~{hi} 사이 숫자여야 합니다")
    return v


def clean_profile(p):
    if not isinstance(p, dict): raise Invalid("profile 이 필요합니다")
    out = {"name": _text(p, "name", 30, True), "email": _text(p, "email", 100, True), "phone": _text(p, "phone", 20),
           "gender": p.get("gender"), "height": _num(p, "height", 120, 220), "weight": _num(p, "weight", 30, 200),
           "style": p.get("style"), "fit": p.get("fit")}
    if "@" not in out["email"]: raise Invalid("이메일 형식을 확인해 주세요")
    if out["gender"] not in ("남성", "여성"): raise Invalid("gender 는 남성/여성")
    if out["style"] not in STYLES: raise Invalid(f"style 은 {STYLES} 중 하나")
    if out["fit"] not in FITS: raise Invalid(f"fit 은 {FITS} 중 하나")
    # 11/11 선택 정보 (없으면 빈 값) — 좋아하는/피하고 싶은 색, 퍼스널 컬러, 머리 길이
    for k in ("like_colors", "avoid_colors"):
        v = p.get(k, [])
        if not isinstance(v, list) or any(c not in COLORS for c in v): raise Invalid(f"{k} 는 색 이름 목록이어야 합니다")
        out[k] = list(dict.fromkeys(v))[:MAX_COLORS]
    if set(out["like_colors"]) & set(out["avoid_colors"]): raise Invalid("좋아하는 색과 피하고 싶은 색에 같은 색을 넣을 수 없어요")
    out["personal_color"] = p.get("personal_color") or ""; out["hair"] = p.get("hair") or ""
    if out["personal_color"] not in PERSONALS: raise Invalid(f"personal_color 는 {PERSONALS} 중 하나")
    if out["hair"] not in HAIRS: raise Invalid(f"hair 는 {HAIRS} 중 하나")
    return out


def clean_snap(s):
    """저장할 코디 스냅샷 — 화면에 다시 그릴 값만 남긴다 (이미지는 우리 /image 경로만)"""
    if not isinstance(s, dict) or not isinstance(s.get("outfit"), dict) or not isinstance(s["outfit"].get("items"), list): raise Invalid("outfit.items 가 필요합니다")
    items = []
    for c in s["outfit"]["items"][:6]:
        if not isinstance(c, dict): raise Invalid("items 형식이 올바르지 않습니다")
        img = c.get("image")
        items.append({k: _text(c, k, 80) for k in ("icon", "category", "name", "desc", "color") if isinstance(c.get(k), str)}
                     | {"image": img if isinstance(img, str) and img.startswith(IMG_PREFIX) and len(img) < 300 else None})
    meta = {k: _text(s, k, 40) for k in ("situation", "style", "fit", "body", "region") if isinstance(s.get(k), str)}
    for k in ("feels_like", "precip_prob"):
        if isinstance(s.get(k), (int, float)) and not isinstance(s[k], bool): meta[k] = s[k]
    return {"outfit": {"items": items}, **meta}


class Members:
    def __init__(self, path=DB_PATH):
        if path != ":memory:": os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()                         # API 서버가 스레드마다 요청을 받으므로 쓰기는 하나씩
        self.fails = {}
        with self.lock, self.db:
            self.db.executescript(SCHEMA)
            if os.environ.get("FFU_NO_DEMO") == "1":     # 외부 공개 테스트: 시연 계정을 만들지 않고, 이미 있으면 그 계정과 딸린 기록을 지운다
                for t in ("sessions", "saved", "prefs", "reviews", "qna"):
                    self.db.execute(f"DELETE FROM {t} WHERE user_id='test'")
                self.db.execute("DELETE FROM users WHERE id='test'")
            elif not self.db.execute("SELECT 1 FROM users WHERE id='test'").fetchone():   # 시연 계정 (민상님 앱과 같은 test / 1234)
                self.db.execute("INSERT INTO users VALUES (?,?,?,?)", ("test", _hash_pw("1234"), json.dumps(
                    {"name": "테스트", "email": "test@example.com", "phone": "", "gender": "남성", "height": 175, "weight": 70,
                     "style": "캐주얼", "fit": "레귤러핏"}, ensure_ascii=False), time.time()))

    def _q(self, sql, args=(), one=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.fetchone() if one else cur.fetchall()

    def _w(self, sql, args=()):
        with self.lock, self.db:
            return self.db.execute(sql, args)

    # ---- 회원
    def signup(self, uid, pw, profile):
        if not isinstance(uid, str) or not ID_RE.match(uid): raise Invalid("아이디는 영문·숫자·_ 3~20자")
        if not isinstance(pw, str) or len(pw) < 8 or len(pw) > 128: raise Invalid("비밀번호는 8자 이상으로 정해 주세요")
        prof = clean_profile(profile)
        try:
            self._w("INSERT INTO users VALUES (?,?,?,?)", (uid, _hash_pw(pw), json.dumps(prof, ensure_ascii=False), time.time()))
        except sqlite3.IntegrityError:
            raise Invalid("이미 사용 중인 아이디입니다")

    def login(self, uid, pw):
        now = time.time()
        recent = [t for t in self.fails.get(uid, []) if now - t < FAIL_WINDOW]
        if len(recent) >= FAIL_MAX: raise Throttled("로그인 시도가 너무 많아요. 10분 뒤에 다시 시도해 주세요.")
        row = self._q("SELECT pw FROM users WHERE id=?", (uid,), one=True) if isinstance(uid, str) else None
        if not row or not isinstance(pw, str) or not _check_pw(pw, row["pw"]):
            if len(self.fails) > 10000: self.fails = {k: v for k, v in self.fails.items() if now - v[-1] < FAIL_WINDOW}
            self.fails[uid if isinstance(uid, str) else ""] = recent + [now]
            return None
        self.fails.pop(uid, None)
        tok = secrets.token_urlsafe(32)
        self._w("DELETE FROM sessions WHERE expires < ?", (now,))
        self._w("INSERT INTO sessions VALUES (?,?,?)", (_tok_hash(tok), uid, now + TOKEN_DAYS * 86400))
        return tok

    def logout(self, tok):
        if tok: self._w("DELETE FROM sessions WHERE token=?", (_tok_hash(tok),))

    def user_of(self, tok):
        if not tok: return None
        row = self._q("SELECT user_id, expires FROM sessions WHERE token=?", (_tok_hash(tok),), one=True)
        return row["user_id"] if row and row["expires"] > time.time() else None

    def get_user(self, uid):
        row = self._q("SELECT profile FROM users WHERE id=?", (uid,), one=True)
        return {"id": uid, **json.loads(row["profile"])} if row else None

    def update_user(self, uid, profile):
        self._w("UPDATE users SET profile=? WHERE id=?", (json.dumps(clean_profile(profile), ensure_ascii=False), uid))
        return self.get_user(uid)

    # ---- 저장한 코디
    def list_saved(self, uid):
        return [{**json.loads(r["snap"]), "id": r["id"], "key": r["key"], "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["created"]))}
                for r in self._q("SELECT * FROM saved WHERE user_id=? ORDER BY id DESC", (uid,))]

    def add_saved(self, uid, snap):
        s = clean_snap(snap)
        key = json.dumps([c.get("name") for c in s["outfit"]["items"]], ensure_ascii=False, separators=(",", ":"))   # 브라우저 JSON.stringify 와 같은 모양
        if self._q("SELECT COUNT(*) n FROM saved WHERE user_id=?", (uid,), one=True)["n"] >= 200: raise Invalid("저장은 200개까지 할 수 있어요")
        self._w("INSERT OR IGNORE INTO saved (user_id, key, snap, created) VALUES (?,?,?,?)", (uid, key, json.dumps(s, ensure_ascii=False), time.time()))

    def delete_saved(self, uid, sid):
        self._w("DELETE FROM saved WHERE user_id=? AND id=?", (uid, sid))

    # ---- 👍👎 취향
    def get_pref(self, uid):
        row = self._q("SELECT pref FROM prefs WHERE user_id=?", (uid,), one=True)
        return json.loads(row["pref"]) if row else None

    def set_pref(self, uid, pref):
        if pref is None: self._w("DELETE FROM prefs WHERE user_id=?", (uid,)); return
        self._w("INSERT INTO prefs VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET pref=excluded.pref", (uid, json.dumps(pref, ensure_ascii=False)))

    # ---- 후기 · Q&A
    def list_reviews(self, limit=100):
        return [{"id": r["id"], "user": r["name"], "stars": r["stars"], "text": r["text"]}
                for r in self._q("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,))]

    def add_review(self, uid, stars, text):
        if not isinstance(stars, int) or isinstance(stars, bool) or not 1 <= stars <= 5: raise Invalid("stars 는 1~5")
        t = _text({"text": text}, "text", 1000, True)
        self._w("INSERT INTO reviews (user_id, name, stars, text, created) VALUES (?,?,?,?,?)", (uid, self.get_user(uid)["name"], stars, t, time.time()))

    def list_qna(self, limit=200):
        return [{"id": r["id"], "username": r["user_id"], "title": r["title"], "content": r["content"], "answer": r["answer"],
                 "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["created"]))}
                for r in self._q("SELECT * FROM qna ORDER BY id DESC LIMIT ?", (limit,))]

    def add_qna(self, uid, title, content):
        d = {"title": title, "content": content}
        self._w("INSERT INTO qna (user_id, title, content, created) VALUES (?,?,?,?)", (uid, _text(d, "title", 100, True), _text(d, "content", 3000, True), time.time()))

    def delete_qna(self, uid, qid):
        self._w("DELETE FROM qna WHERE user_id=? AND id=?", (uid, qid))

    # ---- 평가 참여 (평가 프로토콜 §5) — 익명 참가자 번호만
    def study_start(self, profile, tape=None):
        pid = "P" + secrets.token_hex(3).upper()
        self._w("INSERT INTO study_sessions VALUES (?,?,?,?,NULL)", (pid, time.time(), json.dumps(profile, ensure_ascii=False),
                                                                     json.dumps(tape, ensure_ascii=False) if tape else None))
        return pid

    def study_get(self, pid):
        row = self._q("SELECT * FROM study_sessions WHERE pid=?", (pid,), one=True) if isinstance(pid, str) else None
        if not row: raise Invalid("참가자 번호가 올바르지 않습니다")
        return {"pid": pid, "profile": json.loads(row["profile"]), "tape": json.loads(row["tape"]) if row["tape"] else None,
                "photo": json.loads(row["photo"]) if row["photo"] else None}

    def study_set(self, pid, field, value):
        assert field in ("tape", "photo")
        self._w(f"UPDATE study_sessions SET {field}=? WHERE pid=?", (json.dumps(value, ensure_ascii=False), pid))

    def study_pair(self, pid, rnd, a_is_rules, identical, meta):
        pair_id = secrets.token_hex(8)
        self._w("INSERT INTO study_pairs VALUES (?,?,?,?,?,?,?)", (pair_id, pid, rnd, int(a_is_rules), int(identical), json.dumps(meta, ensure_ascii=False), time.time()))
        return pair_id

    def study_answer(self, pid, pair_id, choice, score_a, score_b):
        row = self._q("SELECT pid FROM study_pairs WHERE pair_id=?", (pair_id,), one=True) if isinstance(pair_id, str) else None
        if not row or row["pid"] != pid: raise Invalid("pair_id 가 올바르지 않습니다")
        self._w("INSERT OR REPLACE INTO study_ab VALUES (?,?,?,?,?,?)", (pair_id, pid, choice, score_a, score_b, time.time()))

    def study_survey(self, pid, answers):
        self.study_get(pid)
        self._w("INSERT OR REPLACE INTO study_survey VALUES (?,?,?)", (pid, json.dumps(answers, ensure_ascii=False), time.time()))

    def study_delete(self, pid):
        """참가자가 기록 삭제를 요청하면 (동의 화면에서 약속) — 그 번호의 모든 기록을 지운다"""
        with self.lock, self.db:
            n = self.db.execute("DELETE FROM study_sessions WHERE pid=?", (pid,)).rowcount
            for t in ("study_pairs", "study_ab", "study_survey"): self.db.execute(f"DELETE FROM {t} WHERE pid=?", (pid,))
        return n

    def study_dump(self):
        """분석용 (eval_study.py) — 참가자별 입력·실측·사진 결과·A/B 회차·설문"""
        out = []
        for s in self._q("SELECT pid FROM study_sessions ORDER BY created"):
            d = self.study_get(s["pid"])
            pairs = self._q("SELECT p.*, a.choice, a.score_a, a.score_b FROM study_pairs p LEFT JOIN study_ab a USING (pair_id) WHERE p.pid=? ORDER BY p.round, p.created", (s["pid"],))
            d["ab"] = [{"round": p["round"], "a_is_rules": bool(p["a_is_rules"]), "identical": bool(p["identical"]), "meta": json.loads(p["meta"]),
                        "choice": p["choice"], "score_a": p["score_a"], "score_b": p["score_b"]} for p in pairs]
            sv = self._q("SELECT answers FROM study_survey WHERE pid=?", (s["pid"],), one=True)
            d["survey"] = json.loads(sv["answers"]) if sv else None
            out.append(d)
        return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "delete-study":
        print(f"{sys.argv[2]}: {'삭제했습니다' if Members().study_delete(sys.argv[2]) else '그 번호의 기록이 없습니다'}")
    else:
        print("사용: python members.py delete-study <참가자 번호>")
