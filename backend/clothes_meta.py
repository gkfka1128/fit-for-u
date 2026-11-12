"""
AI Hub 「의류 통합 데이터(착용 이미지, 치수 및 원단 정보)」 라벨 → 표 하나 (data/clothes_meta.csv)

  라벨 zip 24개(Training/Validation × 12 카테고리) 의 JSON 55만 개에서
  착용자(성별·나이·키·가슴·허리·엉덩이·어깨·팔·등길이·체중·평소 사이즈) + 의류(종류·계절·색·기장·소매·넥·실루엣·소재·신축) + 의류 실측 치수
  를 한 행으로. 사진 종류 view = wear(착용 전신) / front / back(옷 단품).

  .\.venv\Scripts\python.exe clothes_meta.py            # 3~4분
출력: data/clothes_meta.csv, data/clothes_meta_summary.md
"""
import collections, csv, io, json, os, re, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROOT = os.path.join(HERE, "..", "Data", "008.의류 통합 데이터(착용 이미지, 치수 및 원단 정보)", "01-1.정식개방데이터")
OUT = os.path.join(DATA, "clothes_meta.csv")

MODEL_KEYS = ["gender", "age", "job", "usually_size", "body_height", "waist_height", "chest_size_male", "breast_size_female", "waist_size", "hip_seize", "back_length", "shoulders_width", "arm_length", "weight"]
CLOTH_KEYS = ["type", "season", "color", "top_length_type", "sleeve_length_type", "topneck_color_design", "topsleeve_design", "pants_silhouette", "skirt_design", "fiber_composition", "elasticity", "transparency", "isfleece"]
GARMENT_KEYS = ["top.front_length", "top.chest_size", "top.waist_size", "top.hem_size", "top.shoulder_width", "top.sleeve_length",
                "pants.pants_length", "pants.waist_size", "pants.hip_size", "pants.inner_seam_length",
                "skirt.length", "skirt.waist_size", "skirt.hip_size", "dress.front_length", "dress.chest_size", "dress.waist_size", "dress.hip_size"]
COLS = ["name", "split", "zip", "wearer", "img", "view", "part", "category", "sex", "width", "height"] + MODEL_KEYS + CLOTH_KEYS + [k.replace(".", "_") for k in GARMENT_KEYS]

def nz(v):
    return "" if v in (None, "null", "None") else v

def label_zips():
    for split in ("Training", "Validation"):
        d = os.path.join(ROOT, split, "02.라벨링데이터")
        for f in sorted(os.listdir(d)):
            if f.endswith(".zip"): yield split.lower()[:5], os.path.join(d, f)

def main():
    t0 = time.time(); n = 0
    os.makedirs(DATA, exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="") as fo:
        w = csv.writer(fo); w.writerow(COLS)
        for split, zp in label_zips():
            z = zipfile.ZipFile(zp); names = [x for x in z.namelist() if x.endswith(".json")]
            for nm in names:
                try: d = json.loads(z.read(nm).decode("utf-8"))
                except Exception: continue
                base = os.path.basename(nm)[:-5]
                f = base.split("_")                       # 01_sou_000255_001274_wear_02top_01blouse_woman
                m = d.get("metadata.model", {}); c = d.get("metadata.clothes", {}); ds = d.get("dataset", {})
                view = f[4] if len(f) > 4 else ""; sex = f[-1]
                part = f[5] if len(f) > 6 else ""; cat = f[6] if len(f) > 7 else f[5] if len(f) > 5 else ""
                row = [base, split, os.path.basename(zp), f[2] if len(f) > 2 else "", f[3] if len(f) > 3 else "", view, part, cat, sex, ds.get("dataset.width", ""), ds.get("dataset.height", "")]
                row += [nz(m.get(f"metadata.model.{k}", "")) for k in MODEL_KEYS]
                row += [nz(c.get(f"metadata.clothes.{k}", "")) for k in CLOTH_KEYS]
                row += [nz(c.get(f"metadata.{k}", "")) for k in GARMENT_KEYS]
                w.writerow(row); n += 1
            print(f"  {os.path.basename(zp)}: {len(names):,}  (누적 {n:,}, {time.time()-t0:.0f}s)", flush=True)
    print(f"rows {n:,} → {OUT}")
    summary()

def summary():
    import pandas as pd
    df = pd.read_csv(OUT, dtype=str, keep_default_na=False)
    for k in ["body_height", "waist_size", "hip_seize", "shoulders_width", "weight", "chest_size_male", "breast_size_female"]:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    df["chest"] = df["chest_size_male"].fillna(df["breast_size_female"])
    wear = df[df.view == "wear"]
    key = ["gender", "age", "body_height", "waist_size", "hip_seize", "shoulders_width", "weight", "chest"]
    people = wear.drop_duplicates(subset=key)
    L = ["# 의류 통합 데이터 요약", "", f"- 라벨 {len(df):,} 행 (train {int((df.split=='train').sum()):,} / val {int((df.split=='valid').sum()):,}), 착용 사진(wear) {len(wear):,}",
         f"- 성별 (전체 행): " + ", ".join(f"{k} {v:,}" for k, v in df.gender.value_counts().items()),
         f"- 성별 (착용 사진): " + ", ".join(f"{k} {v:,}" for k, v in wear.gender.value_counts().items()),
         f"- **착용자(고유 치수 조합) {len(people):,}명**: " + ", ".join(f"{k} {v:,}" for k, v in people.gender.value_counts().items()),
         f"- 착용자 나이대: " + ", ".join(f"{k} {v}" for k, v in people.age.value_counts().items()), ""]
    for g in ("MALE", "FEMALE"):
        p = people[people.gender == g]
        L.append(f"## {g} 착용자 {len(p)}명 — 실측 분포 (평균 ± 표준편차)")
        L.append("| 항목 | 평균 | 표준편차 | 최소 | 최대 |"); L.append("|---|---|---|---|---|")
        for k, nm in (("body_height", "키"), ("weight", "체중"), ("chest", "가슴둘레"), ("waist_size", "허리둘레"), ("hip_seize", "엉덩이둘레"), ("shoulders_width", "어깨너비")):
            s = p[k].dropna(); L.append(f"| {nm} | {s.mean():.1f} | {s.std():.1f} | {s.min():.0f} | {s.max():.0f} |")
        L.append("")
    L.append("## 카테고리 × 성별 (착용 사진)"); L.append("| 카테고리 | 여 | 남 |"); L.append("|---|---|---|")
    ct = wear.groupby(["category", "gender"]).size().unstack(fill_value=0)
    for cat, r in ct.iterrows(): L.append(f"| {cat} | {r.get('FEMALE', 0):,} | {r.get('MALE', 0):,} |")
    L.append("")
    for k in ("color", "season", "top_length_type", "sleeve_length_type", "topneck_color_design", "pants_silhouette", "skirt_design", "usually_size"):
        L.append(f"## {k} × 성별 (착용 사진)"); L.append("| 값 | 여 | 남 |"); L.append("|---|---|---|")
        ct = wear[wear[k] != ""].groupby([k, "gender"]).size().unstack(fill_value=0).sort_values("FEMALE", ascending=False)
        for v, r in ct.head(25).iterrows(): L.append(f"| {v} | {r.get('FEMALE', 0):,} | {r.get('MALE', 0):,} |")
        L.append("")
    io.open(os.path.join(DATA, "clothes_meta_summary.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[:8]))

if __name__ == "__main__":
    main()
