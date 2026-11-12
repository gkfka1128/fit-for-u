"""
웹페이지 연동 사본(../fit-for-u_연동/fit-for-u.py) 스모크 테스트 — Streamlit AppTest 로 추천 화면을 직접 띄워 엔진 결과가 나오는지 확인.
로그인·체형 분석 단계는 세션 값으로 건너뛴다 (시연 계정 test 는 앱이 DB 초기화 때 만드는 계정).
  .\\.venv\\Scripts\\python.exe test_web_bridge.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from streamlit.testing.v1 import AppTest
import ffu_web_bridge as b

APP = os.path.join(HERE, "..", "fit-for-u_연동", "fit-for-u.py")
HAS_APP = os.path.exists(APP)                                          # 팀 저장소에서 받은 경우: 연동 사본 없음 → 앱 화면 검사 건너뜀
HAS_IMG = os.path.isdir(os.path.join(HERE, "data", "gen_items", "m"))  # 생성 이미지(524MB)는 git 제외 → 이미지 검사 건너뜀
if not HAS_APP: print("  skip 앱 화면 검사 (../fit-for-u_연동 없음)")
if not HAS_IMG: print("  skip 이미지 검사 (data/gen_items 없음)")
# 테스트는 실제 .env(사용자 KMA 키)를 읽지 않는다 — 키 없음(수동 입력)·가짜 키 시나리오를 환경변수로만 제어
import types
sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: False)
os.environ.pop("KMA_API_KEY", None)
ok = fail = 0


def check(name, cond):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("  ok  " if cond else "  FAIL ") + name)


def count(node, kind):
    return sum((getattr(ch, "type", None) == kind) + count(ch, kind) for ch in getattr(node, "children", {}).values())


# 변환 함수
check("체감온도 겨울 바람", b.feels_like(5, 60, 6, month=11) < 5)
check("체감온도 여름 습도", b.feels_like(30, 80, 1, month=8) > 30)
check("체형 매핑", b.engine_body({"gender": "여성", "height": 160, "weight": 45}, "삼각형") == {"sex": "F", "group": "하체형", "build": "마름", "leg": "보통"})
check("비 → 강수확률 80", b.engine_weather({"temperature": 15, "precipitation_type": 1})["precip_prob"] == 80)
check("상황+스타일 묶음", b.engine_style({"style": "미니멀"}, "출근", "M") == ["모던", "소피스트케이티드", "클래식"] + ["모던"] * b.PREF_STYLE_REPEAT)   # 선호 스타일은 REPEAT 배로 센다

# 앱 추천 화면
for situation, temp, rain in (("출근", 9.0, False), ("데이트", 27.0, False), ("운동", 14.0, True)) if HAS_APP else ():
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["logged_in"] = True; at.session_state["username"] = "test"
    at.session_state["page"] = "recommend"; at.session_state["analysis_complete"] = True
    at.session_state["situation"] = situation
    at.session_state["manual_temp"] = int(temp); at.session_state["manual_rain"] = rain
    at.run()
    tag = f"{situation} {temp}° {'비' if rain else ''}"
    check(f"{tag}: 예외 없음", not at.exception)
    check(f"{tag}: 엔진 경고 없음", not any("추천 엔진" in w.value for w in at.warning))
    check(f"{tag}: 3안 선택", any(r.options == ["코디 1", "코디 2", "코디 3"] for r in at.radio))
    md = " ".join(m.value for m in at.markdown)
    check(f"{tag}: 엔진 이유 카드", "무신사에서 찾아보기" in md and "체감" in md)
    if HAS_IMG: check(f"{tag}: 이미지 카드", count(at.main, "image") >= 3)
    if temp >= 25: check(f"{tag}: 더운 날 아우터 없음", "OUTER" not in md)
# 실제 키 경로 (기상청 응답은 가짜): 초단기실황 + 단기예보 → 강수확률이 사이드바·엔진에 반영되는지
from datetime import datetime, timedelta
from unittest import mock
import kma_forecast


class _Resp:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


def _fake_get(url, params=None, timeout=None):
    if "getUltraSrtNcst" in url:
        obs = [{"category": c, "obsrValue": v} for c, v in (("T1H", "13"), ("REH", "60"), ("WSD", "2"), ("RN1", "0"), ("PTY", "0"))]
        return _Resp({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": obs}}}})
    now = datetime.now(kma_forecast.KST).replace(minute=0, second=0, microsecond=0)
    items = [{"fcstDate": (now + timedelta(hours=i)).strftime("%Y%m%d"), "fcstTime": (now + timedelta(hours=i)).strftime("%H%M"),
              "category": c, "fcstValue": v} for i in range(14) for c, v in (("POP", "70" if i == 5 else "20"), ("TMP", "15"), ("SKY", "4"))]
    return _Resp({"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}})


os.environ["KMA_API_KEY"] = "FAKE-KEY-FOR-TEST"
if HAS_APP:
    with mock.patch("requests.get", side_effect=_fake_get):
        at = AppTest.from_file(APP, default_timeout=180)
        for k_, v_ in dict(logged_in=True, username="test", page="recommend", analysis_complete=True, situation="학교").items(): at.session_state[k_] = v_
        at.run()
        side = " ".join(m.value for m in at.sidebar.markdown)
        check("실키 경로: 예외 없음", not at.exception)
        check("실키 경로: 사이드바 강수확률 70%", "강수확률 70%" in side and "흐림" in side)
        md = " ".join(m.value for m in at.markdown)
        check("실키 경로: 엔진이 비 반영 (70% ≥ 60)", "비 예보" in md)
del os.environ["KMA_API_KEY"]

# 10/22 전체 점검에서 고친 것 (React 경로 recommend_for_web) — 상황에 안 맞는 아이템·한파 아우터·3안 중복·문구
def web(sex, sit, feels, bt="균형", pop=10):
    prof = {"gender": "여성" if sex == "F" else "남성", "height": 162 if sex == "F" else 175, "weight": 55 if sex == "F" else 68}
    return b.recommend_for_web(prof, bt, {"feels_like": feels, "precip_prob": pop}, sit)["outfits"]
shoe = lambda o: o["items"][-1]["name"].split()[-1] if o["items"][-1]["name"].split()[-1] != "부츠" else o["items"][-1]["name"]
BAD_SPORT = ("워커", "로퍼", "옥스포드", "부츠", "펌프스", "슈즈", "슬리퍼", "샌들")
for sx in "FM":
    for f in (-5, 10, 31):
        sp = web(sx, "운동", f)
        check(f"운동 {sx} {f}도: 구두·부츠·샌들 없음", not any(any(w in o["items"][-1]["name"] for w in BAD_SPORT) for o in sp))
        check(f"운동 {sx} {f}도: 청바지·스커트·코트 없음", not any(o["fb"].get(k, {}).get("카테고리") in ("청바지", "스커트", "코트") for o in sp for k in ("bottom", "outer")))
        wk = web(sx, "출근", f)
        check(f"출근 {sx} {f}도: 슬리퍼·반바지 없음", not any("슬리퍼" in o["items"][-1]["name"] or o["fb"]["bottom"].get("기장") == "미니" for o in wk))
    cold = web(sx, "학교", -5)
    check(f"한파 {sx}: 3안 중 패딩·코트 1개 이상", any(o["fb"].get("outer", {}).get("카테고리") in ("패딩", "코트") for o in cold))
    outs = [o["fb"]["outer"]["id"] for o in web(sx, "학교", 10) if o["fb"].get("outer")]
    check(f"추움 {sx}: 3안 아우터 안 겹침", len(outs) == len(set(outs)))
    names = [c["name"] for o in web(sx, "데이트", 7, "하체형") for c in o["items"] if c["category"] in ("TOP", "BOTTOM")]
    check(f"데이트 {sx}: 3안 상·하의 화면 이름 안 겹침", len(names) == len(set(names)))
    why = " ".join(w["text"] for bt in ("상체형", "하체형") for o in web(sx, "학교", 14, bt) for w in o["why"])
    check(f"{sx}: 부정적 체형 표현 없음", not any(k in why for k in ("넓은 편이라", "발달한 편이라", "마른 편이라", "눌러 보이게")))
check("학교 ≠ 친구와 약속 (다른 상황 묶음)", [o["fb"]["top"]["id"] for o in web("F", "학교", 14)] != [o["fb"]["top"]["id"] for o in web("F", "친구와 약속", 14)])
check("더움: 반팔 아닌 니트 없음", not any(o["fb"]["top"].get("소재") == "니트" and o["fb"]["top"].get("소매기장") not in ("반팔", "민소매", "캡") for sit in ("출근", "학교") for o in web("F", sit, 25)))
check("남성: 미디(7부) 바지 없음", not any(o["fb"]["bottom"].get("기장") == "미디" for f in (14, 25, 31) for sit in ("학교", "출근") for o in web("M", sit, f)))
check("바지 '맥시' 표기 → 롱", not any("맥시" in c["name"] and "스커트" not in c["name"] for f in (14, 21) for o in web("F", "학교", f) for c in o["items"]))
check("남성 이유: 아이템 이름이 들어감", not any(w["text"].endswith("아이템이에요") and "남성분" in w["text"] for o in web("M", "학교", 14) for w in o["why"]))
# 10/27 중간발표 피드백: 상황별 비중 설명 · 결과 비교 (체격만 바꾸면 추천이 달라지는지)
sm = b.situation_summary("운동", "M")
check("상황 설명: 운동 → 스포티 우선, 로퍼·청바지 제외", sm["styles"][0] == "스포티" and "로퍼" in sm["excluded"] and "청바지" in sm["excluded"] and sm["focus"])
check("상황 설명: 출근 → '크롭 상의'처럼 부위 붙임", "크롭 상의" in b.situation_summary("출근", "F")["excluded"])
check("상황 설명: 없는 상황 → None", b.situation_summary(None, "F") is None and b.situation_summary("우주", "F") is None)
check("recommend_for_web 에 situation 포함", b.recommend_for_web({"gender": "여성", "height": 162, "weight": 55}, "균형", {"feels_like": 14}, "데이트")["situation"]["situation"] == "데이트")
for sx in "FM":
    tops = {bd: [o["fb"]["top"]["id"] for o in b.recommend_for_web({}, None, {"feels_like": 14}, "학교", body={"sex": sx, "group": "균형", "build": bd, "leg": "보통"})["outfits"]]
            for bd in ("마름", "통통")}
    check(f"체격 비교 {sx}: 마름 ≠ 통통", tops["마름"] != tops["통통"])
# 10/27 다양성 손질: 상황별 선호 표(tpo.PREFER) · 남성 실루엣(SILHOUETTE) · 남성 전용 이미지(gen_items/m)
SITS = ("학교", "데이트", "출근", "친구와 약속", "운동", "여행")
for sx in "FM":
    for f in (3, 14, 25):
        firsts = {sit: tuple(o["fb"][k]["id"] for k in ("top", "bottom") for o in web(sx, sit, f)[:1]) for sit in SITS}
        check(f"상황 다양성 {sx} {f}도: 6개 상황 첫 코디가 모두 다름", len(set(firsts.values())) == len(SITS))
        sp = web(sx, "운동", f)
        check(f"운동 {sx} {f}도: 니트·울 하의 없음", not any(o["fb"]["bottom"].get("소재") in ("니트", "울/캐시미어", "가죽") for o in sp))
for f in (3, 14, 25):                                              # 학교의 티셔츠·청바지 같은 기본템은 남녀 같아도 됨 — 차려입는 상황만 비교
    for sit in ("데이트", "출근"):
        fm = [tuple(o["fb"][k]["id"] for k in ("top", "bottom")) for o in (web("F", sit, f)[0], web("M", sit, f)[0])]
        check(f"남녀 {sit} {f}도: 첫 코디가 다름", fm[0] != fm[1])
mo = [o for f in (3, 14, 25) for sit in SITS for o in web("M", sit, f)]
check("남성: 벨보텀·니트·시폰 하의 없음", not any(o["fb"]["bottom"].get("핏") == "벨보텀" or o["fb"]["bottom"].get("소재") in ("니트", "시폰", "레이스") for o in mo))
check("남성: 레이스·시폰 상의 없음", not any(o["fb"]["top"].get("소재") in ("레이스", "시폰") for o in mo))
mimg = [c["image"] for o in mo for c in o["items"] if c["category"] in ("TOP", "BOTTOM", "OUTER") and c.get("image")]
if HAS_IMG: check("남성: 남성 실루엣 이미지(gen_items/m) 사용", any("/m/" in x.replace("\\", "/") for x in mimg))
check("여성: 남성 이미지 안 씀", not any("/m/" in (c.get("image") or "").replace("\\", "/") for o in web("F", "출근", 14) for c in o["items"]))
sm = b.situation_summary("출근", "M")
check("상황 설명: 우선한 아이템 (출근 M → 셔츠·재킷, 블라우스 없음)", "셔츠" in sm["preferred"] and "재킷" in sm["preferred"] and "블라우스" not in sm["preferred"])
check("상황 이유: '상황에 맞춰 고른' 문구가 화면 문장으로", any(w["kind"] == "상황" and "에 맞춰 고른" in w["text"] and w["text"].startswith("'") for o in web("M", "출근", 14) for w in o["why"]))
# 10/27 레이어드: 추운 날 차려입는 상황의 셔츠·블라우스 위에 니트 (화면 상의 카드 2장)
lay = [o for sx in "FM" for f in (0, 6, 10) for sit in ("출근", "데이트", "친구와 약속") for o in web(sx, sit, f)]
LO = [o for o in lay if len(o["items"]) == len(o["fb"]) + 2]
check("레이어드: 추운 날 차려입는 상황에 겹쳐 입기 코디가 있음", len(LO) >= 5)
check("레이어드: 겹친 옷은 셔츠·블라우스 위의 니트(터틀넥 아님)", all(o["fb"]["top"]["카테고리"] in ("셔츠", "블라우스") and "니트웨어" in o["items"][len(o["fb"]) - 1 + (0 if o["fb"].get("outer") else 1)]["name"] and "터틀넥" not in o["items"][2 if o["fb"].get("outer") else 1]["name"] for o in LO))
check("레이어드: 겹친 니트는 셔츠와 다른 색", all(len({c["color"] for c in o["items"] if c["category"] == "TOP"}) == 2 for o in LO))
check("레이어드: 이유에 '겹쳐' 문장", all(any("겹쳐" in w["text"] and w["kind"] == "날씨" for w in o["why"]) for o in LO))
check("레이어드: 더운 날·학교·운동에는 없음", not any(len(o["items"]) > len(o["fb"]) + 1 for sx in "FM" for f, sit in ((21, "출근"), (3, "학교"), (3, "운동")) for o in web(sx, sit, f)))
# 10/27 여성 점검: 영하에 7부 바지 줄이기 · 어색한 이름
cold = [o for sx in "FM" for sit in ("학교", "출근", "친구와 약속", "여행") for o in web(sx, sit, -3)]
check("영하: 7부(미디) 바지 1개 이하", sum(o["fb"]["bottom"].get("기장") == "미디" and o["fb"]["bottom"]["카테고리"] != "스커트" for o in cold) <= 1)
names = [c["name"] for sx in "FM" for f in (25, 31) for sit in ("학교", "여행", "운동") for o in web(sx, sit, f) for c in o["items"]]
check("이름: '미니 청바지'·'벨보텀 스커트' 없음", not any(("미니" in n and ("청바지" in n or "팬츠" in n)) or ("벨보텀" in n and "스커트" in n) for n in names))
# 11/11 테스터 피드백: 튀는 색 · 갈색 쏠림 · 스포티 부적합 · 선호 스타일/핏 반영 (수치 목표는 손으로 정한 값 — measure_v3 로 확인)
def webp(sx, sit, feels, style, fit="레귤러핏", bt="균형"):
    prof = {"gender": "여성" if sx == "F" else "남성", "height": 162 if sx == "F" else 175, "weight": 55 if sx == "F" else 68, "style": style, "fit": fit}
    return b.recommend_for_web(prof, bt, {"feels_like": feels, "precip_prob": 10}, sit)["outfits"]
import colorsys, tint
BAD_FOR_SPORTY = ("청바지", "스커트", "셔츠", "블라우스", "니트웨어", "재킷", "코트", "가디건")
sporty = [o for sx in "FM" for sit in ("출근", "학교", "데이트", "친구와 약속", "여행", "운동") for f in (5, 14, 25, 31) for o in webp(sx, sit, f, "스포티")]
check("스포티 선호: 청바지·스커트·셔츠·블라우스·니트·재킷·코트·가디건 없음", not any(o["fb"].get(k, {}).get("카테고리") in BAD_FOR_SPORTY for o in sporty for k in ("top", "bottom", "outer")))
check("스포티 선호: 로퍼·옥스포드·펌프스 없음", not any(any(w in o["items"][-1]["name"] for w in ("로퍼", "옥스포드", "펌프스")) for o in sporty))
check("스포티 선호: 하의는 저지·스판덱스 소재", all(o["fb"]["bottom"].get("소재") in ("저지", "스판덱스", None) for o in sporty))
check("운동: 재킷·우븐 바지 없음", not any(o["fb"].get("outer", {}).get("카테고리") == "재킷" or o["fb"]["bottom"].get("소재") == "우븐" for sx in "FM" for f in (5, 14, 25, 31) for o in web(sx, "운동", f)))
grid = [o for sx in "FM" for st in ("캐주얼", "미니멀", "스트릿", "스포티", "댄디") for sit in ("학교", "데이트", "출근", "운동") for f in (5, 14, 25, 31) for o in webp(sx, sit, f, st)]
col = lambda o: [c["color"] for c in o["items"] if c.get("color")]
VIV = {"레드", "오렌지", "옐로우", "퍼플", "그린", "네온", "골드"}
check("튀는 색(레드·오렌지·옐로우·퍼플·그린·네온·골드) 거의 없음 (2% 미만)", sum(any(c in VIV for c in col(o)) for o in grid) / len(grid) < 0.02)
EARTH3 = lambda o: sum(c in ("브라운", "베이지", "카키") for c in col(o)) >= 3
check("전체적으로 갈색: 갈색계 3곳 이상 코디 2% 미만", sum(EARTH3(o) for o in grid) / len(grid) < 0.02)
check("브라운 상의+브라운 하의 위아래 없음", not any(o["fb"]["top"].get("색상") == "브라운" and o["fb"]["bottom"].get("색상") == "브라운" for o in grid))
check("화면 색 팔레트: 블루·스카이블루·옐로우 채도 낮춤", all(colorsys.rgb_to_hsv(*(x / 255 for x in tint.COLORS[c]))[1] < lim for c, lim in (("블루", 0.55), ("스카이블루", 0.30), ("옐로우", 0.50), ("핑크", 0.25))))
rs = [w["text"] for o in webp("M", "학교", 14, "미니멀") for w in o["why"]]
check("선호 스타일 이유: '선호하시는 미니멀 스타일에 맞춰 고른' 문장", any(t.startswith("선호하시는 미니멀 스타일에 맞춰 고른 ") for t in rs))
check("선호 스타일 이유: 취향 문구가 없는 '스타일 선호 반영' 가짜 문구 없음", not any("미니멀 · " in w["text"] or "캐주얼 · " in w["text"] for st in ("미니멀", "캐주얼") for o in webp("F", "학교", 14, st) for w in o["why"]))
STY5 = ("캐주얼", "미니멀", "스트릿", "스포티", "댄디"); chg = tot = 0
for sx in "FM":
    for f in (5, 14, 25):
        top1 = {st: tuple(c["name"] for c in webp(sx, "학교", f, st)[0]["items"][:-1]) for st in STY5}
        for x in range(5):
            for y in range(x + 1, 5): tot += 1; chg += top1[STY5[x]] != top1[STY5[y]]
check("선호 스타일만 바꿔도 1안이 달라지는 비율 80% 이상", chg / tot >= 0.8)
FITW = {"오버핏": {"오버사이즈", "루즈"}, "슬림핏": {"타이트"}}
for fit, want in FITW.items():
    sel = [o for sx in "FM" for sit in ("학교", "데이트", "친구와 약속") for f in (8, 16, 24) for o in webp(sx, sit, f, "캐주얼", fit)]
    lim = 0.65 if fit == "오버핏" else 0.35
    check(f"선호 핏 {fit}: 상의 핏 일치 {lim:.0%} 이상", sum(o["fb"]["top"].get("핏") in want for o in sel) / len(sel) >= lim)
# 11/11 ④ 개인화 입력 — 좋아하는/피하고 싶은 색, 퍼스널 컬러, 머리 길이, 유사 의상
def webc(sx, sit, feels, **extra):
    prof = {"gender": "여성" if sx == "F" else "남성", "height": 162 if sx == "F" else 175, "weight": 55 if sx == "F" else 68, "style": "캐주얼", "fit": "레귤러핏", **extra}
    return b.recommend_for_web(prof, "균형", {"feels_like": feels, "precip_prob": 10}, sit)["outfits"]
cc = lambda os_: [c["color"] for o in os_ for c in o["items"] if c.get("color")]
check("engine_cpref: 비어 있으면 None · 이상한 값은 버림", b.engine_cpref({}) is None and b.engine_cpref({"like_colors": ["형광"], "personal_color": "x", "hair": "y"}) is None)
check("engine_cpref: 피하는 색과 겹치는 좋아하는 색은 뺌", b.engine_cpref({"like_colors": ["핑크", "블랙"], "avoid_colors": ["블랙"]}) == {"like": ["핑크"], "avoid": ["블랙"], "personal": None, "hair": None})
for av in (["브라운", "베이지"], ["블랙", "화이트"], ["그레이"]):
    allo = [o for sx in "FM" for sit in ("학교", "데이트", "출근", "운동") for f in (5, 14, 25) for o in webc(sx, sit, f, avoid_colors=av)]
    check(f"피하고 싶은 색 {av}: 코디(신발 포함)에 없음", not any(c in av for c in cc(allo)))
base_pink = sum(c == "핑크" for c in cc([o for sx in "FM" for sit in ("학교", "데이트") for f in (14, 25) for o in webc(sx, sit, f)]))
like_pink = sum(c == "핑크" for c in cc([o for sx in "FM" for sit in ("학교", "데이트") for f in (14, 25) for o in webc(sx, sit, f, like_colors=["핑크"])]))
check("좋아하는 색(핑크): 선택 안 했을 때보다 훨씬 자주 나옴", like_pink >= base_pink + 5)
liked_vivid = [o for sx in "FM" for sit in ("학교", "데이트") for f in (14, 25) for o in webc(sx, sit, f, like_colors=["오렌지"])]
check("좋아하는 색은 튀는 색이어도 반영 (오렌지)", any("오렌지" in cc([o]) for o in liked_vivid))
check("좋아하는 색 이유 문장", any("좋아하신다고 고른" in w["text"] for o in webc("F", "데이트", 14, like_colors=["핑크"]) for w in o["why"]))
check("피하고 싶은 색 안내 문장", any("넣지 않았어요" in w["text"] for o in webc("F", "데이트", 14, avoid_colors=["브라운"]) for w in o["why"]))
def top_colors(pc): return [o["fb"]["top"].get("색상") for sx in "FM" for sit in ("학교", "데이트", "출근", "친구와 약속") for f in (14, 20, 25) for o in webc(sx, sit, f, personal_color=pc)]
au, su = top_colors("가을웜"), top_colors("여름쿨")
check("퍼스널 컬러: 가을웜은 여름쿨보다 브라운·카키·베이지 상의가 많음", sum(c in ("브라운", "카키", "베이지") for c in au) > sum(c in ("브라운", "카키", "베이지") for c in su))
check("퍼스널 컬러: 여름쿨은 가을웜보다 라벤더·스카이블루·핑크 상의가 많음", sum(c in ("라벤더", "스카이블루", "핑크") for c in su) >= sum(c in ("라벤더", "스카이블루", "핑크") for c in au))
check("퍼스널 컬러 이유 문장", any("톤에 어울리는" in w["text"] for sx in "FM" for sit in ("학교", "데이트") for f in (14, 25) for o in webc(sx, sit, f, personal_color="가을웜") for w in o["why"]))
def necks(h): return [o["fb"]["top"].get("넥라인") for sx in "FM" for sit in ("학교", "데이트", "친구와 약속") for f in (14, 22, 28) for o in webc(sx, sit, f, hair=h)]
check("머리 길이: 긴 머리는 짧은 머리보다 터틀넥이 적음", necks("긴 머리").count("터틀넥") <= necks("짧은 머리").count("터틀넥"))
# 유사 의상
pf = {"gender": "여성", "height": 162, "weight": 55, "style": "캐주얼", "fit": "레귤러핏"}
wx = {"feels_like": 14, "precip_prob": 10}
r0 = b.recommend_for_web(pf, "균형", wx, "학교")["outfits"][0]
for key, part, cat in (("top", "상의", "TOP"), ("bottom", "하의", "BOTTOM"), ("outer", "아우터", "OUTER")):
    if not r0["fb"].get(key): continue
    sm = b.similar_for_web(pf, "균형", wx, "학교", key, r0["fb"][key]["id"], r0["fb"][key].get("색상"))
    base_cat = r0["fb"][key]["카테고리"]
    check(f"유사 의상 {part}: 같은 카테고리({base_cat}) 3벌 이상", len(sm["items"]) >= 3 and all(base_cat in i["name"] for i in sm["items"]))
    check(f"유사 의상 {part}: 서로 다른 옷 · 기준 옷과도 다름", len({i["name"] for i in sm["items"]}) == len(sm["items"]) and sm["base"] not in {i["name"] for i in sm["items"]})
    check(f"유사 의상 {part}: 기준 옷과 같은 색 유지", all(i["color"] == r0["fb"][key].get("색상") for i in sm["items"]))
sm = b.similar_for_web({**pf, "style": "스포티"}, "균형", wx, "운동", "bottom", r0["fb"]["bottom"]["id"], None)
check("유사 의상: 선호 스타일(스포티) 필터 유지 — 청바지·스커트 없음", not any(("청바지" in i["name"] or "스커트" in i["name"]) for i in sm["items"]))
for bad in (("shoes", 0), ("top", -1), ("top", 10 ** 6), ("top", True), ("top", "1")):
    try: b.similar_for_web(pf, "균형", wx, "학교", *bad); okk = False
    except ValueError: okk = True
    check(f"유사 의상: 잘못된 입력 {bad} → ValueError", okk)
print(f"{ok} ok, {fail} fail"); sys.exit(1 if fail else 0)
