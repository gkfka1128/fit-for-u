"""
Fit-For-U 통합 JSON v2 ↔ 규칙 엔진 어댑터 (추천 파트).
K-Means 파트의 예측 JSON 과 날씨를 받아 규칙 엔진 입력(sex, group, build, leg) 으로 바꾸고 코디 3안을 붙여 돌려준다.
받는 형식 두 가지:
  - 2.0 (04_prediction: sex + model_version + cluster_id + body_profile)
  - front_profile_v1 (팀 레포 body_analysis/front_prototype POST /analyze 응답, 10/12 정면 전용)
    → normalize_front_v1() 로 2.0 모양으로 바꿔 같은 경로를 탄다. 매핑 키는 "model_id@model_version"
      (정면 모델은 model_version 이 남녀 공통이라 model_id 까지 봐야 함).

  - 군집 → group 은 rules/cluster_map.json 에 합의된 매핑만 쓴다. 없으면 '균형' + 경고 (군집 번호를 체형명으로 번역하지 않음).
  - build 는 매핑 항목이 없으면 body_profile.BMI → 없으면 user 키·몸무게로 계산 (<18.5 마름 / <23 보통 / ≥23 통통).
    둘 다 없으면 '보통' + 경고. (정면 API 는 키·몸무게를 받지 않으므로 앱/백엔드가 user 로 넘겨야 함)
  - 매핑 항목에 group_from 이 있으면 group 을 군집이 아니라 비율값(예: upper_hip_ratio)의 3분위로 정하고,
    군집은 waist(굴곡/보통/직선, 허리 굴곡 규칙 K1~K5)로만 쓴다 — 여성 정면 모델은 허리 굴곡 기준 군집이라 상·하체 축과 다름.
  - leg 는 v2·정면 모두 다리 비율이 없어 매핑 항목이 없으면 '보통' (L 규칙 비활성).
  - 예측 status 가 ok 가 아니면 추천하지 않고 사유를 그대로 넘긴다. confidence 같은 값은 만들지 않는다.

  .\\.venv\\Scripts\\python.exe ffu_v2_adapter.py --prediction contracts/ffu_v2/04_prediction.example.json --feels 12 --precip 10
  .\\.venv\\Scripts\\python.exe ffu_v2_adapter.py --prediction contracts/front_v1/front_profile.example_M.json --feels 12 --height 175 --weight 70
"""
import argparse, io, json, math, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SCHEMA_VERSION = "2.0"
RECOMMENDATION_VERSION = "ffu-rec-1.0"
SEX = {"female": "F", "male": "M"}
GROUPS, BUILDS, LEGS = ("상체형", "균형", "하체형"), ("마름", "보통", "통통"), ("롱", "보통", "숏")
WAISTS = ("굴곡", "보통", "직선")
USER_RANGE = {"height_cm": (100, 230), "weight_kg": (25, 250)}
PRED_STATUS = ("ok", "retake_required", "error")
FRONT_SCHEMA = "front_profile_v1"
FRONT_SEX = {"Female": "female", "Male": "male"}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _err(code, msg, field=None):
    e = {"code": code, "message": msg}
    if field: e["field"] = field
    return e


def load_cluster_map(path=None):
    with open(path or os.path.join(ROOT, "rules", "cluster_map.json"), encoding="utf-8") as f:
        return json.load(f).get("models", {})


def build_from_bmi(bmi):
    return "마름" if bmi < 18.5 else "보통" if bmi < 23 else "통통"


def validate_prediction(pred):
    """예측 JSON 구조 검사 → errors 목록 (비면 통과)."""
    if not isinstance(pred, dict): return [_err("INVALID_PREDICTION", "예측 JSON 이 객체가 아님")]
    errs = []
    if pred.get("schema_version") != SCHEMA_VERSION:
        errs.append(_err("UNSUPPORTED_SCHEMA", f"schema_version {pred.get('schema_version')!r} 미지원 (지원: {SCHEMA_VERSION})", "schema_version"))
    if pred.get("sex") not in SEX:
        errs.append(_err("UNSUPPORTED_SEX", f"sex {pred.get('sex')!r} 미지원 (male/female)", "sex"))
    if pred.get("status") not in PRED_STATUS:
        errs.append(_err("INVALID_STATUS", f"status {pred.get('status')!r} (ok/retake_required/error)", "status"))
    if pred.get("status") != "ok": return errs
    if not isinstance(pred.get("model_version"), str) or not pred["model_version"]:
        errs.append(_err("MISSING_MODEL_VERSION", "model_version 없음", "model_version"))
    cid, cnt = pred.get("cluster_id"), pred.get("cluster_count")
    if not _int(cid) or cid < 0:
        errs.append(_err("INVALID_CLUSTER_ID", f"cluster_id {cid!r} 는 0 이상 정수여야 함", "cluster_id"))
    if cnt is not None and (not _int(cnt) or cnt < 1):
        errs.append(_err("INVALID_CLUSTER_COUNT", f"cluster_count {cnt!r}", "cluster_count"))
    elif _int(cid) and _int(cnt) and cid >= cnt:
        errs.append(_err("CLUSTER_OUT_OF_RANGE", f"cluster_id {cid} ≥ cluster_count {cnt}", "cluster_id"))
    bp = pred.get("body_profile")
    if bp is not None and not isinstance(bp, dict):
        errs.append(_err("INVALID_BODY_PROFILE", "body_profile 이 객체가 아님", "body_profile"))
    elif bp:
        for k, v in bp.items():
            if v is not None and not _num(v):
                errs.append(_err("INVALID_BODY_PROFILE", f"body_profile.{k} = {v!r} (유한 숫자 또는 null)", f"body_profile.{k}"))
    return errs


def validate_weather(weather):
    if not isinstance(weather, dict): return [_err("INVALID_WEATHER", "weather 가 객체가 아님")]
    errs = []
    if not _num(weather.get("feels_like")):
        errs.append(_err("INVALID_WEATHER", f"feels_like {weather.get('feels_like')!r} (체감온도 °C 숫자 필수)", "weather.feels_like"))
    p = weather.get("precip_prob")
    if p is not None and (not _num(p) or not 0 <= p <= 100):
        errs.append(_err("INVALID_WEATHER", f"precip_prob {p!r} (0~100 또는 생략)", "weather.precip_prob"))
    return errs


def normalize_front_v1(raw):
    """front_profile_v1 (정면 체형 API 응답) → (2.0 모양 예측, warnings, errors).
    errors 가 있으면 형식 오류. retake 는 status='retake_required' + 사유 errors 로 바꾼다."""
    warns, errs = [], []
    status = raw.get("status")
    q = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
    pred = {"schema_version": SCHEMA_VERSION, "input_schema": FRONT_SCHEMA, "request_id": raw.get("request_id"),
            "sex": FRONT_SEX.get(raw.get("sex"), raw.get("sex")), "model_version": raw.get("model_version"),
            "model_id": raw.get("model_id"), "cluster_id": raw.get("cluster_id"),
            "feature_definition_version": raw.get("measurement_definition"),
            "photo_validated": raw.get("photo_validated", False)}
    if status == "retake" or (status == "experimental" and q.get("passed") is False):
        pred["status"] = "retake_required"
        pred["errors"] = [_err(q.get("code") or "retake", raw.get("error") or "재촬영 필요", "photo")]
        return pred, warns, errs
    if status != "experimental":
        errs.append(_err("INVALID_STATUS", f"status {status!r} ({FRONT_SCHEMA}: experimental/retake)", "status"))
        return pred, warns, errs
    if raw.get("sex") not in FRONT_SEX:
        errs.append(_err("UNSUPPORTED_SEX", f"sex {raw.get('sex')!r} 미지원 (Male/Female)", "sex"))
    if not isinstance(raw.get("model_id"), str) or not raw["model_id"]:
        errs.append(_err("MISSING_MODEL_ID", "model_id 없음 (정면 모델은 성별마다 달라 필수)", "model_id"))
    if q.get("passed") is not True:
        errs.append(_err("INVALID_QUALITY", f"quality.passed {q.get('passed')!r}", "quality.passed"))
    centers = raw.get("cluster_centers")
    pred.update(status="ok", feature_spec=raw.get("measurement_definition"),
                cluster_count=len(centers) if isinstance(centers, list) and centers else None,
                body_profile=dict(raw["ratios"]) if isinstance(raw.get("ratios"), dict) else raw.get("ratios"))
    if isinstance(pred["model_id"], str) and isinstance(pred["model_version"], str):
        pred["map_key"] = f"{pred['model_id']}@{pred['model_version']}"
    warns.append(_err("EXPERIMENTAL_MODEL", "정면 사진 프로토타입 결과 — 정확도 미검증, 측면·상하 비율 미포함"))
    return pred, warns, errs


def validate_user(user):
    """user = {"height_cm", "weight_kg"} (앱/백엔드가 받는 키·몸무게) → errors 목록. None 은 '안 받음' 이라 통과."""
    if user is None: return []
    if not isinstance(user, dict): return [_err("INVALID_USER", "user 가 객체가 아님", "user")]
    errs = []
    for k, (lo, hi) in USER_RANGE.items():
        v = user.get(k)
        if v is not None and not (_num(v) and lo <= v <= hi):
            errs.append(_err("INVALID_USER", f"{k} {v!r} ({lo}~{hi})", f"user.{k}"))
    return errs


def bmi_from_user(user):
    """user = {"height_cm", "weight_kg"} → BMI 또는 None (없거나 범위 밖이면 None)."""
    if not isinstance(user, dict) or validate_user(user): return None
    h, w = user.get("height_cm"), user.get("weight_kg")
    if h is None or w is None: return None
    return w / (h / 100) ** 2


def group_from_ratio(spec, profile):
    """spec = {"ratio", "lo", "hi", "below", "between", "above"} → (group 또는 None, 비율값)."""
    v = (profile or {}).get(spec.get("ratio"))
    if not _num(v): return None, v
    return (spec["below"] if v < spec["lo"] else spec["above"] if v > spec["hi"] else spec["between"]), v


def body_from_prediction(pred, cmap, user=None):
    """검증된 ok 예측 → (엔진 body, 매핑 정보, warnings, errors)."""
    warns, errs = [], []
    sex, mv, cid = SEX[pred["sex"]], pred["model_version"], pred["cluster_id"]
    body = {"sex": sex, "group": "균형", "build": None, "leg": "보통", "waist": "보통"}
    info = {"mapped": False, "source": {"group": "default", "build": None, "leg": "default", "waist": "default"}}
    key = pred.get("map_key") or mv
    entry = cmap.get(key)
    if mv.startswith("demo"):
        warns.append(_err("DEMO_MODEL", f"model_version {mv!r} 는 가상 예시 — 실제 추론 결과 아님"))
    if entry is None:
        warns.append(_err("CLUSTER_UNMAPPED", f"모델 {key!r} 의 군집 매핑이 없어 group='균형' 기본값 사용 (체형 파트와 매핑 합의 필요)", "cluster_id"))
    else:
        if entry.get("sex") not in (None, pred["sex"]):
            errs.append(_err("MODEL_MAP_MISMATCH", f"매핑의 sex {entry.get('sex')!r} ≠ 예측 sex {pred['sex']!r}", "sex"))
        if entry.get("cluster_count") is not None and pred.get("cluster_count") is not None and entry["cluster_count"] != pred["cluster_count"]:
            errs.append(_err("MODEL_MAP_MISMATCH", f"매핑 cluster_count {entry['cluster_count']} ≠ 예측 {pred['cluster_count']}", "cluster_count"))
        if entry.get("feature_spec") and pred.get("feature_spec") and entry["feature_spec"] != pred["feature_spec"]:
            errs.append(_err("MODEL_MAP_MISMATCH", f"매핑 feature_spec {entry['feature_spec']!r} ≠ 예측 {pred['feature_spec']!r}", "feature_spec"))
        c = entry.get("clusters", {}).get(str(cid))
        if c is None:
            errs.append(_err("CLUSTER_UNMAPPED", f"{key!r} 매핑에 cluster_id {cid} 항목 없음", "cluster_id"))
        elif not errs:
            for k, allowed in (("group", GROUPS), ("build", BUILDS), ("leg", LEGS), ("waist", WAISTS)):
                if k in c:
                    if c[k] not in allowed:
                        errs.append(_err("INVALID_CLUSTER_MAP", f"{mv} 군집 {cid} {k}={c[k]!r}", f"cluster_map.{k}"))
                    else:
                        body[k] = c[k]; info["source"][k] = "cluster_map"
            gf = entry.get("group_from")
            if gf and not errs:
                g, v = group_from_ratio(gf, pred.get("body_profile"))
                if g in GROUPS:
                    body["group"] = g; info["source"]["group"] = f"ratio:{gf['ratio']}"
                    info["ratio"] = {"name": gf["ratio"], "value": v, "lo": gf["lo"], "hi": gf["hi"]}
                elif g is None:
                    body["group"] = "균형"; info["source"]["group"] = "default"
                    warns.append(_err("RATIO_MISSING", f"body_profile.{gf.get('ratio')} 없음 → group='균형' 기본값", f"body_profile.{gf.get('ratio')}"))
                else:
                    errs.append(_err("INVALID_CLUSTER_MAP", f"{key} group_from 결과 {g!r}", "cluster_map.group_from"))
            elif "group" not in c:
                errs.append(_err("INVALID_CLUSTER_MAP", f"{mv} 군집 {cid} 에 group 없음", "cluster_map.group"))
            info["mapped"] = not errs
            if c.get("label"): info["cluster_label"] = c["label"]
            if not errs and entry.get("status") == "provisional":
                info["provisional"] = True
                warns.append(_err("CLUSTER_MAP_PROVISIONAL", f"{key!r} 군집 {cid}({c.get('label', '')}) → group {body['group']} · waist {body['waist']} 는 임시 매핑 — 체형 파트 확인 전", "cluster_id"))
    if body["build"] is None:
        bmi, src = (pred.get("body_profile") or {}).get("BMI"), "body_profile.BMI"
        if bmi is None:
            bmi, src = bmi_from_user(user), "user.height_weight"
        if bmi is None:
            body["build"] = "보통"; info["source"]["build"] = "default"
            warns.append(_err("BMI_MISSING", "BMI 없음(body_profile.BMI·user 키/몸무게) → build='보통' 기본값", "body_profile.BMI"))
        else:
            body["build"] = build_from_bmi(bmi); info["source"]["build"] = src; info["bmi"] = round(bmi, 1)
    return body, info, warns, errs


def recommend_v2(pred, weather, style=None, engine=None, cmap=None, pref=None, user=None):
    """예측 JSON(2.0 또는 front_profile_v1) + 날씨 (+ user 키·몸무게) → 추천 응답 (status ok / retake_required / error)."""
    pre_warns = []
    if isinstance(pred, dict) and pred.get("schema_version") == FRONT_SCHEMA:
        pred, pre_warns, ferrs = normalize_front_v1(pred)
        if ferrs: pred["_front_errors"] = ferrs
    p = pred if isinstance(pred, dict) else {}
    out = {"schema_version": SCHEMA_VERSION, "recommendation_version": RECOMMENDATION_VERSION,
           "input_schema": p.get("input_schema", p.get("schema_version")),
           "request_id": p.get("request_id"), "status": "error", "sex": p.get("sex"),
           "model_version": p.get("model_version"), "model_id": p.get("model_id"), "cluster_id": p.get("cluster_id"),
           "feature_definition_version": p.get("feature_definition_version"),
           "photo_validated": p.get("photo_validated", False),
           "body_input": None, "warnings": [], "errors": [],
           "missing_required_measurements": list(p.get("missing_required_measurements") or []),
           "recommendation": None}
    if p.get("_front_errors"):
        out["errors"] = p["_front_errors"]; return out
    if p.get("input_schema") == FRONT_SCHEMA and p.get("status") == "retake_required":
        out["status"] = "retake_required"      # 정면 API 재촬영 응답은 sex 가 없을 수 있어 구조 검사 전에 처리
        out["errors"] = p["errors"] + [_err("PREDICTION_NOT_OK", "체형 예측 status=retake → 추천 보류")]
        return out
    errs = validate_prediction(pred)
    if errs:
        out["errors"] = errs; return out
    if p["status"] != "ok":                      # 예측 보류 — 사유만 넘기고 추천하지 않음
        out["status"] = p["status"]
        out["errors"] = list(p.get("errors") or []) + [_err("PREDICTION_NOT_OK", f"체형 예측 status={p['status']} → 추천 보류")]
        return out
    errs = validate_weather(weather) + validate_user(user)
    if errs:
        out["errors"] = errs; return out
    body, info, warns, errs = body_from_prediction(p, load_cluster_map() if cmap is None else cmap, user)
    out["warnings"] = pre_warns + warns
    if errs:
        out["errors"] = errs; return out
    if engine is None:
        from rule_engine import RuleEngine
        engine = RuleEngine()
    w = {"feels_like": float(weather["feels_like"]), "precip_prob": weather.get("precip_prob") or 0}
    out["body_input"] = {**body, **info}
    out["recommendation"] = engine.recommend(body, w, style=style, pref=pref)
    out["status"] = "ok"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prediction", required=True, help="체형 예측 JSON (04_prediction 2.0 또는 front_profile_v1)")
    ap.add_argument("--height", type=float, default=None, help="키 cm (BMI 없을 때 build 계산)")
    ap.add_argument("--weight", type=float, default=None, help="몸무게 kg")
    ap.add_argument("--feels", type=float, required=True); ap.add_argument("--precip", type=int, default=0)
    ap.add_argument("--style", default=None); ap.add_argument("--cluster-map", default=None)
    a = ap.parse_args()
    with open(a.prediction, encoding="utf-8") as f: pred = json.load(f)
    r = recommend_v2(pred, {"feels_like": a.feels, "precip_prob": a.precip}, style=a.style,
                     cmap=load_cluster_map(a.cluster_map) if a.cluster_map else None,
                     user={"height_cm": a.height, "weight_kg": a.weight} if a.height and a.weight else None)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
