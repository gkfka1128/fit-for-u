"""api_server 테스트 — 실제 HTTP 서버를 임시 포트로 띄워 호출. .\\.venv\\Scripts\\python.exe test_api_server.py"""
import json, os, sys, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import api_server, members
from rule_engine import RuleEngine

api_server.ENGINE = RuleEngine()
api_server.MEMBERS = members.Members(":memory:")
srv = ThreadingHTTPServer(("127.0.0.1", 0), api_server.Handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"
ok = fail = 0


def call(path, body=None, tok=None, origin=None, raw_headers=False):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = f"Bearer {tok}"
    if origin: h["Origin"] = origin
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(req) as r: return (r.status, r.read(), r.headers) if raw_headers else (r.status, r.read(), r.headers.get("Content-Type"))
    except urllib.error.HTTPError as e:
        return (e.code, e.read(), e.headers) if raw_headers else (e.code, e.read(), e.headers.get("Content-Type"))


def j(path, body=None, tok=None):
    c, b, _ = call(path, body, tok)
    return c, json.loads(b)


def check(name, cond):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    if not cond: print("FAIL", name)


W = {"feels_like": 12, "precip_prob": 10}
c, b, _ = call("/health"); check("health", c == 200 and json.loads(b)["ok"])
c, b, _ = call("/meta"); m = json.loads(b); check("meta tpo", c == 200 and "출근·면접" in m["tpo"] and len(m["bands"]) == 8)

c, b, _ = call("/recommend", {"body": {"sex": "M", "group": "상체형", "build": "보통"}, "weather": W}); r = json.loads(b)
check("body 3안", c == 200 and len(r["outfits"]) == 3 and r["band"] == "쌀쌀")
check("신발 색", all(o["colors"].get("신발") for o in r["outfits"]))

c, b, _ = call("/recommend", {"user": {"sex": "F", "height_cm": 162, "weight_kg": 50, "answer": "하체"}, "weather": W}); r = json.loads(b)
check("user → 하체형·보통", c == 200 and r["body_input"]["group"] == "하체형" and r["body_input"]["build"] == "보통")

c, b, _ = call("/recommend", {"user": {"sex": "F", "height_cm": 162, "weight_kg": 50}, "weather": W, "tpo": "출근·면접"}); r = json.loads(b)
check("tpo", c == 200 and r["input"] and any("T1" in o["rules"] for o in r["outfits"]))

fp = json.load(open(os.path.join(HERE, "contracts", "front_v1", "front_profile.example_M.json"), encoding="utf-8"))
c, b, _ = call("/recommend", {"front_profile": fp, "user": {"height_cm": 175, "weight_kg": 70}, "weather": W}); r = json.loads(b)
check("front_profile", c == 200 and r["body_input"]["sex"] == "M")
fr = json.load(open(os.path.join(HERE, "contracts", "front_v1", "front_profile.example_retake.json"), encoding="utf-8"))
c, b, _ = call("/recommend", {"front_profile": fr, "weather": W}); check("front retake 422", c == 422 and json.loads(b)["status"] == "retake_required")

for bad in ({"weather": W}, {"body": {"sex": "X"}, "weather": W}, {"body": {"sex": "M"}}, {"body": {"sex": "M"}, "weather": {"feels_like": 99}},
            {"body": {"sex": "M"}, "weather": W, "style": "없는스타일"}, {"body": {"sex": "M"}, "weather": W, "tpo": "우주"},
            {"user": {"sex": "F", "height_cm": 400, "weight_kg": 50}, "weather": W}):
    c, b, _ = call("/recommend", bad); check(f"400 {bad}", c == 400 and "error" in json.loads(b))
c, b, _ = call("/recommend", [1, 2]); check("non-object 400", c == 400)
c, b, _ = call("/nope", {}); check("404", c == 404)

uid = "_test_api_user"
c, b, _ = call("/recommend", {"body": {"sex": "F"}, "weather": W}); o = json.loads(b)["outfits"][0]
c, b, _ = call("/feedback", {"user_id": uid, "outfit": o, "like": True}); check("feedback", c == 200 and json.loads(b)["ok"])
c, b, _ = call("/recommend", {"body": {"sex": "F"}, "weather": W, "user_id": uid}); r = json.loads(b)
check("취향 반영", c == 200 and any("P1" in x["rules"] for x in r["outfits"]))
c, b, _ = call("/feedback", {"user_id": "../../x", "outfit": o, "like": True}); check("user_id 정리", c == 200)
for f in (uid, "x"):
    p = os.path.join(HERE, "data", "prefs", f + ".json")
    if os.path.exists(p): os.remove(p)

gen = o.get("gen") or {}
if gen.get("top"):
    c, b, t = call(f"/image?path={gen['top']}&color=%EB%84%A4%EC%9D%B4%EB%B9%84"); check("image png", c == 200 and t == "image/png" and b[:4] == b"\x89PNG")
for p in ("../app.py", "data/gen_items/../../app.py", "C:/Windows/win.ini", "data/gen_items/manifest.json"):
    c, b, _ = call(f"/image?path={p}"); check(f"image 경로 차단 {p}", c == 400)

# ---- CORS: 허용 출처만 되돌려 준다
_, _, h = call("/health", origin="http://localhost:5173", raw_headers=True); check("CORS 허용 출처", h.get("Access-Control-Allow-Origin") == "http://localhost:5173")
_, _, h = call("/health", origin="https://evil.example", raw_headers=True); check("CORS 다른 출처 거부", h.get("Access-Control-Allow-Origin") is None)

# ---- 회원
P = {"name": "홍길동", "email": "a@b.c", "phone": "", "gender": "여성", "height": 162, "weight": 50, "style": "미니멀", "fit": "레귤러핏"}
c, d = j("/me"); check("로그인 없이 /me 401", c == 401)
c, d = j("/saved", {"snap": {}}); check("로그인 없이 저장 401", c == 401)
c, d = j("/auth/signup", {"id": "kim_01", "pw": "short", "profile": P}); check("짧은 비밀번호 400", c == 400)
c, d = j("/auth/signup", {"id": "a b", "pw": "longenough1", "profile": P}); check("아이디 형식 400", c == 400)
c, d = j("/auth/signup", {"id": "kim_01", "pw": "longenough1", "profile": {**P, "height": 999}}); check("프로필 검사 400", c == 400)
c, d = j("/auth/signup", {"id": "kim_01", "pw": "longenough1", "profile": P}); check("가입", c == 200)
c, d = j("/auth/signup", {"id": "kim_01", "pw": "longenough1", "profile": P}); check("중복 아이디 400", c == 400)
row = api_server.MEMBERS._q("SELECT pw FROM users WHERE id='kim_01'", one=True)["pw"]
check("비밀번호는 솔트 해시로만", row.startswith("pbkdf2$") and "longenough1" not in row)
c, d = j("/auth/login", {"id": "kim_01", "pw": "wrong-password"}); check("틀린 비밀번호 401", c == 401)
c, d = j("/auth/login", {"id": "kim_01", "pw": "longenough1"}); tok = d.get("token"); check("로그인 → 토큰", c == 200 and tok and d["user"]["name"] == "홍길동")
check("DB 에는 토큰 원문 없음", not api_server.MEMBERS._q("SELECT 1 FROM sessions WHERE token=?", (tok,), one=True))
c, d = j("/auth/login", {"id": "test", "pw": "1234"}); check("시연 계정 test/1234", c == 200 and d["token"])
c, d = j("/me", tok=tok); check("/me", c == 200 and d["user"]["id"] == "kim_01" and "pw" not in d["user"])
c, d = j("/me", {"profile": {**P, "weight": 52}}, tok); check("프로필 수정", c == 200 and d["user"]["weight"] == 52)

c, r = j("/web/recommend", {"profile": P, "situation": "학교", "weather": W})
snap = {"outfit": r["outfits"][0], "situation": "학교", "style": "미니멀", "fit": "레귤러핏", "body": "균형", "feels_like": 12, "precip_prob": 10}
c, d = j("/saved", {"snap": snap}, tok); check("코디 저장", c == 200 and len(d["saved"]) == 1)
c, d = j("/saved", {"snap": snap}, tok); check("같은 코디 두 번 저장 안 됨", len(d["saved"]) == 1)
bad = json.loads(json.dumps(snap)); bad["outfit"]["items"][0]["image"] = "https://evil.example/x.png"
check("외부 이미지 주소는 지움", members.clean_snap(bad)["outfit"]["items"][0]["image"] is None
      and (not os.path.isdir(os.path.join(HERE, "data", "gen_items"))      # 생성 이미지는 git 제외 — 없으면 image=None
           or members.clean_snap(snap)["outfit"]["items"][0]["image"].startswith("/image?path=data/gen_items/")))
sid = d["saved"][0]["id"]
c, d = j("/saved", tok=tok); check("저장 목록", c == 200 and len(d["saved"]) >= 1)
c, t2 = j("/auth/login", {"id": "test", "pw": "1234"})
c, d = j("/saved/delete", {"id": sid}, t2["token"]); c, d = j("/saved", tok=tok); check("남의 코디는 못 지움", any(s["id"] == sid for s in d["saved"]))
c, d = j("/saved/delete", {"id": sid}, tok); check("내 코디 삭제", all(s["id"] != sid for s in d["saved"]))

c, fb = j("/web/feedback", {"outfit": r["outfits"][0]["fb"], "like": True})
c, d = j("/prefs", {"pref": {"weights": fb["weights"], "history": fb["history"]}}, tok); check("취향 저장", c == 200 and d["pref"]["weights"])
c, d = j("/prefs", tok=tok); check("취향 불러오기", d["pref"] and d["pref"]["history"])
c, d = j("/prefs", {"pref": None}, tok); check("취향 초기화", d["pref"] is None)

# 11/11 ④ 개인화 입력 · 유사 의상
PP = {**P, "like_colors": ["핑크"], "avoid_colors": ["브라운", "베이지"], "personal_color": "여름쿨", "hair": "긴 머리"}
c, d = j("/me", {"profile": PP}, tok); check("개인화 선택 정보 저장", c == 200 and d["user"]["like_colors"] == ["핑크"] and d["user"]["avoid_colors"] == ["브라운", "베이지"] and d["user"]["personal_color"] == "여름쿨" and d["user"]["hair"] == "긴 머리")
c, d = j("/me", {"profile": {**PP, "like_colors": ["브라운"]}}, tok); check("좋아하는 색과 피하는 색 겹치면 400", c == 400)
c, d = j("/me", {"profile": {**PP, "like_colors": ["형광"]}}, tok); check("없는 색 이름 400", c == 400)
c, d = j("/me", {"profile": {**PP, "personal_color": "무지개"}}, tok); check("퍼스널 컬러 값 검사 400", c == 400)
c, d = j("/me", {"profile": {**PP, "hair": "대머리"}}, tok); check("머리 길이 값 검사 400", c == 400)
c, d = j("/me", {"profile": P}, tok); check("선택 정보 없이도 저장 (빈 값)", c == 200 and d["user"]["like_colors"] == [] and d["user"]["personal_color"] == "")
c, rp = j("/web/recommend", {"profile": PP, "situation": "데이트", "weather": W})
check("피하고 싶은 색은 코디에 없음", c == 200 and not any(it.get("color") in ("브라운", "베이지") for o in rp["outfits"] for it in o["items"]))
o0 = rp["outfits"][0]; tb = o0["fb"]["top"]
c, sm = j("/web/similar", {"profile": PP, "situation": "데이트", "weather": W, "key": "top", "item_id": tb["id"], "color": tb.get("색상")})
check("유사 의상 4벌", c == 200 and 1 <= len(sm["items"]) <= 4 and sm["part"] == "상의")
check("유사 의상: 기준 옷과 이름이 다름 · 무신사 링크 · 같은 속성 설명", all(i["name"] != sm["base"] and i["link"].startswith("https://www.musinsa.com/search/goods?keyword=") and i["shared"] is not None for i in sm["items"]))
check("유사 의상: 이미지는 /image URL 이거나 없음", all(i["image"] is None or i["image"].startswith("/image?path=data/gen_items/") for i in sm["items"]))
check("유사 의상: 피하는 색은 없음", not any(i["color"] in ("브라운", "베이지") for i in sm["items"]))
c, d = j("/web/similar", {"profile": PP, "situation": "데이트", "weather": W, "key": "shoes", "item_id": 0}); check("유사 의상: 지원 안 하는 부위 400", c == 400)
c, d = j("/web/similar", {"profile": PP, "situation": "데이트", "weather": W, "key": "top", "item_id": 99999}); check("유사 의상: 범위 밖 id 400", c == 400)
c, d = j("/web/similar", {"profile": PP, "situation": "데이트", "key": "top", "item_id": 1}); check("유사 의상: 날씨 없으면 400", c == 400)

c, d = j("/reviews", {"stars": 6, "text": "x"}, tok); check("별점 범위 400", c == 400)
c, d = j("/reviews", {"stars": 5, "text": "좋아요"}, tok); check("후기", c == 200 and d["reviews"][0]["user"] == "홍길동")
c, d = j("/qna", {"title": "질문", "content": "내용"}, tok); qid = d["qna"][0]["id"]; check("Q&A", c == 200 and d["qna"][0]["username"] == "kim_01")
c, d = j("/qna/delete", {"id": qid}, t2["token"]); check("남의 질문은 못 지움", any(q["id"] == qid for q in d["qna"]))
c, d = j("/qna/delete", {"id": qid}, tok); check("내 질문 삭제", all(q["id"] != qid for q in d["qna"]))

c, d = j("/auth/logout", {}, tok); c, d = j("/me", tok=tok); check("로그아웃 후 토큰 무효", c == 401)
for _ in range(5): j("/auth/login", {"id": "kim_01", "pw": "nope"})
c, d = j("/auth/login", {"id": "kim_01", "pw": "longenough1"}); check("로그인 실패 5번 → 429", c == 429)

# ---- 평가 참여
tok = t2["token"]
c, d = j("/study/start", {"consent": False, "profile": {}}, tok); check("동의 없으면 400", c == 400)
c, d = j("/study/start", {"consent": True, "profile": {"sex": "M", "age": "20대", "height": 175, "weight": 70, "answer": "상체"}}); check("평가도 로그인 필요", c == 401)
c, d = j("/study/start", {"consent": True, "profile": {"sex": "M", "age": "20대", "height": 175, "weight": 70, "answer": "상체"},
                          "tape": {"chest": 96, "waist": 80, "hip": 95}}, tok)
pid = d.get("pid"); check("참가 시작 → 익명 번호", c == 200 and pid and pid.startswith("P"))
c, d = j("/study/tape", {"pid": pid, "tape": {"chest": 300}}, tok); check("실측 범위 400", c == 400)
c, d = j("/study/tape", {"pid": pid, "tape": {"chest": 97, "waist": 81, "hip": 96, "shoulder": 45}}, tok); check("실측 저장", c == 200)
c, d = j("/study/photo", {"pid": pid, "front": "!!"}, tok); check("사진 base64 검사", c == 400)
answered = 0
for rnd, sit in enumerate(("학교", "데이트", "출근"), 1):
    c, d = j("/study/pair", {"pid": pid, "round": rnd, "situation": sit, "weather": W}, tok)
    check(f"A/B {rnd}회차", c == 200 and d["A"] and d["B"] and "a_is_rules" not in json.dumps(d) and all("image" in x for x in d["A"]))
    if not d.get("identical"):
        c2, _ = j("/study/answer", {"pid": pid, "pair_id": d["pair_id"], "choice": "A", "score_a": 4, "score_b": 3}, tok); answered += c2 == 200
c, d = j("/study/answer", {"pid": "PXXXXX", "pair_id": "x", "choice": "A", "score_a": 4, "score_b": 3}, tok); check("남의 pair 400", c == 400)
c, d = j("/study/recommend", {"pid": pid, "situation": "학교", "weather": W}, tok); check("설문용 3안", c == 200 and len(d["outfits"]) == 3)
c, d = j("/study/survey", {"pid": pid, "wear": 4, "shoes": 3, "understand": 5, "negative": False}, tok); check("설문", c == 200)
dump = [x for x in api_server.MEMBERS.study_dump() if x["pid"] == pid][0]
check("분석용 기록", dump["tape"]["shoulder"] == 45 and len(dump["ab"]) == 3 and dump["survey"]["wear"] == 4
      and sum(a["choice"] is not None for a in dump["ab"]) == answered and dump["ab"][0]["meta"]["body"]["group"] == "상체형")

srv.shutdown()
print(f"{ok} ok, {fail} fail"); sys.exit(1 if fail else 0)
