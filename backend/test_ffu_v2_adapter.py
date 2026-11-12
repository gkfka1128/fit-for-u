"""
v2 어댑터 테스트 — 04_prediction 예시 + front_profile_v1(정면 API) + 경계 사례 (군집 매핑 유무, 예측 보류, 잘못된 값).
  .\\.venv\\Scripts\\python.exe test_ffu_v2_adapter.py        (약 20초)
"""
import copy, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffu_v2_adapter import recommend_v2, build_from_bmi
from rule_engine import RuleEngine

ROOT = os.path.dirname(os.path.abspath(__file__))
W = {"feels_like": 12, "precip_prob": 10}
fails, checks = [], 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond: fails.append(msg)


def codes(r, key="errors"):
    return {e["code"] for e in r[key]}


def main():
    with open(os.path.join(ROOT, "contracts", "ffu_v2", "04_prediction.example.json"), encoding="utf-8") as f: base = json.load(f)
    e = RuleEngine(); body_ids = {r["id"] for r in e.body["rules"]}
    run = lambda p, w=W, cmap={}, **k: recommend_v2(p, w, engine=e, cmap=cmap, **k)

    def mod(**kv):
        p = copy.deepcopy(base); p.update(kv); return p

    # 1. 04 예시 그대로 — 매핑 없음 → 균형 기본값 + 경고, 추천은 나옴
    r = run(base)
    check(r["status"] == "ok", f"1 status {r['status']} {r['errors']}")
    check(r["body_input"]["group"] == "균형" and r["body_input"]["mapped"] is False, f"1 body {r['body_input']}")
    check(r["body_input"]["build"] == "보통" and r["body_input"]["source"]["build"] == "body_profile.BMI", "1 BMI 22.0 → 보통")
    check({"CLUSTER_UNMAPPED", "DEMO_MODEL"} <= codes(r, "warnings"), f"1 경고 {codes(r, 'warnings')}")
    check(len(r["recommendation"]["outfits"]) == 3, "1 3안")
    check(r["request_id"] == "demo-002" and r["model_version"] == base["model_version"] and r["photo_validated"] is False, "1 메타 전달")
    check(r["body_input"]["sex"] == "F", "1 female → F")
    check("confidence" not in json.dumps(r), "1 confidence 생성 금지")

    # 2. 합의된 매핑이 있으면 group 반영 → 하체형 규칙(H) 발동
    cmap = {base["model_version"]: {"sex": "female", "feature_spec": base["feature_spec"], "cluster_count": 3,
                                    "clusters": {"0": {"group": "하체형"}, "1": {"group": "상체형", "build": "마름", "leg": "숏"}}}}
    r = run(base, cmap=cmap)
    check(r["status"] == "ok" and r["body_input"]["group"] == "하체형" and r["body_input"]["mapped"], f"2 매핑 {r['body_input']}")
    check("CLUSTER_UNMAPPED" not in codes(r, "warnings"), "2 매핑됐는데 경고")
    check(any(i.startswith("H") for o in r["recommendation"]["outfits"] for i in o["rules"] if i in body_ids), "2 H 규칙 발동 없음")
    r = run(mod(cluster_id=1), cmap=cmap)
    check(r["body_input"]["group"] == "상체형" and r["body_input"]["build"] == "마름" and r["body_input"]["leg"] == "숏", f"2b {r['body_input']}")
    check(r["body_input"]["source"]["build"] == "cluster_map", "2b build 출처")

    # 3. 매핑과 예측 모델이 어긋나면 추천하지 않음
    for name, bad in (("sex", {"sex": "male"}), ("count", {"cluster_count": 4}), ("spec", {"feature_spec": "HEIGHT5"})):
        c = copy.deepcopy(cmap); c[base["model_version"]].update(bad)
        r = run(base, cmap=c)
        check(r["status"] == "error" and "MODEL_MAP_MISMATCH" in codes(r) and r["recommendation"] is None, f"3 {name} 불일치 {r['status']}")
    r = run(mod(cluster_id=2), cmap=cmap)
    check(r["status"] == "error" and "CLUSTER_UNMAPPED" in codes(r), "3 매핑에 없는 군집")
    c = copy.deepcopy(cmap); c[base["model_version"]]["clusters"]["0"] = {"group": "역삼각형"}
    check("INVALID_CLUSTER_MAP" in codes(run(base, cmap=c)), "3 목록 밖 group")

    # 4. 예측 보류 → 상태·사유 그대로, 추천 없음
    miss = ["front.bust_width_px"]
    r = run(mod(status="retake_required", cluster_id=None, body_profile=None, missing_required_measurements=miss,
                errors=[{"code": "REQUIRED_MISSING", "message": "x"}]))
    check(r["status"] == "retake_required" and r["recommendation"] is None, f"4 retake {r['status']}")
    check(r["missing_required_measurements"] == miss and {"REQUIRED_MISSING", "PREDICTION_NOT_OK"} <= codes(r), "4 사유 전달")
    r = run(mod(status="error", cluster_id=None))
    check(r["status"] == "error" and r["recommendation"] is None, "4 error")

    # 5. 잘못된 값
    for name, p, code in (
            ("schema", mod(schema_version="1.0"), "UNSUPPORTED_SCHEMA"),
            ("sex", mod(sex="other"), "UNSUPPORTED_SEX"),
            ("status", mod(status="partial"), "INVALID_STATUS"),
            ("cid bool", mod(cluster_id=True), "INVALID_CLUSTER_ID"),
            ("cid str", mod(cluster_id="0"), "INVALID_CLUSTER_ID"),
            ("cid 음수", mod(cluster_id=-1), "INVALID_CLUSTER_ID"),
            ("cid 범위", mod(cluster_id=3), "CLUSTER_OUT_OF_RANGE"),
            ("mv 없음", mod(model_version=""), "MISSING_MODEL_VERSION"),
            ("bmi nan", mod(body_profile={**base["body_profile"], "BMI": float("nan")}), "INVALID_BODY_PROFILE"),
            ("bmi bool", mod(body_profile={**base["body_profile"], "BMI": True}), "INVALID_BODY_PROFILE")):
        r = run(p)
        check(r["status"] == "error" and code in codes(r) and r["recommendation"] is None, f"5 {name}: {r['status']} {codes(r)}")
    check(run("not json")["status"] == "error", "5 dict 아님")
    for name, w in (("feels 없음", {"precip_prob": 10}), ("feels bool", {"feels_like": True}), ("feels inf", {"feels_like": float("inf")}),
                    ("precip 범위", {"feels_like": 12, "precip_prob": 150})):
        r = run(base, w)
        check(r["status"] == "error" and "INVALID_WEATHER" in codes(r), f"5 날씨 {name}")

    # 6. BMI → build, BMI 없음 → 보통 + 경고, 남성, 비
    check([build_from_bmi(b) for b in (17.0, 18.5, 22.9, 23.0, 30)] == ["마름", "보통", "보통", "통통", "통통"], "6 BMI 경계")
    r = run(mod(body_profile={**base["body_profile"], "BMI": None}))
    check(r["status"] == "ok" and r["body_input"]["build"] == "보통" and "BMI_MISSING" in codes(r, "warnings"), "6 BMI 없음")
    r = run(mod(body_profile=None))
    check(r["status"] == "ok" and "BMI_MISSING" in codes(r, "warnings"), "6 body_profile 없음")
    r = run(mod(sex="male", body_profile={"BMI": 26.0}), {"feels_like": 25, "precip_prob": 70}, style="스트리트")
    check(r["status"] == "ok" and r["body_input"]["sex"] == "M" and r["body_input"]["build"] == "통통", f"6 남성 {r['body_input']}")
    check(r["recommendation"]["rain"] is True and all(o["top"]["카테고리"] not in ("블라우스", "스커트") for o in r["recommendation"]["outfits"]), "6 남성·비")
    r = run(base, {"feels_like": 12})
    check(r["status"] == "ok" and r["recommendation"]["input"]["weather"]["precip_prob"] == 0, "6 precip 생략 → 0")

    # 7. front_profile_v1 (팀 정면 API) — 실제 rules/cluster_map.json 사용
    from ffu_v2_adapter import load_cluster_map
    cm = load_cluster_map()
    fr = {}
    for k in ("M", "F", "retake"):
        with open(os.path.join(ROOT, "contracts", "front_v1", f"front_profile.example_{k}.json"), encoding="utf-8") as f: fr[k] = json.load(f)
    r = run(fr["M"], cmap=cm, user={"height_cm": 175, "weight_kg": 70})
    bi = r["body_input"] or {}
    check(r["status"] == "ok" and r["input_schema"] == "front_profile_v1" and r["sex"] == "male", f"7 남성 정면 {r['errors']}")
    check(bi.get("sex") == "M" and bi.get("group") == "상체형" and bi.get("cluster_label") == "상체중심형" and bi.get("mapped"), f"7 남성 매핑 {bi}")
    check(bi.get("build") == "보통" and bi["source"]["build"] == "user.height_weight", "7 키·몸무게 → BMI 22.9 → 보통")
    check("EXPERIMENTAL_MODEL" in codes(r, "warnings") and "CLUSTER_MAP_PROVISIONAL" not in codes(r, "warnings"), f"7 남성 경고 {codes(r, 'warnings')}")
    check(r["model_id"] == "Male_front_equal_82001" and len(r["recommendation"]["outfits"]) == 3, "7 남성 메타·3안")
    for cid, g, lab in ((0, "하체형", "하체중심형"), (1, "균형", "균형형")):
        r = run({**fr["M"], "cluster_id": cid}, cmap=cm)
        check(r["status"] == "ok" and r["body_input"]["group"] == g and r["body_input"]["cluster_label"] == lab, f"7 남성 군집 {cid}")
        check("BMI_MISSING" in codes(r, "warnings"), f"7 키·몸무게 없음 → BMI_MISSING ({cid})")
    r = run(fr["F"], cmap=cm, user={"height_cm": 160, "weight_kg": 45})
    check(r["status"] == "ok" and r["body_input"]["group"] == "하체형" and r["body_input"]["build"] == "마름", f"7 여성 {r['body_input']}")
    check("CLUSTER_MAP_PROVISIONAL" in codes(r, "warnings") and r["body_input"].get("provisional"), "7 여성 임시 매핑 경고")
    r = run(fr["retake"], cmap=cm)
    check(r["status"] == "retake_required" and "implausible_width" in codes(r) and r["recommendation"] is None, f"7 재촬영 {r['errors']}")
    r = run(fr["F"], cmap={})
    check(r["status"] == "ok" and r["body_input"]["group"] == "균형" and "CLUSTER_UNMAPPED" in codes(r, "warnings"), "7 매핑 없음 → 균형")
    r = run({**fr["M"], "model_id": "Female_front_waist_priority_82001"}, cmap=cm)
    check(r["status"] == "error" and "MODEL_MAP_MISMATCH" in codes(r), "7 성별·model_id 불일치")
    r = run({**fr["M"], "cluster_id": 3}, cmap=cm)
    check(r["status"] == "error" and "CLUSTER_OUT_OF_RANGE" in codes(r), "7 군집 범위")
    for name, kv, code in (("sex 소문자", {"sex": "male"}, "UNSUPPORTED_SEX"), ("model_id 없음", {"model_id": None}, "MISSING_MODEL_ID"),
                           ("status 이상", {"status": "ok"}, "INVALID_STATUS"), ("ratios 문자", {"ratios": {"upper_hip_ratio": "x"}}, "INVALID_BODY_PROFILE")):
        r = run({**fr["M"], **kv}, cmap=cm)
        check(r["status"] == "error" and code in codes(r), f"7 {name} → {code} ({codes(r)})")
    r = run({**fr["M"], "quality": {"passed": False, "code": "tilt"}, "error": "기울어짐"}, cmap=cm)
    check(r["status"] == "retake_required" and "tilt" in codes(r), "7 quality 실패 → 재촬영")
    for name, u in (("키 단위 오류", {"height_cm": 17.5, "weight_kg": 70}), ("몸무게 문자", {"height_cm": 170, "weight_kg": "70"}), ("user 리스트", [170, 70])):
        r = run(fr["M"], cmap=cm, user=u)
        check(r["status"] == "error" and "INVALID_USER" in codes(r), f"7 {name} → INVALID_USER")
    r = run(fr["M"], cmap=cm, user={"height_cm": 170})
    check(r["status"] == "ok" and "BMI_MISSING" in codes(r, "warnings"), "7 몸무게만 없음 → BMI_MISSING")

    # 8. 여성: group 은 upper_hip_ratio 3분위, 군집은 waist (허리 굴곡 규칙 K1~K5)
    gf = cm["Female_front_waist_priority_82001@front_proxy_v3"]["group_from"]
    r = run(fr["F"], cmap=cm)
    bi = r["body_input"]
    check(bi["group"] == "하체형" and bi["source"]["group"] == "ratio:upper_hip_ratio" and bi["waist"] == "굴곡", f"8 굴곡·하체 {bi}")
    check(bi["ratio"]["value"] == fr["F"]["ratios"]["upper_hip_ratio"] and bi["ratio"]["lo"] == gf["lo"], "8 비율 근거 전달")
    for u, cid, g, wst in ((gf["lo"] + 0.001, 2, "균형", "보통"), (gf["hi"] + 0.01, 1, "상체형", "직선"), (gf["lo"] - 0.01, 1, "하체형", "직선"), (gf["hi"], 0, "균형", "굴곡")):
        r = run({**fr["F"], "cluster_id": cid, "ratios": {"upper_hip_ratio": u, "waist_hip_ratio": 0.8}}, cmap=cm)
        check(r["status"] == "ok" and r["body_input"]["group"] == g and r["body_input"]["waist"] == wst, f"8 U {u:.4f} 군집 {cid} → {g}/{wst} ({r['body_input']})")
    r = run({**fr["F"], "ratios": {"waist_hip_ratio": 0.8}}, cmap=cm)
    check(r["status"] == "ok" and r["body_input"]["group"] == "균형" and "RATIO_MISSING" in codes(r, "warnings"), "8 비율 없음 → 균형 + 경고")
    r = run(fr["M"], cmap=cm)
    check(r["body_input"]["waist"] == "보통" and r["body_input"]["source"]["waist"] == "default", "8 남성 waist 기본값")
    # 허리 규칙이 점수에 들어가는지 — 같은 아이템에 waist 만 바꿔 body_score 비교
    bf = {"sex": "F", "group": "균형", "build": "보통", "leg": "보통"}
    for part, attr, val, wst, rid in (("아우터", "핏", "타이트", "굴곡", "K1"), ("상의", "핏", "오버사이즈", "굴곡", "K2"), ("상의", "기장", "크롭", "직선", "K3"),
                                      ("아우터", "핏", "타이트", "직선", "K4"), ("상의", "핏", "타이트", "직선", "K5")):
        it = next(x for x in e.items[part] if x["attrs"].get(attr) == val)
        s0, f0 = e.body_score({**bf, "waist": "보통"}, part, it); s1, f1 = e.body_score({**bf, "waist": wst}, part, it)
        check(rid in {r["id"] for r in f1} and rid not in {r["id"] for r in f0} and s1 != s0, f"8 {rid} {part} {val} ({s0}→{s1})")
    check(all(r["id"] in body_ids for r in e.body["rules"]) and {"K1", "K2", "K3", "K4", "K5"} <= body_ids, "8 K1~K5 규칙 로드")

    print(f"검사 {checks}건, 실패 {len(fails)}")
    for m in fails: print("  ✗", m)
    if fails: sys.exit(1)
    print("모든 검사 통과 ✓")


if __name__ == "__main__":
    main()
