"""
규칙 엔진 테스트 — 불변 조건 + 규칙 효과 + 864 케이스 스윕 (성별 2 × 체형 3×3×3 × 기온 8 × 비 2).
  .\\.venv\\Scripts\\python.exe test_rule_engine.py        (약 2분)
"""
import itertools, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rule_engine import RuleEngine
from preference import Preference

FEELS = [-8, 3, 7, 10, 14, 18, 22, 30]
fails, checks = [], 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond: fails.append(msg)


def main():
    t0 = time.time(); e = RuleEngine(); rain_mat = set(e.weather["rain"]["material_exclude"])
    valid_ids = {r["id"] for r in e.body["rules"]} | {r["id"] for r in e.body["color_rules"]} | {"M1", "T1", "P1", "SH1", "R1", "SC1", "Y1"}
    cover = {"n": 0, "prod_all": 0, "prod_some": 0, "wearing": 0, "slot": 0, "wear_m": 0, "m": 0}
    for sex, g, b, l, f, rain in itertools.product("FM", ("상체형", "균형", "하체형"), ("마름", "보통", "통통"), ("롱", "보통", "숏"), FEELS, (False, True)):
        body = {"sex": sex, "group": g, "build": b, "leg": l}; tag = f"{sex}/{g}/{b}/{l}/{f}°/{'비' if rain else '맑음'}"
        r = e.recommend(body, {"feels_like": f, "precip_prob": 80 if rain else 10}); band = e.band(f); outs = r["outfits"]
        check(len(outs) == 3, f"{tag}: 안 {len(outs)}개")
        check(len({o["top"]["id"] for o in outs}) == len(outs) and len({o["bottom"]["id"] for o in outs}) == len(outs), f"{tag}: 상의·하의 중복")
        for o in outs:
            check(bool(o["reason"]) and o["reason"].count(".") <= 6, f"{tag}: 이유 문장")
            check(len(o["query"]) >= 2 and all(o["query"]), f"{tag}: 검색어")
            check(set(o["rules"]) <= valid_ids, f"{tag}: 알 수 없는 규칙 id {set(o['rules']) - valid_ids}")
            check(bool(o["shoes"]), f"{tag}: 신발")
            check(o["colors"].get("신발") in ("블랙", "화이트", "브라운", "베이지"), f"{tag}: 신발 색 {o['colors'].get('신발')}")
            if sex == "M": check(not ({"B1", "B2"} & set(o["rules"])), f"{tag}: 남성에 여성 전용 규칙 B1·B2")
            check(band["outer"] != "forbid" or o["outer"] is None, f"{tag}: 더운 날 아우터")
            check(band["outer"] != "require" or o["outer"] is not None, f"{tag}: 추운 날 아우터 없음")
            check(not o["outer"] or o["outer"].get("카테고리") not in band.get("outer_category_exclude", []), f"{tag}: 추운 날 얇은 겉옷 {o['outer'] and o['outer'].get('카테고리')}")
            check(o["top"].get("소매기장") is None or o["top"]["소매기장"] in band["top_sleeve"], f"{tag}: 소매 {o['top'].get('소매기장')}")
            for p in ("top", "bottom", "outer"):
                if o[p]:
                    check(o[p]["색상"], f"{tag}: {p} 색 없음")
                    if rain: check(o[p].get("소재") not in rain_mat, f"{tag}: 비 소재 {o[p].get('소재')}")
            if sex == "M":
                ex = e.body["sex_exclude"]["M"]
                for p, key in (("상의", "top"), ("하의", "bottom"), ("아우터", "outer")):
                    it = o[key]
                    if it: check(not any(it.get(k) in vs for k, vs in ex.get(p, {}).items()), f"{tag}: 남성 제외 아이템 {it['label']}")
                check(o["shoes"] not in ("펌프스", "플랫 슈즈", "앵클 부츠", "롱 부츠"), f"{tag}: 남성 신발 {o['shoes']}")
            if rain: check(o["shoes"] not in e.weather["rain"]["shoes_exclude"], f"{tag}: 비 신발 {o['shoes']}")
            ph = o.get("photo") or {}; parts_n = sum(1 for k in ("top", "bottom", "outer") if o[k])
            cover["n"] += 1; cover["prod_all"] += len(ph.get("product") or {}) == parts_n; cover["prod_some"] += bool(ph.get("product"))
            cover["wearing"] += bool(ph.get("wearing")); cover["slot"] += bool(ph.get("wearing") or ph.get("outfit"))
            for rel in [ph.get("outfit"), ph.get("wearing")] + list((ph.get("product") or {}).values()) + list((ph.get("wear") or {}).values()) + list((ph.get("items") or {}).values()):
                if rel: check(os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)), f"{tag}: 사진 파일 없음 {rel}")
            if sex == "M":
                check(not ph.get("outfit"), f"{tag}: 남성에게 K-Fashion 여성 착장 사진"); cover["m"] += 1; cover["wear_m"] += bool(ph.get("wear"))
                if ph.get("wearing"): check(ph.get("wearing_sex") == "M", f"{tag}: 남성에게 남성 아닌 착용 컷")
            else:
                check(not ph.get("wear"), f"{tag}: 여성에게 남성 단품 컷")
    # 규칙 효과: 체형 규칙이 실제로 추천을 바꾸는지
    base = {"sex": "F", "group": "균형", "build": "보통", "leg": "보통"}; w = {"feels_like": 12, "precip_prob": 10}
    up = e.recommend({**base, "group": "상체형"}, w)["outfits"]; nb = e.recommend(base, w)["outfits"]
    check(any("G1" in o["rules"] for o in up), "상체형: G1 미발동")
    check(not any(("G4" in o["rules"] or "G5" in o["rules"]) for o in up), "상체형: 오프숄더·보트넥 추천")
    fat = e.recommend({**base, "build": "통통"}, {"feels_like": 25, "precip_prob": 0})["outfits"]
    check(all(o["top"].get("핏") != "타이트" for o in fat), "통통: 타이트 상의 추천")
    # 취향: 👍 를 누르면 그 속성이 더 자주 나오는지
    pref = Preference(); o0 = nb[0]
    for _ in range(3): pref.feedback(o0, True)
    liked = e.recommend(base, w, pref=pref)["outfits"]
    check(any("P1" in o["rules"] for o in liked), "취향: P1 미발동")
    # 스타일: 스타일을 고르면 T1 이 붙고 결과가 달라지는지
    st = e.recommend(base, w, style="스트리트")["outfits"]
    check(any("T1" in o["rules"] for o in st), "스타일: T1 미발동")
    # 10/16 추가: 비 오는 날 아우터 선호(R1) · 체형 규칙 끄기(A/B 대조군) · TPO 스타일 묶음 · 신발 색
    rainy = e.recommend(base, {"feels_like": 14, "precip_prob": 80})["outfits"]
    check(any("R1" in o["rules"] for o in rainy), "비: R1(점퍼·짚업 우선) 미발동")
    body_ids = {r["id"] for r in e.body["rules"]} | {r["id"] for r in e.body["color_rules"]}
    off = e.recommend({**base, "group": "상체형"}, w, use_body=False)["outfits"]
    check(not any(body_ids & set(o["rules"]) for o in off), "use_body=False 인데 체형 규칙 발동")
    check([o["top"]["id"] for o in off] != [o["top"]["id"] for o in up], "use_body=False 가 결과를 안 바꿈 (상체형)")
    import tpo
    multi = e.recommend(base, w, style=tpo.styles_for("출근·면접", "F"))["outfits"]
    check(any("T1" in o["rules"] for o in multi) and "·" in " ".join(o["reason"] for o in multi), "TPO 스타일 묶음: T1 미발동")
    check(e.shoe_color("로퍼", {"하의": "베이지"}, "선선") == "브라운" and e.shoe_color("스니커즈", {"하의": "블루"}, "선선") == "화이트", "신발 색 규칙")
    print(f"검사 {checks:,}건, 실패 {len(fails)}, {time.time()-t0:.0f}s")
    n = max(cover["n"], 1)
    print(f"사진 커버 ({cover['n']}안): 제품 컷 전부 {cover['prod_all']/n:.0%} · 일부 {cover['prod_some']/n:.0%} · 착용 컷(143) {cover['wearing']/n:.0%} · 착장 칸(착용 컷 또는 K-Fashion) {cover['slot']/n:.0%} · 남성 단품 착용 컷 {cover['wear_m']/max(cover['m'],1):.0%}")
    for m in fails[:20]: print("  ✗", m)
    print("모든 검사 통과 ✓" if not fails else f"실패 {len(fails)}건")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
