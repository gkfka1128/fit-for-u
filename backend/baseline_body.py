"""
체형 베이스라인 — 사진 없이 키·몸무게(·나이·성별)만으로 둘레를 얼마나 맞히나  (validate_body.py 의 사진 방식과 비교용)

  의류 통합 데이터 착용자 3,154명(남 754 / 여 2,400)의 실측으로 5-fold 교차검증.
  모델 = Ridge 회귀 (키, 몸무게, BMI, 키×몸무게, 나이대 원핫) → 가슴·허리·엉덩이둘레·어깨너비
  + 같은 사람들에게 3대 체형(상체형/균형/하체형) 규칙을 적용했을 때 분포·일치율

  .\.venv\Scripts\python.exe baseline_body.py
출력: runs/body_baseline.md, models/body_ridge_{M,F}.joblib
"""
import io, json, os
import numpy as np, pandas as pd, joblib
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs"); MODELS = os.path.join(HERE, "models")
KEY = ["gender", "age", "body_height", "waist_size", "hip_seize", "shoulders_width", "weight", "chest"]
AGES = ["20대", "30대", "40대", "50대 이상"]

def group_of(sex, bust, waist, hip):
    if sex == "M":
        drop = bust - waist; return np.where(drop > 18.3, "상체형", np.where(drop > 13.0, "균형", "하체형"))
    ch, hw = bust / hip, hip / waist
    return np.where(ch > 1.01, "상체형", np.where(hw > 1.22, "하체형", "균형"))

def people():
    df = pd.read_csv(os.path.join(DATA, "clothes_meta.csv"), dtype=str, keep_default_na=False)
    for k in ["body_height", "waist_size", "hip_seize", "shoulders_width", "weight", "chest_size_male", "breast_size_female"]:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    df["chest"] = df["chest_size_male"].fillna(df["breast_size_female"])
    df = df[df.view == "wear"].drop_duplicates(subset=KEY)
    df = df[(df.body_height > 140) & (df.weight > 30) & (df.waist_size > 40) & (df.hip_seize > 60) & (df.chest > 60) & (df.shoulders_width > 30)]
    return df

def feats(d):
    X = pd.DataFrame({"h": d.body_height, "w": d.weight, "bmi": d.weight / (d.body_height / 100) ** 2, "hw": d.body_height * d.weight})
    for a in AGES: X["age_" + a] = (d.age == a).astype(float)
    return X.values

def main():
    df = people(); os.makedirs(OUT, exist_ok=True); os.makedirs(MODELS, exist_ok=True)
    L = ["# 체형 베이스라인 — 키·몸무게·나이만으로 (사진 없음)", "", f"의류 통합 데이터 착용자 {len(df):,}명 (남 {(df.gender=='MALE').sum()} / 여 {(df.gender=='FEMALE').sum()}), Ridge 회귀 5-fold CV.", ""]
    res = {}
    for g, sex in (("MALE", "M"), ("FEMALE", "F")):
        d = df[df.gender == g]; X = feats(d); res[sex] = {}
        L += [f"## {'남성' if sex == 'M' else '여성'} n={len(d)}", "", "| 항목 | MAE (cm) | 상관 r | ±5cm 이내 | 평균만 썼을 때 MAE |", "|---|---|---|---|---|"]
        preds = {}
        for k, nm in (("chest", "가슴둘레"), ("waist_size", "허리둘레"), ("hip_seize", "엉덩이둘레"), ("shoulders_width", "어깨너비")):
            y = d[k].values
            model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
            p = cross_val_predict(model, X, y, cv=KFold(5, shuffle=True, random_state=0)); preds[k] = p
            e = p - y; r = np.corrcoef(p, y)[0, 1]; naive = np.abs(y - y.mean()).mean()
            res[sex][k] = dict(mae=float(np.abs(e).mean()), r=float(r), within5=float((np.abs(e) <= 5).mean()), naive_mae=float(naive))
            L.append(f"| {nm} | {np.abs(e).mean():.1f} | {r:.2f} | {(np.abs(e) <= 5).mean()*100:.0f}% | {naive:.1f} |")
            model.fit(X, y); joblib.dump(model, os.path.join(MODELS, f"body_ridge_{sex}_{k}.joblib"))
        t = group_of(sex, d.chest.values, d.waist_size.values, d.hip_seize.values)
        p = group_of(sex, preds["chest"], preds["waist_size"], preds["hip_seize"])
        acc = float((t == p).mean()); res[sex]["group_acc"] = acc
        dist = pd.Series(t).value_counts(); maj = dist.max() / len(t)
        L += ["", f"**3대 체형 일치율 {acc*100:.1f}%** (실측 정답 vs 키·몸무게 예측치로 판정)  — 다수 클래스만 찍으면 {maj*100:.1f}%", "",
              "실측 기준 체형 분포: " + ", ".join(f"{k} {v} ({v/len(t)*100:.0f}%)" for k, v in dist.items()), ""]
        ct = pd.crosstab(pd.Series(t, name="실측"), pd.Series(p, name="예측"))
        L += ["| 실측 \\ 예측 | " + " | ".join(ct.columns) + " |", "|---|" + "---|" * len(ct.columns)] + [f"| {i} | " + " | ".join(str(v) for v in row) + " |" for i, row in ct.iterrows()] + [""]
        # 실측 분포 자체: 드롭/비율의 백분위
        if sex == "M":
            drop = d.chest - d.waist_size
            L += [f"남성 드롭(가슴−허리) 백분위: 10% {drop.quantile(.1):.1f} / 25% {drop.quantile(.25):.1f} / 50% {drop.quantile(.5):.1f} / 75% {drop.quantile(.75):.1f} / 90% {drop.quantile(.9):.1f}  (KS K 0050 기준 18.3·13 은 이 집단에서 상위 {(drop>18.3).mean()*100:.0f}% · {(drop>13).mean()*100:.0f}%)", ""]
        else:
            ch, hw = d.chest / d.hip_seize, d.hip_seize / d.waist_size
            L += [f"여성 가슴/엉덩이 백분위: 10% {ch.quantile(.1):.3f} / 50% {ch.quantile(.5):.3f} / 90% {ch.quantile(.9):.3f}  (>1.01 인 사람 {(ch>1.01).mean()*100:.0f}%)",
                  f"여성 엉덩이/허리 백분위: 10% {hw.quantile(.1):.3f} / 50% {hw.quantile(.5):.3f} / 90% {hw.quantile(.9):.3f}  (>1.22 인 사람 {(hw>1.22).mean()*100:.0f}%)", ""]
    io.open(os.path.join(OUT, "body_baseline.md"), "w", encoding="utf-8").write("\n".join(L))
    io.open(os.path.join(OUT, "body_baseline.json"), "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    print("\n".join(L))

if __name__ == "__main__":
    main()
