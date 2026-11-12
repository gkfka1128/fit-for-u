"""
체형 측정 검증 — AI Hub 의류 통합 데이터의 착용 사진(wear) + 착용자 실측 치수로 body_measure.py 를 채점한다

  착용자 3,154명(남 754 / 여 2,400)에게 키·가슴·허리·엉덩이둘레·어깨너비·체중이 라벨로 있다.
  → 사람마다 사진 1장(얇은 옷: 티셔츠·셔츠·팬츠 착용 컷)을 뽑아 measure(사진, 키, 체중, 성별) 를 돌리고
     ① 둘레 오차 (MAE·평균 편향·상관·±5cm 이내 비율)
     ② 3대 체형(상체형/균형/하체형) 분류 일치율 — 실측으로 계산한 정답 vs 사진으로 계산한 예측 (pipeline.to_body_json 과 같은 규칙)
  을 잰다. 팀원 30명 실측 검증셋(평가 프로토콜 B단계)의 대규모 선행판.

  .\.venv\Scripts\python.exe validate_body.py [--n 150] [--seed 0]     # 성별당 n명, 1장 ≈ 1.5초
출력: runs/body_val.csv (사람별), runs/body_val.md, runs/body_val.png, runs/body_val_samples.jpg
"""
import argparse, io, json, os, random, sys, time, zipfile, collections
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
ROOT = os.path.join(HERE, "..", "Data", "008.의류 통합 데이터(착용 이미지, 치수 및 원단 정보)", "01-1.정식개방데이터")
THIN = {"02t-shirt": "상의_t-shirt", "04shirt": "상의_shirt", "01pants": "하의_bottom"}     # 두꺼운 옷(코트·패딩)은 둘레를 부풀리므로 제외
KEY = ["gender", "age", "body_height", "waist_size", "hip_seize", "shoulders_width", "weight", "chest"]

def group_of(sex, bust, waist, hip):
    """pipeline.to_body_json 과 같은 3대 체형 규칙 (남: KS K 0050 드롭 / 여: 2026 논문 비율)"""
    if sex == "M":
        drop = bust - waist; return "상체형" if drop > 18.3 else "균형" if drop > 13.0 else "하체형"
    ch, hw = bust / hip, hip / waist
    return "상체형" if ch > 1.01 else "하체형" if hw > 1.22 else "균형"

def pick(n, seed):
    df = pd.read_csv(os.path.join(DATA, "clothes_meta.csv"), dtype=str, keep_default_na=False)
    for k in ["body_height", "waist_size", "hip_seize", "shoulders_width", "weight", "chest_size_male", "breast_size_female"]:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    df["chest"] = df["chest_size_male"].fillna(df["breast_size_female"])
    df = df[(df.view == "wear") & df.category.isin(THIN) & df.body_height.notna() & df.waist_size.notna() & df.hip_seize.notna() & df.chest.notna()]
    df = df[(df.body_height > 140) & (df.waist_size > 40) & (df.hip_seize > 60) & (df.chest > 60)]     # 라벨 오타 제거
    rng = random.Random(seed); rows = []
    for g in ("MALE", "FEMALE"):
        people = df[df.gender == g].groupby(KEY, dropna=False)
        keys = list(people.groups); rng.shuffle(keys)
        for k in keys[:n]:
            grp = people.get_group(k)
            pref = grp[grp.category == "02t-shirt"]                       # 티셔츠 컷 우선 (몸에 가장 가까움)
            rows.append((pref if len(pref) else grp).iloc[rng.randrange(len(pref) if len(pref) else len(grp))])
    return pd.DataFrame(rows)

def img_zip(split, category):
    d = os.path.join(ROOT, "Training" if split == "train" else "Validation", "01.원천데이터")
    return os.path.join(d, ("TS" if split == "train" else "VS") + "_상품_" + THIN[category] + ".zip")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=150); ap.add_argument("--seed", type=int, default=0); a = ap.parse_args()
    from body_measure import measure
    sel = pick(a.n, a.seed); print(f"선택 {len(sel)}명 (" + ", ".join(f"{k} {v}" for k, v in sel.gender.value_counts().items()) + ")")
    os.makedirs(OUT, exist_ok=True); tmp = os.path.join(OUT, "body_val_tmp"); os.makedirs(tmp, exist_ok=True)
    zips, members = {}, {}
    def get_zip(p):
        if p not in zips:
            zips[p] = zipfile.ZipFile(p); members[p] = {os.path.basename(x): x for x in zips[p].namelist()}
        return zips[p], members[p]
    res = []; t0 = time.time(); keep = []
    for i, r in enumerate(sel.itertuples(index=False)):
        z, mem = get_zip(img_zip(r.split, r.category)); nm = mem.get(r.name + ".jpg")
        if nm is None: continue
        p = os.path.join(tmp, r.name + ".jpg"); open(p, "wb").write(z.read(nm))
        sex = "M" if r.gender == "MALE" else "F"
        try:
            m = measure(p, float(r.body_height), float(r.weight) if r.weight == r.weight else None, sex)
        except (SystemExit, Exception) as e:
            res.append(dict(name=r.name, sex=sex, ok=False, err=str(e)[:80])); os.remove(p); continue
        c, w = m["circumference_cm"], m["width_cm"]
        res.append(dict(name=r.name, sex=sex, ok=True, age=r.age, category=r.category, height=r.body_height, weight=r.weight,
                        t_chest=r.chest, t_waist=r.waist_size, t_hip=r.hip_seize, t_shoulder=r.shoulders_width,
                        p_chest=c["bust"], p_waist=c["waist"], p_hip=c["hip"], p_shoulder=w["shoulder"],
                        t_group=group_of(sex, r.chest, r.waist_size, r.hip_seize), p_group=group_of(sex, c["bust"], c["waist"], c["hip"]),
                        warnings=" | ".join(m.get("warnings", [])), leg_ratio=m.get("leg_ratio")))
        if len(keep) < 8 and i % 37 == 0: keep.append(m["output_image"])
        else: os.remove(m["output_image"])
        os.remove(p)
        if (i + 1) % 25 == 0: print(f"  {i+1}/{len(sel)}  {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(res); df.to_csv(os.path.join(OUT, "body_val.csv"), index=False, encoding="utf-8-sig")
    ok = df[df.ok == True].copy()
    print(f"측정 성공 {len(ok)}/{len(df)}")

    # ---- 리포트
    L = [f"# 체형 측정 검증 — AI Hub 의류 통합 데이터 착용자 실측 vs body_measure.py", "",
         f"사람당 사진 1장(티셔츠·셔츠·팬츠 착용 컷), 성별당 {a.n}명 표본, seed {a.seed}. 측정 성공 {len(ok)}/{len(df)}. 실패 = 사람 검출 실패·전신 아님.", ""]
    summary = {}
    for sex in ("M", "F"):
        d = ok[ok.sex == sex]
        if not len(d): continue
        L += [f"## {'남성' if sex == 'M' else '여성'} n={len(d)}", "", "| 항목 | MAE (cm) | 평균 편향 (예측−실측) | 상관 r | ±5cm 이내 |", "|---|---|---|---|---|"]
        summary[sex] = {}
        for k, nm in (("chest", "가슴둘레"), ("waist", "허리둘레"), ("hip", "엉덩이둘레"), ("shoulder", "어깨너비")):
            e = d[f"p_{k}"] - d[f"t_{k}"]; r = np.corrcoef(d[f"p_{k}"], d[f"t_{k}"])[0, 1]
            summary[sex][k] = dict(mae=float(e.abs().mean()), bias=float(e.mean()), r=float(r), within5=float((e.abs() <= 5).mean()))
            L.append(f"| {nm} | {e.abs().mean():.1f} | {e.mean():+.1f} | {r:.2f} | {(e.abs() <= 5).mean()*100:.0f}% |")
        acc = float((d.t_group == d.p_group).mean()); summary[sex]["group_acc"] = acc
        ct = pd.crosstab(d.t_group, d.p_group)
        L += ["", f"**3대 체형 일치율 {acc*100:.1f}%** (실측 기준 정답 vs 사진 예측)", "", "| 실측 \\ 예측 | " + " | ".join(ct.columns) + " |", "|---|" + "---|" * len(ct.columns)]
        for idx, row in ct.iterrows(): L.append(f"| {idx} | " + " | ".join(str(v) for v in row) + " |")
        L.append(""); L.append("실측 기준 체형 분포: " + ", ".join(f"{k} {v}" for k, v in d.t_group.value_counts().items())); L.append("")
    wc = collections.Counter(w for ws in ok.warnings for w in ws.split(" | ") if w)
    if wc: L += ["## 경고 빈도", ""] + [f"- {w}: {c}" for w, c in wc.most_common()] + [""]
    io.open(os.path.join(OUT, "body_val.md"), "w", encoding="utf-8").write("\n".join(L))
    io.open(os.path.join(OUT, "body_val.json"), "w", encoding="utf-8").write(json.dumps(summary, ensure_ascii=False, indent=1))
    print("\n".join(L))

    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    matplotlib.rcParams["font.family"] = "Malgun Gothic"; matplotlib.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(2, 4, figsize=(15, 7))
    for row, sex in enumerate(("M", "F")):
        d = ok[ok.sex == sex]
        for ax, (k, nm) in zip(axes[row], (("chest", "가슴둘레"), ("waist", "허리둘레"), ("hip", "엉덩이둘레"), ("shoulder", "어깨너비"))):
            ax.scatter(d[f"t_{k}"], d[f"p_{k}"], s=8, alpha=0.5); lo, hi = d[f"t_{k}"].min(), d[f"t_{k}"].max(); ax.plot([lo, hi], [lo, hi], "k--", lw=1)
            s = summary.get(sex, {}).get(k, {}); ax.set_title(f"{'남' if sex == 'M' else '여'} {nm}  MAE {s.get('mae', 0):.1f}  r {s.get('r', 0):.2f}", fontsize=10)
            ax.set_xlabel("실측 (cm)"); ax.set_ylabel("사진 예측 (cm)")
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "body_val.png"), dpi=120)
    if keep:
        from PIL import Image
        ims = [Image.open(p) for p in keep]
        for im in ims: im.thumbnail((240, 420))
        sheet = Image.new("RGB", (sum(i.width for i in ims) + 6 * len(ims), max(i.height for i in ims)), "white"); x = 0
        for im in ims: sheet.paste(im, (x, 0)); x += im.width + 6
        sheet.save(os.path.join(OUT, "body_val_samples.jpg"), quality=85)
        for p in keep: os.remove(p)
    try: os.rmdir(tmp)
    except OSError: pass
    print("saved runs/body_val.{csv,md,json,png}, body_val_samples.jpg")

if __name__ == "__main__":
    main()
