"""
사진 → 실측 체형 보정 실험 — AI Hub 의류 통합 데이터 착용자 실측으로 "사진에서 무엇을 재야 실제 몸을 반영하는가"를 찾는다.

  배경 (runs/cluster_val.md): 웹 경로의 사진 가슴/엉덩이 너비비 U 는 실측 둘레비와 순위상관 0.04~0.08, 눈금도 모델의 1.5배.
    추정 원인: 승민님 추출기는 어깨~골반의 25% 높이에서 실루엣 가로폭을 재는데, 팔을 내린 사진이면 위팔까지 '가슴'에 들어간다.
  ① extract : 사람마다 얇은 옷 정면 컷 1장 → MediaPipe(승민님 분석기의 detector·마스크 그대로) → 특징을 CSV 로 (사진은 메모리에서만)
       특징 = 랜드마크 거리(어깨·골반 관절 폭, 몸통 길이) + 실루엣 가로폭 프로필(몸통 -10%~130% 높이 15단) + 팔 제외 폭(어깨 관절 안쪽만)
  ② fit     : 성별마다 사람 단위 5-fold CV — (a) 키·몸무게·나이 (b) 사진만 (c) 둘 다 → 실측 체형 지표(남 드롭 · 여 가슴/엉덩이) 예측
       지표: 순위상관, 3분위 일치율·카파 (예측값도 3분위로 잘라 비교 — 정답이 3분위라 같은 규칙)

  .\.venv\Scripts\python.exe calibrate_photo.py extract [--n 2000] [--seed 1]
  .\.venv\Scripts\python.exe calibrate_photo.py fit
출력: runs/photo_feats.csv (사람별 특징·실측, 이미지 없음), runs/photo_calib.md
"""
import argparse, json, math, os, sys, time, zipfile
import numpy as np, pandas as pd

import body_cluster_bridge as bcb
from validate_body import pick, img_zip
from validate_cluster import truth, kappa, spearman

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "runs")
FEATS = os.path.join(OUT, "photo_feats.csv")
LEVELS = [round(-0.1 + 0.1 * i, 2) for i in range(15)]          # 어깨선 -10% ~ 골반선 +30%


def _modules():
    ours = sys.modules.get("body_features")
    feat = bcb._load("ffu_body_models_features", "body_features.py")
    sys.modules["body_features"] = feat
    try:
        an = bcb._load("ffu_body_models_analyzer", "mediapipe_bodypose_analyzer.py")
    finally:
        if ours is not None: sys.modules["body_features"] = ours
        else: sys.modules.pop("body_features", None)
    return feat, an


def span(mask, y, x0, x1=None):
    """y 줄에서 몸통 축(x0)과 이어진 마스크 구간 [l, r]. x1 이 있으면 (l, r) 를 [x0-x1, x0+x1] 로 잘라 팔 제외 폭"""
    h, w = mask.shape
    y = int(np.clip(round(y), 0, h - 1)); row = mask[y] > 0; x = int(np.clip(round(x0), 0, w - 1))
    if not row[x]: return None
    l = x
    while l > 0 and row[l - 1]: l -= 1
    r = x
    while r < w - 1 and row[r + 1]: r += 1
    return (l, r)


def features(feat, an, detector, img_bytes):
    import mediapipe as mp, cv2
    image = an.decode(img_bytes); h, w = image.shape[:2]
    res = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))))
    if len(res.pose_landmarks) != 1 or not res.segmentation_masks: return None, "pose"
    lm = res.pose_landmarks[0]
    P = {n: dict(x=lm[i].x * w, y=lm[i].y * h, visibility=float(lm[i].visibility or 0)) for n, i in an.INDEX.items()}
    prob = np.asarray(res.segmentation_masks[0].numpy_view()).squeeze()
    if prob.shape != (h, w): prob = cv2.resize(prob, (w, h))
    q = feat.inspect_photo({k: {**v, "x": round(v["x"]), "y": round(v["y"])} for k, v in P.items()}, image, "front")
    try: mask = an.refine_mask(prob, {k: {**v, "x": round(v["x"]), "y": round(v["y"])} for k, v in P.items()}, "front")
    except ValueError: return None, "mask"
    ph = feat.pose_height({k: {**v, "x": round(v["x"]), "y": round(v["y"])} for k, v in P.items()}, "front")
    if not ph or ph < 100: return None, "height"
    ls, rs, lh, rh = P["LEFT_SHOULDER"], P["RIGHT_SHOULDER"], P["LEFT_HIP"], P["RIGHT_HIP"]
    sx, sy = (ls["x"] + rs["x"]) / 2, (ls["y"] + rs["y"]) / 2; hx, hy = (lh["x"] + rh["x"]) / 2, (lh["y"] + rh["y"]) / 2
    trunk = hy - sy
    if trunk < 25: return None, "trunk"
    shw, hipw = math.dist((ls["x"], ls["y"]), (rs["x"], rs["y"])), math.dist((lh["x"], lh["y"]), (rh["x"], rh["y"]))
    f = {"q": q["status"] if not q["errors"] else "RETAKE", "lm_shoulder": shw / ph, "lm_hip": hipw / ph, "lm_sh_hip": shw / max(hipw, 1),
         "trunk": trunk / ph, "aspect": w / h}
    # 팔이 몸통에 붙었는지: 팔꿈치·손목이 어깨 관절 바깥으로 얼마나 벌어졌나
    f["arm_open"] = (abs(P["LEFT_WRIST"]["x"] - P["RIGHT_WRIST"]["x"]) - shw) / ph
    for lv in LEVELS:
        y = sy + trunk * lv; x = sx + (hx - sx) * lv; s = span(mask, y, x)
        f[f"w{lv:+.1f}"] = (s[1] - s[0]) / ph if s else np.nan
        half = shw * 0.55                                                            # 어깨 관절 폭의 110% 안쪽만 = 팔 제외 근사
        f[f"in{lv:+.1f}"] = (min(s[1], x + half) - max(s[0], x - half)) / ph if s else np.nan
    return f, None


def extract(a):
    feat, an = _modules()
    import mediapipe as mp
    from pathlib import Path
    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_buffer=(Path(bcb.HERE) / "body_models" / "pose_landmarker_lite.task").read_bytes()),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=2, output_segmentation_masks=True,
        min_pose_detection_confidence=.5, min_pose_presence_confidence=.5)
    det = mp.tasks.vision.PoseLandmarker.create_from_options(opts)
    sel = pick(a.n, a.seed); print(f"선택 {len(sel)}명", flush=True)
    zips, members, rows, t0, fails = {}, {}, [], time.time(), {}
    for i, r in enumerate(sel.itertuples(index=False)):
        p = img_zip(r.split, r.category)
        if p not in zips: zips[p] = zipfile.ZipFile(p); members[p] = {os.path.basename(x): x for x in zips[p].namelist()}
        nm = members[p].get(r.name + ".jpg")
        if nm is None: continue
        sex = "M" if r.gender == "MALE" else "F"
        try: f, why = features(feat, an, det, zips[p].read(nm))
        except Exception as e: f, why = None, type(e).__name__
        if f is None: fails[why] = fails.get(why, 0) + 1; continue
        tg, tb, tv = truth(sex, float(r.chest), float(r.waist_size), float(r.hip_seize), float(r.body_height), float(r.weight))
        rows.append(dict(name=r.name, sex=sex, age=int(str(r.age)[:2]) if str(r.age)[:2].isdigit() else np.nan,
                         height=float(r.body_height), weight=float(r.weight), chest=float(r.chest), waist=float(r.waist_size),
                         hip=float(r.hip_seize), shoulder=float(r.shoulders_width), t_group=tg, t_value=tv, **f))
        if (i + 1) % 200 == 0: print(f"  {i+1}/{len(sel)}  {time.time()-t0:.0f}s  실패 {fails}", flush=True)
    pd.DataFrame(rows).to_csv(FEATS, index=False, encoding="utf-8-sig")
    print(f"저장 {len(rows)}명 · 실패 {fails} · {time.time()-t0:.0f}s")


def tertile(v, ref):
    lo, hi = np.quantile(ref, [1 / 3, 2 / 3])
    return np.where(v > hi, "상체형", np.where(v > lo, "균형", "하체형"))


def fit(a):
    from sklearn.linear_model import RidgeCV
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import KFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    df = pd.read_csv(FEATS)
    photo = [c for c in df.columns if c.startswith(("lm_", "w+", "w-", "in+", "in-")) or c in ("trunk", "arm_open")]
    for c in [c for c in photo if c.startswith(("w", "in"))]:                       # 폭 비율 (골반 폭 대비) 도 추가
        if c not in ("w+1.0", "in+1.0"): df[c + "/hip"] = df[c] / df["w+1.0"]; photo.append(c + "/hip")
    base = ["height", "weight", "bmi", "age"]
    df["bmi"] = df.weight / (df.height / 100) ** 2
    sets = {"키·몸무게·나이": base, "사진만": photo, "키·몸무게 + 사진": base + photo}
    L = ["# 사진 → 실측 체형 보정 실험", "",
         f"AI Hub 의류 통합 데이터, 특징 추출 성공 {len(df)}명 (남 {int((df.sex == 'M').sum())} / 여 {int((df.sex == 'F').sum())}), 사람 단위 5-fold CV.",
         "목표 = 실측 체형 지표 (남 가슴−허리 드롭 cm · 여 가슴/엉덩이 둘레비). 3분위 일치율의 찍기 기준 33%.", ""]
    L += ["## 1. 무엇으로 예측하나 — 순위상관 · 3분위 일치율 · 카파", "",
          "| 성별 | 입력 | 모델 | 순위상관 | 3분위 일치율 | 카파 |", "|---|---|---|---|---|---|"]
    best = {}
    for s in ("M", "F"):
        d = df[df.sex == s].reset_index(drop=True); y = d.t_value.values
        for name, cols in sets.items():
            X = d[cols].astype(float)
            for mname, mk in (("Ridge", lambda: make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-2, 3, 12)))),
                              ("GBM", lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0))):
                pred = np.zeros(len(d))
                for tr, te in KFold(5, shuffle=True, random_state=0).split(X):
                    m = mk(); Xtr, Xte = X.iloc[tr], X.iloc[te]
                    if mname == "Ridge": Xtr, Xte = Xtr.fillna(Xtr.median()), Xte.fillna(Xtr.median())
                    m.fit(Xtr, y[tr]); pred[te] = m.predict(Xte)
                pg = tertile(pred, pred); r = spearman(list(pred), list(y))
                acc = float((pg == d.t_group.values).mean()); k = kappa(list(d.t_group), list(pg), ("상체형", "균형", "하체형"))
                L.append(f"| {'남' if s == 'M' else '여'} | {name} | {mname} | **{r:.2f}** | {100 * acc:.1f}% | {k:.2f} |")
                if name != "키·몸무게·나이" and r > best.get(s, (-9,))[0]: best[s] = (r, name, mname)
    L += ["", "## 2. 사진 특징 하나씩 — 실측 지표와의 순위상관 (상위 8개)", "", "| 성별 | 특징 | 순위상관 | 비고 |", "|---|---|---|---|"]
    for s in ("M", "F"):
        d = df[df.sex == s]
        cs = sorted(((spearman(list(d[c].astype(float).fillna(d[c].median())), list(d.t_value)), c) for c in photo), key=lambda t: -abs(t[0]))[:8]
        for r, c in cs: L.append(f"| {'남' if s == 'M' else '여'} | `{c}` | {r:.2f} | |")
    L += ["", "## 3. 웹 추출기의 '가슴' 위치에 팔이 들어가는가", "",
          "| 성별 | 가슴 높이(25%) 실루엣 폭 ÷ 어깨 관절 폭 (중앙값) | 팔 제외 폭 ÷ 어깨 관절 폭 | 손목 벌림 (키 대비, 중앙값) |", "|---|---|---|---|"]
    for s in ("M", "F"):
        d = df[df.sex == s]
        L.append(f"| {'남' if s == 'M' else '여'} | {np.nanmedian(d['w+0.2'] / d.lm_shoulder):.2f} | {np.nanmedian(d['in+0.2'] / d.lm_shoulder):.2f} | {np.nanmedian(d.arm_open):.2f} |")
    L += ["", "실루엣 폭이 어깨 관절 폭보다 크게 넓으면 위팔이 몸통 폭에 포함된 것 (어깨 관절 폭 ≈ 실제 어깨너비의 80% 수준).", ""]
    open(os.path.join(OUT, "photo_calib.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L)); print("best", best)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["extract", "fit"])
    ap.add_argument("--n", type=int, default=2000); ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(); {"extract": extract, "fit": fit}[a.cmd](a)
