"""
체형 추정 v2 — 키·몸무게(필수) + 형태 1문항 또는 사진(선택)

  9/18~20 검증 결과(체형검증_260918.md): 실루엣 측정은 키·몸무게 회귀보다 못함 → 둘레는 키·몸무게로 추정하고,
  형태(상체형/균형/하체형)는 ① 사진 3D 추정(SHAPY 등, 준비 중) ② 없으면 사용자 1문항 ③ 그것도 없으면 균형.

  둘레 모델 = baseline_body.py 가 실측 3,150명으로 학습한 Ridge (models/body_ridge_{M,F}_{항목}.joblib)
  유형 기준 = data/body_thresholds.json (실측 3분위)

  estimate(sex, height, weight, age="20대", answer=None, photo_shape=None)
    answer      : "상체" | "하체" | "비슷" | None      (사용자 1문항: 어깨/가슴이 넓은 편 · 골반/엉덩이가 넓은 편 · 비슷)
    photo_shape : {"chest":…, "waist":…, "hip":…}     (3D 메시 추정 결과가 생기면 여기로 — 있으면 문항보다 우선)
  → rule_engine 입력 JSON ({"sex","group","build","leg", "_basis", "_measured"})
"""
import os, io, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")
AGES = ["20대", "30대", "40대", "50대 이상"]
TARGETS = {"chest": "chest", "waist": "waist_size", "hip": "hip_seize", "shoulder": "shoulders_width"}
_cache = {}

def _model(sex, key):
    k = (sex, key)
    if k not in _cache:
        import joblib
        p = os.path.join(MODELS, f"body_ridge_{sex}_{TARGETS[key]}.joblib")
        _cache[k] = joblib.load(p) if os.path.exists(p) else None
    return _cache[k]

def measurements(sex, height, weight, age="20대"):
    """키·몸무게·나이 → 가슴·허리·엉덩이둘레·어깨너비 (cm). 모델 없으면 None"""
    x = np.array([[height, weight, weight / (height / 100) ** 2, height * weight] + [1.0 if age == a else 0.0 for a in AGES]])
    out = {}
    for key in TARGETS:
        m = _model(sex, key)
        if m is None: return None
        out[key] = round(float(m.predict(x)[0]), 1)
    return out

def estimate(sex, height, weight, age="20대", answer=None, photo_shape=None):
    from body_thresholds import group_of, load_thresholds
    bmi = weight / (height / 100) ** 2
    build = "마름" if bmi < 18.5 else "보통" if bmi < 23 else "통통"
    est = measurements(sex, height, weight, age)
    th = load_thresholds()
    if photo_shape:                                                   # ① 사진 3D 추정 (SHAPY 등) — 검증되면 사용
        group = group_of(sex, photo_shape["chest"], photo_shape["waist"], photo_shape["hip"])
        basis = f"사진 3D 추정 치수로 판정 (가슴 {photo_shape['chest']} · 허리 {photo_shape['waist']} · 엉덩이 {photo_shape['hip']})"
        source = "photo3d"
    elif answer in ("상체", "하체", "비슷"):                            # ② 사용자 1문항
        group = {"상체": "상체형", "하체": "하체형", "비슷": "균형"}[answer]
        basis = {"상체": "어깨·가슴이 넓은 편이라고 답함", "하체": "골반·엉덩이가 넓은 편이라고 답함", "비슷": "비슷하다고 답함"}[answer]
        source = "answer"
    else:                                                             # ③ 정보 없음
        group, basis, source = "균형", "형태 정보 없음 → 균형으로 가정", "default"
    return {"sex": sex, "group": group, "build": build, "leg": "보통",
            "_basis": {"group": basis, "build": f"BMI {bmi:.1f}", "leg": "다리 비율 미측정 → 보통", "source": source},
            "_measured": {"est_cm": est, "method": "키·몸무게 회귀 (실측 3,150명, 허리 MAE 3.9cm)" if est else None, "warnings": []}}

if __name__ == "__main__":
    print(json.dumps(estimate("M", 173, 65, "20대", "상체"), ensure_ascii=False, indent=1))
