"""
3대 체형(상체형 / 균형 / 하체형) 기준을 문헌 절대값 대신 **실측 집단의 백분위(3분위)** 로 잡는다.

  문제 (체형검증_260918.md §4): KS K 0050 드롭 18.3/13, 논문 C/H 1.01·H/W 1.22 를 의류 통합 데이터 실측 3,150명에 적용하면 66~75% 가 하체형.
  → 지표 하나로 통일: 남 = 드롭(가슴−허리), 여 = 가슴/엉덩이 비율.  상위 1/3 상체형, 하위 1/3 하체형, 가운데 균형.
  결과 = data/body_thresholds.json.  pipeline.to_body_json / validate_body / baseline_body 가 이걸 읽는다 (없으면 문헌값 폴백).

  .\.venv\Scripts\python.exe body_thresholds.py
"""
import io, json, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "body_thresholds.json")
LITERATURE = {"M": {"metric": "drop", "hi": 18.3, "lo": 13.0, "source": "KS K 0050 (역삼각 Y / 보통 A / 삼각 B)"},
              "F": {"metric": "chest_hip", "hi": 1.01, "lo": None, "hw": 1.22, "source": "Sci. Reports 2026 (C/H>1.01 상체형, H/W>1.22 하체형)"}}

def load_thresholds():
    return json.loads(io.open(OUT, encoding="utf-8").read()) if os.path.exists(OUT) else None

def group_of(sex, bust, waist, hip, th=None):
    """치수 → 상체형/균형/하체형. th=None 이면 파일(없으면 문헌값)."""
    th = th if th is not None else (load_thresholds() or {})
    if sex == "M":
        v = bust - waist
        hi, lo = (th["M"]["hi"], th["M"]["lo"]) if "M" in th else (LITERATURE["M"]["hi"], LITERATURE["M"]["lo"])
        return "상체형" if v > hi else "균형" if v > lo else "하체형"
    if "F" in th:
        v = bust / hip; return "상체형" if v > th["F"]["hi"] else "균형" if v > th["F"]["lo"] else "하체형"
    ch, hw = bust / hip, hip / waist
    return "상체형" if ch > 1.01 else "하체형" if hw > 1.22 else "균형"

def main():
    df = pd.read_csv(os.path.join(DATA, "clothes_meta.csv"), dtype=str, keep_default_na=False)
    for k in ["body_height", "waist_size", "hip_seize", "weight", "chest_size_male", "breast_size_female"]: df[k] = pd.to_numeric(df[k], errors="coerce")
    df["chest"] = df["chest_size_male"].fillna(df["breast_size_female"])
    df = df[df.view == "wear"].drop_duplicates(subset=["gender", "age", "body_height", "waist_size", "hip_seize", "weight", "chest"])
    df = df[(df.body_height > 140) & (df.weight > 30) & (df.waist_size > 40) & (df.hip_seize > 60) & (df.chest > 60)]
    th = {"_doc": "실측 3분위 기준 (AI Hub 의류 통합 데이터 착용자). 남 = 가슴−허리 드롭(cm), 여 = 가슴/엉덩이 비율. > hi 상체형, > lo 균형, 그 외 하체형", "n": {}}
    m = df[df.gender == "MALE"]; d = m.chest - m.waist_size
    th["M"] = {"metric": "drop", "hi": round(float(d.quantile(2 / 3)), 1), "lo": round(float(d.quantile(1 / 3)), 1), "median": round(float(d.median()), 1)}
    f = df[df.gender == "FEMALE"]; r = f.chest / f.hip_seize
    th["F"] = {"metric": "chest_hip", "hi": round(float(r.quantile(2 / 3)), 3), "lo": round(float(r.quantile(1 / 3)), 3), "median": round(float(r.median()), 3)}
    th["n"] = {"M": int(len(m)), "F": int(len(f))}; th["literature"] = LITERATURE
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(th, ensure_ascii=False, indent=1))
    for sex, d_, sub in (("M", d, m), ("F", r, f)):
        g = pd.Series([group_of(sex, b, w, h, th) for b, w, h in zip(sub.chest, sub.waist_size, sub.hip_seize)]).value_counts(normalize=True)
        print(sex, th[sex], "→ 분포", {k: f"{v*100:.0f}%" for k, v in g.items()})
    print("saved", OUT)

if __name__ == "__main__":
    main()
