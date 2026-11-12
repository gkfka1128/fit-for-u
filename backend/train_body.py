"""
사진 → 실측 치수 회귀 학습 (교수님이 말한 "학습된 체형 분석")

  정답 = AI Hub 의류 통합 데이터 착용자 실측(가슴·허리·엉덩이둘레·어깨너비), 입력 = 사진 특징(body_features.py) + 키·몸무게·나이.
  비교: (a) 키·몸무게·나이만 (baseline_body.py 와 동일)  (b) + 사진 특징.  같은 사람·같은 fold 로 5-fold CV.
  → "사진이 키·몸무게 위에 얼마나 더 맞히나" 가 우리 AI 의 성능 지표.

  1) 특징 추출  .\.venv\Scripts\python.exe train_body.py extract --n 600     # 성별당 n명, 1장 ≈ 1초 → runs/body_feats.csv (이어서 실행 가능)
  2) 학습·평가  .\.venv\Scripts\python.exe train_body.py train              # → runs/body_train.md, models/body_photo_{M,F}_{항목}.joblib
"""
import argparse, io, json, os, random, tempfile, time, zipfile
import numpy as np, pandas as pd, joblib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs"); MODELS = os.path.join(HERE, "models")
FEATS = os.path.join(OUT, "body_feats_v3.csv")      # v1 마스크 높이 정규화 / v2 랜드마크 정규화 / v3 + 3D world landmark·품질 지표
TARGETS = [("chest", "가슴둘레"), ("waist_size", "허리둘레"), ("hip_seize", "엉덩이둘레"), ("shoulders_width", "어깨너비")]
AGES = ["20대", "30대", "40대", "50대 이상"]

def extract(n, seed):
    from validate_body import pick, img_zip
    from body_features import FeatureExtractor, NAMES
    done = set(pd.read_csv(FEATS, dtype=str)["name"]) if os.path.exists(FEATS) else set()
    sel = pick(n, seed); sel = sel[~sel.name.isin(done)]
    print(f"추출 대상 {len(sel)} (이미 {len(done)})", flush=True)
    ex = FeatureExtractor(); tmp = tempfile.mkdtemp(prefix="bodyfeat_"); zips = {}
    rows = []; t0 = time.time()
    for i, r in enumerate(sel.itertuples(index=False)):
        zp = img_zip(r.split, r.category)
        if zp not in zips: z = zipfile.ZipFile(zp); zips[zp] = (z, {os.path.basename(x): x for x in z.namelist()})
        z, mem = zips[zp]; nm = mem.get(r.name + ".jpg")
        if nm is None: continue
        p = os.path.join(tmp, "img.jpg"); open(p, "wb").write(z.read(nm))
        try: f = ex(p)
        except Exception: f = None
        if f is None: continue
        rows.append({"name": r.name, "sex": "M" if r.gender == "MALE" else "F", "age": r.age, "height": r.body_height, "weight": r.weight,
                     "chest": r.chest, "waist_size": r.waist_size, "hip_seize": r.hip_seize, "shoulders_width": r.shoulders_width, **{k: f[k] for k in NAMES}})
        if (i + 1) % 50 == 0:
            pd.DataFrame(rows).to_csv(FEATS, mode="a", header=not os.path.exists(FEATS), index=False); rows = []
            print(f"  {i+1}/{len(sel)}  {time.time()-t0:.0f}s", flush=True)
    if rows: pd.DataFrame(rows).to_csv(FEATS, mode="a", header=not os.path.exists(FEATS), index=False)
    print("saved", FEATS)

def train():
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import KFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from body_features import NAMES
    df = pd.read_csv(FEATS); df = df.drop_duplicates("name")
    df = df[(df.weight > 30) & (df.chest > 60) & (df.waist_size > 40) & (df.hip_seize > 60)]
    df["bmi"] = df.weight / (df.height / 100) ** 2; df["hw"] = df.height * df.weight
    for a in AGES: df["age_" + a] = (df.age == a).astype(float)
    base_cols = ["height", "weight", "bmi", "hw"] + ["age_" + a for a in AGES]
    photo_cols = [c for c in NAMES if c not in ("nose_vis", "facing", "shoulder_tilt", "hip_tilt", "arm_asym")]
    os.makedirs(MODELS, exist_ok=True)
    L = ["# 사진 → 실측 치수 회귀 (의류 통합 데이터 착용자)", "", f"사람 {len(df):,}명 (남 {(df.sex=='M').sum()} / 여 {(df.sex=='F').sum()}), 사람당 사진 1장, 5-fold CV. 정면 컷만: facing=+1.", "",
         "MAE (cm) — 키·몸무게·나이만 vs + 사진 특징(Ridge) vs + 사진 특징(GBM)", ""]
    res = {}
    for sex in ("M", "F"):
        d = df[(df.sex == sex) & (df.facing > 0) & (df.shoulder_tilt < 0.15) & (df.arm_asym < 0.35)].dropna(subset=["wl_shoulder"]).reset_index(drop=True)   # 정면·직립·대칭 컷만
        if len(d) < 40: continue
        res[sex] = {"n": int(len(d))}
        L += [f"## {'남성' if sex == 'M' else '여성'} n={len(d)} (정면·직립·대칭 컷만)", "", "| 항목 | 키·몸무게만 | +사진 Ridge | +사진 GBM | r (GBM) | ±5cm (GBM) |", "|---|---|---|---|---|---|"]
        cv = KFold(5, shuffle=True, random_state=0)
        Xb = d[base_cols].values; Xp = d[base_cols + photo_cols].values
        for k, nm in TARGETS:
            y = d[k].values
            pb = cross_val_predict(make_pipeline(StandardScaler(), Ridge(1.0)), Xb, y, cv=cv)
            pr = cross_val_predict(make_pipeline(StandardScaler(), Ridge(3.0)), Xp, y, cv=cv)
            gbm = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8, random_state=0)
            pg = cross_val_predict(gbm, Xp, y, cv=cv)
            m = lambda p: float(np.abs(p - y).mean())
            res[sex][k] = {"base": m(pb), "ridge": m(pr), "gbm": m(pg), "r_gbm": float(np.corrcoef(pg, y)[0, 1]), "within5_gbm": float((np.abs(pg - y) <= 5).mean())}
            L.append(f"| {nm} | {m(pb):.2f} | {m(pr):.2f} | {m(pg):.2f} | {res[sex][k]['r_gbm']:.2f} | {res[sex][k]['within5_gbm']*100:.0f}% |")
            gbm.fit(Xp, y); joblib.dump({"model": gbm, "cols": base_cols + photo_cols}, os.path.join(MODELS, f"body_photo_{sex}_{k}.joblib"))
        # 체형 지표 직접 예측: 남 = 드롭(가슴−허리), 여 = 가슴/엉덩이 → 3분위 유형 일치율
        from body_thresholds import group_of
        shape = (d.chest - d.waist_size).values if sex == "M" else (d.chest / d.hip_seize).values
        t_grp = [group_of(sex, c, w, h) for c, w, h in zip(d.chest, d.waist_size, d.hip_seize)]
        def grp_from_shape(v):     # 지표값 → 유형 (같은 3분위 기준)
            fake = (lambda x: (x + 80, 80, 90)) if sex == "M" else (lambda x: (x * 90, 70, 90))
            return [group_of(sex, *fake(x)) for x in v]
        rows = []
        for label, X in (("키·몸무게만", Xb), ("+사진 Ridge", Xp), ("+사진 GBM", Xp)):
            mdl = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8, random_state=0) if "GBM" in label else make_pipeline(StandardScaler(), Ridge(3.0 if "사진" in label else 1.0))
            p = cross_val_predict(mdl, X, shape, cv=cv)
            acc = float(np.mean(np.array(grp_from_shape(p)) == np.array(t_grp))); r = float(np.corrcoef(p, shape)[0, 1])
            rows.append(f"| {label} | {np.abs(p - shape).mean():.2f} | {r:.2f} | {acc*100:.1f}% |")
            res[sex][f"shape_{label}"] = {"mae": float(np.abs(p - shape).mean()), "r": r, "group_acc": acc}
        L += ["", f"체형 지표({'드롭 cm' if sex == 'M' else '가슴/엉덩이'}) 직접 예측 → 3분위 유형 일치율 (찍기 33%)", "", "| 입력 | 지표 MAE | r | 유형 일치율 |", "|---|---|---|---|"] + rows
        # 사진 특징 중요도 (허리 GBM)
        gbm = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8, random_state=0).fit(Xp, d["waist_size"].values)
        imp = sorted(zip(base_cols + photo_cols, gbm.feature_importances_), key=lambda t: -t[1])[:10]
        L += ["", "허리둘레 GBM 특징 중요도 상위: " + ", ".join(f"{c} {v:.2f}" for c, v in imp), ""]
    io.open(os.path.join(OUT, "body_train.md"), "w", encoding="utf-8").write("\n".join(L))
    io.open(os.path.join(OUT, "body_train.json"), "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    print("\n".join(L))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["extract", "train"]); ap.add_argument("--n", type=int, default=600); ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    extract(a.n, a.seed) if a.cmd == "extract" else train()
