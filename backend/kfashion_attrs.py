"""
K-Fashion 라벨 96.8만 장 파싱 → 속성 사전.
  data/kfashion_labels.pkl  이미지별 {id, file, split, style, parts{부위:[속성dict]}, rect{부위:[[x,y,w,h]]}}  (다른 스크립트가 공용)
  data/kfashion_attrs.json  부위별 속성 값·빈도  /  data/kfashion_attrs.md 요약

  .\.venv\Scripts\python.exe kfashion_attrs.py     (Data/K-Fashion 이미지 필요, 수 분)
"""
import io, json, os, pickle, sys, time, zipfile, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROOT = os.path.abspath(os.path.join(HERE, "..", "Data", "K-Fashion 이미지"))
ZIPS = {"train": os.path.join(ROOT, "Training", "라벨링데이터.zip"), "valid": os.path.join(ROOT, "Validation", "라벨링데이터.zip")}
PARTS = ["상의", "하의", "아우터", "원피스"]


def clean(d):
    return {k: v for k, v in d.items() if v not in (None, "", [])}


def parse(raw, split):
    d = json.loads(raw.decode("utf-8"))
    info = d["이미지 정보"]; ds = d["데이터셋 정보"]["데이터셋 상세설명"]
    lab, rect = ds.get("라벨링", {}), ds.get("렉트좌표", {})
    parts, rects = {}, {}
    for p in PARTS:
        items = [clean(x) for x in lab.get(p, []) if clean(x)]
        if items:
            parts[p] = items
            rects[p] = [[x["X좌표"], x["Y좌표"], x["가로"], x["세로"]] for x in rect.get(p, []) if x.get("가로")]
    style = [clean(x) for x in lab.get("스타일", []) if clean(x)]
    return {"id": info["이미지 식별자"], "file": info["이미지 파일명"], "w": info["이미지 너비"], "h": info["이미지 높이"],
            "split": split, "style": style, "parts": parts, "rect": rects}


def main():
    os.makedirs(DATA, exist_ok=True); t0 = time.time(); recs = []
    pk = os.path.join(DATA, "kfashion_labels.pkl")
    for split, zp in ({} if os.path.exists(pk) and "--reparse" not in sys.argv else ZIPS).items():
        z = zipfile.ZipFile(zp)
        names = [n for n in z.namelist() if n.endswith(".json")]
        print(f"{split}: {len(names):,} 파일", flush=True)
        for i, n in enumerate(names):
            try: recs.append(parse(z.read(n), split))
            except Exception as e: print("skip", n, e)
            if (i + 1) % 100000 == 0: print(f"  {i+1:,}  {time.time()-t0:.0f}s", flush=True)
    if recs:
        with open(pk, "wb") as f: pickle.dump(recs, f, protocol=4)
    else:
        with open(pk, "rb") as f: recs = pickle.load(f)
    attrs = {p: collections.defaultdict(collections.Counter) for p in PARTS + ["스타일"]}
    for r in recs:
        for p, its in r["parts"].items():
            for it in its:
                for k, v in it.items():
                    for x in (v if isinstance(v, list) else [v]): attrs[p][k][x] += 1
        for it in r["style"]:
            for k, v in it.items(): attrs["스타일"][k][v] += 1
    out = {p: {k: dict(c.most_common()) for k, c in d.items()} for p, d in attrs.items()}
    io.open(os.path.join(DATA, "kfashion_attrs.json"), "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    lines = ["# K-Fashion 속성 사전", "", f"이미지 {len(recs):,} 장 (train {sum(r['split']=='train' for r in recs):,} / valid {sum(r['split']=='valid' for r in recs):,})", ""]
    for p, d in out.items():
        lines.append(f"## {p}")
        for k, c in d.items(): lines.append(f"- **{k}** ({len(c)}종): " + ", ".join(f"{v} {n:,}" for v, n in list(c.items())[:12]))
        lines.append("")
    io.open(os.path.join(DATA, "kfashion_attrs.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"완료 {len(recs):,}장 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
