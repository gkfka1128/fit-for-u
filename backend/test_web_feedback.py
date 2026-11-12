"""React 용 👍👎(/web/feedback) · 화면용 이유(why) 테스트. .\\.venv\\Scripts\\python.exe test_web_feedback.py"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_server as a
import ffu_web_bridge as w

ok = fail = 0


def check(name, cond):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    if not cond: print("FAIL", name)


PROF = {"gender": "남성", "height": 175, "weight": 70, "style": "캐주얼", "fit": "레귤러핏"}
WX = {"feels_like": 14, "precip_prob": 10}
r = w.recommend_for_web(PROF, "역삼각형", WX, "학교")
o = r["outfits"][0]

# 화면용 이유
kinds = [x["kind"] for x in o["why"]]
check("이유 종류가 정해진 다섯 가지", set(kinds) <= {"체형", "날씨", "취향", "상황", "데이터"})
check("체형·날씨·상황·취향 이유가 다 있음", {"체형", "날씨", "상황", "취향"} <= set(kinds))
check("이유 순서 체형→날씨→취향→상황→데이터", kinds == sorted(kinds, key=["체형", "날씨", "취향", "상황", "데이터"].index))
check("이유에 딱딱한 표현 없음", not any(s in x["text"] for x in o["why"] for s in ("습니다", "조합 모델", "뺌")))
check("이름에 노말·우븐 없음", w._plain("루즈 노말 우븐 점퍼") == "루즈 점퍼")
check("이름에 겹치는 단어 없음", w._plain("화이트 니트 니트웨어") == "화이트 니트웨어" and w._plain("블랙 패딩 패딩") == "블랙 패딩")
check("fb 에 부위 라벨", set(o["fb"]) <= {"outer", "top", "bottom"} and all("label" in v for v in o["fb"].values()))

# 👎 반복 → 1안이 바뀜, 👍 → 이유에 반영
pref = None
for _ in range(3):
    pref = w.apply_feedback(pref, o["fb"], False)
r2 = w.recommend_for_web(PROF, "역삼각형", WX, "학교", pref=pref)
check("👎 3번 → 1안 상의·하의가 바뀜", [c["name"] for c in r2["outfits"][0]["items"]] != [c["name"] for c in o["items"]])
check("👎 기록 3개", len(pref["history"]) == 3 and not any(h[0] for h in pref["history"]))
good = w.apply_feedback(w.apply_feedback(None, o["fb"], True), o["fb"], True)
r3 = w.recommend_for_web(PROF, "역삼각형", WX, "학교", pref=good)
check("👍 2번 → 취향 이유에 '좋아하셨어요'", any("좋아하셨어요" in x["text"] for x in r3["outfits"][0]["why"] if x["kind"] == "취향"))
check("summary 반환", good["summary"] and all(len(t) == 3 for t in good["summary"]))

# 이상한 취향 값은 버림
c = w.clean_pref({"weights": {"상의|핏|루즈": 9, "가방|x|y": 1, "하의|핏": 1, "하의|핏|와이드": "1", "아우터|핏|롱": float("nan"), 5: 1},
                  "history": [[True, "a"]] * 50 + ["bad"]})
check("가중치 상한 ±1.5", c["weights"] == {"상의|핏|루즈": 1.5})
check("기록은 최근 30개", len(c["history"]) == 30)
check("pref 아닌 값 → 빈 취향", w.clean_pref("x") == {"weights": {}, "history": []})

# API
code, body = a.web_feedback({"outfit": o["fb"], "like": True})
check("POST /web/feedback ok", code == 200 and body["weights"] and body["status"] == "ok")
for bad in ({"outfit": o["fb"]}, {"outfit": {"shoes": {"label": "x"}}, "like": True}, {"outfit": {"top": {"핏": "루즈"}}, "like": True},
            {"outfit": [], "like": False}, {"outfit": {}, "like": True}):
    try:
        a.web_feedback(bad); check(f"잘못된 피드백 거부 {bad}", False)
    except a.BadRequest:
        check("잘못된 피드백 거부", True)
code, body = a.web_recommend({"profile": PROF, "body_type": "역삼각형", "weather": WX, "situation": "학교", "pref": pref})
check("POST /web/recommend 가 pref 반영", [c["name"] for c in body["outfits"][0]["items"]] == [c["name"] for c in r2["outfits"][0]["items"]])
print(f"{ok} ok, {fail} fail"); sys.exit(1 if fail else 0)
