"""
사진 → 다리 비율(leg: 숏/보통/롱) 보정 — AI Hub 의류 통합 데이터 착용자의 실측 허리높이÷키로 "사진의 다리 비율이 실제를 반영하나"를 본다.

  배경: 엔진 L 규칙(L1~L6, C8)은 leg 가 숏/롱일 때만 켜지는데, 웹·API 는 지금까지 항상 '보통'을 넣어 규칙이 꺼져 있었다.
  승민님 분석기는 이미 leg_to_pose_height_ratio (골반 관절~발목 ÷ 코~발목) 를 계산한다 — 이 값이 실측과 맞는지,
  맞으면 어디서 숏/롱을 자를지(성별 3분위)를 정한다.
  정답 = 실측 허리높이 ÷ 키 (성별 3분위: 하위 숏 · 상위 롱)

  .\.venv\Scripts\python.exe calibrate_leg.py [--n 1500] [--seed 2]
출력: runs/leg_calib.md — 사진·개인정보 저장 없음
결과(10/27, 2181명): 순위상관 남 -0.01 · 여 0.05, 3분위 일치 32~34% (찍기 33%) → 사진 다리 비율은 실측을 반영하지 못함. leg 는 계속 '보통'
"""
import argparse, json, math, os, time, zipfile
import numpy as np, pandas as pd

import body_cluster_bridge as bcb
from calibrate_photo import _modules
from validate_body import pick, img_zip
from validate_cluster import kappa, spearman

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "runs")


def leg_feats(an, detector, img_bytes):
    import mediapipe as mp, cv2
    image = an.decode(img_bytes); h, w = image.shape[:2]
    res = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))))
    if len(res.pose_landmarks) != 1: return None
    lm = res.pose_landmarks[0]
    P = {n: (lm[i].x * w, lm[i].y * h, float(lm[i].visibility or 0)) for n, i in an.INDEX.items()}
    if min(P[k][2] for k in ("LEFT_ANKLE", "RIGHT_ANKLE", "LEFT_HIP", "RIGHT_HIP")) < 0.5: return None
    top = P["NOSE"][1]; ank = (P["LEFT_ANKLE"][1] + P["RIGHT_ANKLE"][1]) / 2; hip = (P["LEFT_HIP"][1] + P["RIGHT_HIP"][1]) / 2
    ph = ank - top
    if ph < 100: return None
    leg = (math.dist(P["LEFT_HIP"][:2], P["LEFT_ANKLE"][:2]) + math.dist(P["RIGHT_HIP"][:2], P["RIGHT_ANKLE"][:2])) / 2
    return {"leg_mp": leg / ph, "leg_y": (ank - hip) / ph}   # leg_mp = 승민님 leg_to_pose_height_ratio 와 같은 정의


def tert(v, lo, hi): return np.where(v < lo, 0, np.where(v > hi, 2, 1))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=1500); ap.add_argument("--seed", type=int, default=2); a = ap.parse_args()
    _, an = _modules()
    import mediapipe as mp
    from pathlib import Path
    det = mp.tasks.vision.PoseLandmarker.create_from_options(mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_buffer=(Path(bcb.HERE) / "body_models" / "pose_landmarker_lite.task").read_bytes()),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=2, min_pose_detection_confidence=.5, min_pose_presence_confidence=.5))
    sel = pick(a.n, a.seed)
    meta = pd.read_csv(os.path.join(HERE, "data", "clothes_meta.csv"), dtype=str, keep_default_na=False).set_index("name")["waist_height"]
    zips, members, rows, t0 = {}, {}, [], time.time()
    for i, r in enumerate(sel.itertuples(index=False)):
        p = img_zip(r.split, r.category)
        if p not in zips: zips[p] = zipfile.ZipFile(p); members[p] = {os.path.basename(x): x for x in zips[p].namelist()}
        nm = members[p].get(r.name + ".jpg"); wh = pd.to_numeric(meta.get(r.name), errors="coerce")
        if nm is None or not wh == wh: continue
        try: f = leg_feats(an, det, zips[p].read(nm))
        except Exception: f = None
        if f: rows.append(dict(sex="M" if r.gender == "MALE" else "F", truth=float(wh) / float(r.body_height), **f))
        if (i + 1) % 300 == 0: print(f"  {i+1}/{len(sel)} {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    L = ["# 사진 다리 비율 ↔ 실측 허리높이/키", "", f"AI Hub 의류 통합 데이터 착용 컷, 발목·골반이 보이는 {len(df)}명 (남 {(df.sex=='M').sum()} / 여 {(df.sex=='F').sum()}). 찍기 기준 3분위 일치율 33%.", "",
         "| 성별 | 사진 특징 | 순위상관 | 3분위 일치율 | 카파 | 숏↔롱 반대로 판정 |", "|---|---|---|---|---|---|"]
    th = {"_doc": "사진 leg_to_pose_height_ratio(골반 관절~발목 ÷ 코~발목)의 성별 3분위. < lo 숏 · > hi 롱 · 그 외 보통. calibrate_leg.py"}
    for sx in ("M", "F"):
        d = df[df.sex == sx]; t = tert(d.truth.values, *np.quantile(d.truth, [1 / 3, 2 / 3]))
        for k in ("leg_mp", "leg_y"):
            lo, hi = np.quantile(d[k], [1 / 3, 2 / 3]); p = tert(d[k].values, lo, hi)
            L.append(f"| {sx} | `{k}` | {spearman(d[k].values, d.truth.values):.2f} | {(p == t).mean():.1%} | {kappa(list(t), list(p), (0, 1, 2)):.2f} | {((p - t) ** 2 == 4).mean():.1%} |")
        lo, hi = np.quantile(d.leg_mp, [1 / 3, 2 / 3])
        th[sx] = {"lo": round(float(lo), 4), "hi": round(float(hi), 4), "n": int(len(d)), "spearman": round(float(spearman(d.leg_mp.values, d.truth.values)), 3)}
    L += ["", "숏/롱 문턱(사진 `leg_mp` 3분위): " + " · ".join(f"{s} < {th[s]['lo']} 숏, > {th[s]['hi']} 롱" for s in ("M", "F"))]
    open(os.path.join(OUT, "leg_calib.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
