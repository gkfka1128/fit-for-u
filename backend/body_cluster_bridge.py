"""
승민님 체형 분석 통합본(body_models/, FitForU_Four_Models_20261018 의 model_engine) ↔ 규칙 엔진 연결.

  승민 모델 출력 = 군집 번호만 (체형 이름 없음, recommendation_ready=false, 사진 검증 전)
  → 군집 평균 비율(U 상부/엉덩이, J 두께/키)이 그 성별 전체 평균보다 높고 낮은 정도로 엔진 입력(group, build)을 정함.
     zU = log(U_군집) - Σ(군집 인원 가중 평균 log U),  zJ 도 같은 방식
     group: zU > +0.03 상체형 · zU < -0.03 하체형 · 그 외 균형      build: zJ > +0.06 통통 · zJ < -0.06 마름 · 그 외 보통
  ⚠ 위 문턱(0.03, 0.06)은 우리가 임의로 잡은 임시값 — 승민님과 합의 전. 군집→체형 연결은 CLUSTER_BODY 표 한 곳만 고치면 된다.

  입력(비율) 두 가지:
    ratios      {"U","W","H"[, "D","J"]}   — 이미 계산된 비율 (팀 카메라 추출기 출력)
    measures    {"chest_width"|"bust_width","waist_width","hip_width","stature"[,"waist_depth","hip_depth"]} — 같은 단위의 실측

  preset 기본 "auto" = 정면만 → 3군집(정면 우선), 애매하면 need_side → 측면까지 → 5군집(five_best). 4개 preset 을 직접 줄 수도 있음.
  classify_body(sex, ratios=…|measures=…, preset="auto")
    → {"status": "ok" | "need_side", "cluster": 1, "body": {"sex","group","build","leg"}, "preset", "provisional": True}

  classify_photos(sex, front_bytes, side_bytes=None, preset=…)   — 사진 bytes → 승민님 MediaPipe 추출기(메모리에서만, 저장 안 함) → 군집 → 체형
    카메라 비율은 실측 보정 전 proxy 라 승민님 모델의 experimental=True 경로를 쓴다 (결과에 "experimental": True 표시)
    → {"status": "ok" | "need_side" | "retake" | "review", "quality": {"front": {...}, "side": {...}}, "body"?, "cluster"?}
"""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, file):
    """body_models/ 의 승민님 파일을 sys.path 에 넣지 않고 불러온다 (code/ 의 같은 이름 모듈 body_features 등을 가리지 않게)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "body_models", file))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


# [공개 저장소 전용] body_models/ (팀원의 체형 모델 파일)는 이 저장소에 포함되지 않는다. 없으면 체형 분석 API 만 안내 메시지로 응답하고
# 나머지(코디 추천·회원·웹)는 그대로 동작한다. 원본 저장소에서는 이 try 없이 항상 불러온다.
try:
    me = _load("ffu_body_models_engine", "model_engine.py")     # 승민 통합본 그대로 — 수정하지 않음
    sys.modules.setdefault("model_engine", me)                  # 분석기의 `from model_engine import attach_camera_results` 용
except (FileNotFoundError, OSError):
    me = None
NO_MODELS_MSG = "체형 분석 모델(body_models/)이 이 저장소에 포함되어 있지 않아요. 체형은 직접 선택하거나 팀 저장소의 모델 파일을 body_models/ 에 넣어 주세요."


def _need_models():
    if me is None: raise ValueError(NO_MODELS_MSG)

# (모델, 성별) → 군집별 (group, build). 2026-10-18 모델비교보고.txt 의 군집 평균 비율(학습 인원 가중)에서 위 규칙으로 도출한 임시 연결.
CLUSTER_BODY = {
    ("three_conditional", "Male"): [("균형", "보통"), ("균형", "통통"), ("상체형", "보통")],
    ("three_full", "Male"): [("균형", "보통"), ("균형", "통통"), ("상체형", "보통")],
    ("three_conditional", "Female"): [("하체형", "보통"), ("상체형", "통통"), ("균형", "보통")],
    ("three_full", "Female"): [("하체형", "보통"), ("상체형", "통통"), ("균형", "보통")],
    ("five_best", "Male"): [("균형", "마름"), ("하체형", "보통"), ("균형", "통통"), ("상체형", "보통"), ("하체형", "마름")],
    ("five_alternative", "Male"): [("균형", "마름"), ("하체형", "보통"), ("균형", "통통"), ("상체형", "보통"), ("하체형", "마름")],
    ("five_best", "Female"): [("상체형", "통통"), ("하체형", "마름"), ("균형", "마름"), ("균형", "보통"), ("균형", "통통")],
    ("five_alternative", "Female"): [("상체형", "통통"), ("하체형", "마름"), ("균형", "마름"), ("균형", "보통"), ("균형", "통통")],
}
PRESETS = tuple(me.REGISTRY) if me is not None else ()
SEX = {"M": "Male", "F": "Female", "Male": "Male", "Female": "Female"}
# 웹 기본 "auto": 정면만 오면 3군집(정면 우선) — 확실하면 그대로 결과, 애매하면(NEED_SIDE) 측면을 요청.
# 측면까지 오면(=3군집이 애매했던 경우) 5군집(five_best) 으로 정밀 판단.
AUTO, AUTO_FRONT, AUTO_SIDE = "auto", "three_conditional", "five_best"
SIDE_MSG = "정면만으로는 체형이 애매해요. 더 정밀한 5군집 분석을 위해 측면 사진을 추가해 주세요."
# 가슴 높이(어깨~골반 25%) 실루엣 폭 ÷ 어깨 관절 폭. 팔을 내리면 위팔까지 가슴 폭에 들어가 1.45~1.7 (AI Hub 2,608명 중앙값 1.61),
# 팔을 떼면 몸통만 남아 ~1.1 (runs/photo_calib.md §3). 승민님 분석기의 팔 겹침 검사는 팔꿈치·손목만 봐서 이걸 못 잡는다.
ARM_RATIO = 2.0   # 느슨하게: 팔 내린 사진(AI Hub)의 상위 5%만 — 팔을 몸에 꽉 붙였거나 배경과 섞인 정도만 재촬영. 1.40 은 A자 자세도 걸렸음(10/22)
ARM_MSG = "팔이 몸통에 붙어 있어 가슴 너비를 잴 수 없어요. 팔을 몸에서 살짝 떼고 다시 찍어 주세요."


def _resolve(preset, has_side):
    _need_models()
    if preset == AUTO: return AUTO_SIDE if has_side else AUTO_FRONT
    if preset not in me.REGISTRY: raise ValueError(f"preset 은 auto, {', '.join(PRESETS)} 중 하나")
    return preset


def classify_body(sex, ratios=None, measures=None, preset=AUTO):
    _need_models()
    src = ratios if ratios is not None else measures
    if not isinstance(src, dict): src = {}
    preset = _resolve(preset, all(src.get(k) is not None for k in (("D", "J") if ratios is not None else ("waist_depth", "hip_depth"))))
    sx = SEX.get(sex)
    if not sx: raise ValueError("sex 는 M/F (Male/Female)")
    if (ratios is None) == (measures is None): raise ValueError("ratios 또는 measures 중 하나만 주세요")
    r = me.classify(preset, sx, ratios) if ratios is not None else me.from_measurements(preset, sx, measures)
    if r["status"] == "NEED_SIDE":
        return {"status": "need_side", "cluster": None, "body": None, "preset": preset, "provisional": True,
                "message": "정면만으로 애매해 측면 측정값(허리두께, 엉덩이두께)이 필요합니다"}
    group, build = CLUSTER_BODY[(preset, sx)][r["cluster"]]
    return {"status": "ok", "cluster": r["cluster"], "preset": preset, "provisional": True, "side_requested": r["side_requested"],
            "body": {"sex": "M" if sx == "Male" else "F", "group": group, "build": build, "leg": "보통"}}


_ANALYZER = None
_LOCK = threading.Lock()                                   # MediaPipe detector 는 스레드 하나씩


def _analyzer_class():
    """승민님 mediapipe_bodypose_analyzer 를 불러온다. 그 파일의 `import body_features` 가 code/ 의 우리 body_features.py 와
    이름이 같아서, 불러오는 동안만 sys.modules 의 body_features 를 승민님 것으로 바꿔 둔다 (원본 파일은 수정하지 않음)."""
    ours = sys.modules.get("body_features")
    sys.modules["body_features"] = _load("ffu_body_models_features", "body_features.py")
    try:
        return _load("ffu_body_models_analyzer", "mediapipe_bodypose_analyzer.py").BodyPoseAnalyzer
    finally:
        if ours is not None: sys.modules["body_features"] = ours
        else: sys.modules.pop("body_features", None)


def _quality(v):
    if v is None: return None
    q = v["quality"]
    return {"status": q["status"], "errors": q.get("errors", []), "warnings": q.get("warnings", [])}


def arm_ratio(front):
    """정면 결과의 가슴 실루엣 폭 ÷ 어깨 관절 폭 (없으면 None)"""
    f = (front or {}).get("features") or {}
    c, s = f.get("chest_width_px"), f.get("shoulder_width_landmark_px")
    return c / s if c and s else None


def _review_result(r, preset, sx):
    """품질 REVIEW(경고만) 사진도 특징이 있으면 승민님 attach_camera_results 와 같은 비율로 군집 판정 (그쪽은 PASS 일 때만 붙임)"""
    f, sd = (r.get("front") or {}).get("features"), (r.get("side") or {}).get("features") if r.get("side") else None
    if not f or (r.get("side") and not sd): return None
    ratios = {"U": f["chest_hip_width_ratio"], "W": f["waist_hip_width_ratio"], "H": f["hip_width_to_pose_height"]}
    if sd: ratios.update(D=sd["waist_hip_depth_ratio"], J=sd["hip_depth_to_pose_height"])
    try: return me.classify(preset, sx, ratios)
    except ValueError: return None


def classify_photos(sex, front, side=None, preset=AUTO):
    _need_models()
    global _ANALYZER
    preset = _resolve(preset, bool(side))
    sx = SEX.get(sex)
    if not sx: raise ValueError("sex 는 M/F (Male/Female)")
    if not isinstance(front, (bytes, bytearray)) or not front: raise ValueError("정면 사진이 필요합니다")
    with _LOCK:
        if _ANALYZER is None: _ANALYZER = _analyzer_class()()
        r = _ANALYZER.process_pair(bytes(front), bytes(side) if side else None, gender=sx, preset=preset, experimental=True)
    quality = {"front": _quality(r["front"]), "side": _quality(r["side"])}
    ar = arm_ratio(r["front"])
    # 10/22 실제 촬영에서 1.40 은 팔을 뗀 A자 자세도 걸림 (가슴 높이=겨드랑이 근처라 위팔이 붙어 보임) → 2.0 으로 느슨하게.
    # 기준을 다시 잡기 위해 값을 서버 로그에 남긴다 (사진·개인정보 없음, 숫자만).
    if ar is not None: print(f"[arm_ratio] {ar:.3f} sex={sx} front={quality['front']['status']}", file=sys.stderr, flush=True)
    if ar is not None and ar > ARM_RATIO and quality["front"]["status"] != "RETAKE":
        quality["front"] = {**quality["front"], "status": "RETAKE", "errors": quality["front"]["errors"] + [ARM_MSG]}
    out = {"preset": preset, "provisional": True, "experimental": True, "quality": quality, "cluster": None, "body": None}
    statuses = [q["status"] for q in quality.values() if q]
    if "RETAKE" in statuses: return {**out, "status": "retake", "message": "다시 촬영이 필요합니다: " + " / ".join(e for q in quality.values() if q for e in q["errors"])}
    res = r["research_models"][preset]
    if "REVIEW" in statuses:
        # 경고(주로 "팔이 측정선과 겹칩니다")만 있으면 막지 않고 분석 — 10/22 촬영에서 가이드 자세로도 자주 걸림. 결과에 경고를 같이 넘김.
        res = _review_result(r, preset, sx)
        if res is None: return {**out, "status": "review", "message": "촬영 품질 확인이 필요해 분석하지 않았습니다: " + " / ".join(w for q in quality.values() if q for w in q["warnings"])}
        out["warnings"] = [w for q in quality.values() if q for w in q["warnings"]]
    if res.get("status") == "NEED_SIDE": return {**out, "status": "need_side", "message": SIDE_MSG}
    if res.get("cluster") is None: return {**out, "status": "review", "message": "분석 결과가 없습니다"}
    group, build = CLUSTER_BODY[(preset, sx)][res["cluster"]]
    f = (r.get("front") or {}).get("features") or {}
    ratios = {k: round(f[n], 4) for k, n in (("U", "chest_hip_width_ratio"), ("W", "waist_hip_width_ratio"), ("H", "hip_width_to_pose_height")) if f.get(n) is not None}
    return {**out, "status": "ok", "cluster": res["cluster"], "side_requested": res.get("side_requested"), "ratios": ratios,   # 실측 검증용 숫자 (사진 아님)
            "body": {"sex": "M" if sx == "Male" else "F", "group": group, "build": build, "leg": "보통"}}
