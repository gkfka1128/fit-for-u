"""
남성 서브셋 — K-Fashion 에는 성별 라벨이 없으므로 CLIP 추정(kfashion_sex.py, p_male ≥ 임계값) 사진만 모아
남성용 통계·사진을 따로 만든다.

  1) 남성 사진 id 집합 (train / val)  + 스타일별 비율
  2) 라벨 스캔 → 남성 아이템 빈도 count_M (부위별), 남성 색 분포, 남성 코디 조합 → 사진 색인 (kfashion_photos 와 같은 형식)
  3) 평가: Validation 남성 코디 FITB — 인기도(전체) vs 인기도(남성 보정) vs 조합 모델
  통계는 p ≥ thr(0.8), 착장 사진 색인은 더 엄격한 p ≥ photo_thr(0.95) 만 (육안 확인: 0.8~0.95 구간은 절반쯤 숏컷 여성·마네킹).
  아이템 컷(thumbs_M)은 만들지 않는다 — 남성 추정 컷이 일반 컷보다 품질이 나빴다 (뒷모습·마네킹).

  .\.venv\Scripts\python.exe kfashion_male.py [--thr 0.8] [--photo-thr 0.95]
출력: data/kfashion_male.json, runs/male_eval.{json,md}
"""
import argparse, collections, csv, io, json, math, os, time, zipfile
import numpy as np
from PIL import Image
from kfashion_cooc import KEYS, first
from kfashion_photos import read_image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
ROOT = os.path.join(HERE, "..", "Data", "K-Fashion 이미지")
PARTS = ("상의", "하의", "아우터")
THUMBS = os.path.join(DATA, "thumbs_M")

def load_sex(thr, photo_thr):
    male = {"train": set(), "val": set()}; photo = set(); n = collections.Counter(); style = collections.defaultdict(lambda: [0, 0])
    with io.open(os.path.join(DATA, "kfashion_sex.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r["p_male"]: continue
            n[r["split"]] += 1; p = float(r["p_male"]); style[r["style"]][0] += 1
            if p >= thr: male[r["split"]].add(int(r["img_id"])); style[r["style"]][1] += 1
            if p >= photo_thr and r["split"] == "train": photo.add(int(r["img_id"]))
    return male, photo, n, style

def scan(split, male_ids, items, photo_ids=frozenset(), per_item=6, per_combo=8):
    key_of = lambda p, a: tuple(a.get(k) for k in KEYS[p])
    cand = {p: {key_of(p, it["attrs"]): i for i, it in enumerate(items[p])} for p in PARTS}
    zp = os.path.join(ROOT, "Training" if split == "train" else "Validation", "라벨링데이터.zip")
    z = zipfile.ZipFile(zp)
    count = {p: collections.Counter() for p in PARTS}; color = {p: collections.Counter() for p in PARTS}
    best = {p: collections.defaultdict(list) for p in PARTS}; combos = collections.defaultdict(list); outfits = []
    for nm in z.namelist():
        if not nm.lower().endswith(".json"): continue
        iid = int(os.path.splitext(os.path.basename(nm))[0])
        if iid not in male_ids: continue
        try:
            lab = json.loads(z.read(nm).decode("utf-8")); info = lab["이미지 정보"]; d = lab["데이터셋 정보"]["데이터셋 상세설명"]
        except Exception: continue
        W, H = info["이미지 너비"], info["이미지 높이"]; ids, cols, rects = {}, {}, {}
        for p in PARTS:
            lp = [x for x in d["라벨링"].get(p, []) if x]
            if not lp or not first(lp[0], "카테고리"): continue
            i = cand[p].get(key_of(p, {k: first(lp[0], k) for k in KEYS[p]}))
            if i is None: continue
            ids[p] = i; cols[p] = first(lp[0], "색상"); count[p][i] += 1
            if cols[p]: color[p][cols[p]] += 1
            rect = [r for r in d["렉트좌표"].get(p, []) if r]
            if rect and W and H:
                r = rect[0]; rects[p] = r; ratio = r["가로"] * r["세로"] / (W * H); b = best[p][i]
                if len(b) < per_item or ratio > b[-1][0]:
                    b.append((ratio, iid, [r["X좌표"], r["Y좌표"], r["가로"], r["세로"]])); b.sort(key=lambda t: -t[0]); del b[per_item:]
        if "상의" in ids and "하의" in ids:
            outfits.append({p: {"id": ids[p], "attrs": {k: first([x for x in d["라벨링"][p] if x][0], k) for k in KEYS[p]}} for p in ids})
            if iid in photo_ids and "상의" in rects and "하의" in rects and H:
                full = 2 - (rects["상의"]["Y좌표"] < 0.03 * H) - (rects["하의"]["Y좌표"] + rects["하의"]["세로"] > 0.97 * H) + 0.1 * (H >= 1000)
                k = f"{ids['상의']}-{ids['하의']}-{ids.get('아우터', -1)}"; b = combos[k]
                if len(b) < per_combo or full > b[-1][0]:
                    b.append((full, iid, cols.get("상의"), cols.get("하의"), cols.get("아우터"))); b.sort(key=lambda t: -t[0]); del b[per_combo:]
    return count, color, best, {k: [list(t[1:]) for t in v] for k, v in combos.items()}, outfits

def extract(best, max_side=360, margin=0.06):
    n = 0
    for p in PARTS:
        os.makedirs(os.path.join(THUMBS, p), exist_ok=True)
        for i, cuts in best[p].items():
            for _, iid, (x, y, w, h) in cuts:
                img = read_image(iid)
                if img is None: continue
                mx, my = w * margin, h * margin
                crop = img.crop(tuple(int(v) for v in (max(0, x - mx), max(0, y - my), min(img.width, x + w + mx), min(img.height, y + h + my))))
                crop.thumbnail((max_side, max_side)); crop.save(os.path.join(THUMBS, p, f"{i}.jpg"), "JPEG", quality=82); n += 1; break
    return n

def evaluate(eng, male_json, val_outfits):
    """남성 Validation 코디 FITB: 인기도(전체) / 인기도(남성 보정) / 조합 모델 / 조합 모델+남성 보정"""
    from train_compat import ctx_row, key_of
    res = {}
    for hidden in PARTS:
        given = [p for p in PARTS if p != hidden]
        pop = np.array([math.log10(it["count"]) for it in eng.items[hidden]])
        mlift = np.array([eng.male_lift(hidden, i) for i in range(len(eng.items[hidden]))])
        rows, truths = [], []
        for o in val_outfits:
            if hidden not in o: continue
            rows.append(ctx_row({p: o[p]["attrs"] for p in o}, given)); truths.append(o[hidden]["id"])
        if not rows: continue
        P = None
        if hidden in eng.compat:
            m = eng.compat[hidden]; Pm = m["clf"].predict_proba(m["enc"].transform(np.array(rows)))
            P = np.full((len(rows), len(eng.items[hidden])), 1e-9);
            for j, c in enumerate(m["clf"].classes_): P[:, c] = Pm[:, j]
        ranks = collections.defaultdict(list)
        for r, t in enumerate(truths):
            scores = {"popularity": pop, "popularity+male": pop + mlift}
            if P is not None: scores["model"] = np.log(P[r]); scores["model+male"] = np.log(P[r]) + mlift
            for mname, sc in scores.items():
                ranks[mname].append(int((sc > sc[t]).sum()) + 1 + int((sc == sc[t]).sum() - 1) / 2)
        res[hidden] = {"n": len(truths), **{m: {"hit@1": float(np.mean(np.array(v) <= 1)), "hit@5": float(np.mean(np.array(v) <= 5)), "hit@10": float(np.mean(np.array(v) <= 10)), "mrr": float(np.mean(1 / np.array(v)))} for m, v in ranks.items()}}
    return res

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--thr", type=float, default=0.8); ap.add_argument("--photo-thr", type=float, default=0.95); a = ap.parse_args()
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    male, photo, n, style = load_sex(a.thr, a.photo_thr)
    print(f"남성 추정(p≥{a.thr}): train {len(male['train']):,}/{n['train']:,} ({len(male['train'])/max(n['train'],1):.1%}), val {len(male['val']):,}/{n['val']:,};  사진용(p≥{a.photo_thr}) {len(photo):,}")
    t = time.time(); count, color, best, combos, tr_out = scan("train", male["train"], items, photo); print(f"train 남성 코디 {len(tr_out):,}, 사진 색인 조합 {len(combos):,} ({time.time()-t:.0f}s)")
    _, _, _, _, va_out = scan("val", male["val"], items); print(f"val 남성 코디 {len(va_out):,}")
    total = {p: sum(it["count"] for it in items[p]) for p in PARTS}; total_M = {p: sum(count[p].values()) for p in PARTS}
    out = {"threshold": a.thr, "photo_threshold": a.photo_thr, "n_images": {k: len(v) for k, v in male.items()}, "n_outfits": {"train": len(tr_out), "val": len(va_out)},
           "style_share": {s: {"n": v[0], "male": v[1], "ratio": round(v[1] / v[0], 4)} for s, v in sorted(style.items(), key=lambda kv: -kv[1][1])},
           "items": {p: {str(i): c for i, c in count[p].items()} for p in PARTS}, "total": total, "total_M": total_M,
           "color_prior": {p: dict(color[p].most_common()) for p in PARTS}, "combos": combos}
    io.open(os.path.join(DATA, "kfashion_male.json"), "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
    from rule_engine import RuleEngine
    eng = RuleEngine(); res = evaluate(eng, out, va_out); os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(OUT, "male_eval.json"), "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    L = [f"# 남성 서브셋 평가 (CLIP p_male ≥ {a.thr}, Validation 남성 코디 FITB)", "", f"train 남성 사진 {len(male['train']):,} / 코디 {len(tr_out):,},  val 남성 코디 {len(va_out):,},  착장 사진 색인(p≥{a.photo_thr}) {len(combos):,} 조합", ""]
    for h, r in res.items():
        L += [f"## {h} 가림 (n={r['n']})", "", "| 방법 | Hit@1 | Hit@5 | Hit@10 | MRR |", "|---|---|---|---|---|"]
        for m, v in r.items():
            if m == "n": continue
            L.append(f"| {m} | {v['hit@1']*100:.1f}% | {v['hit@5']*100:.1f}% | {v['hit@10']*100:.1f}% | {v['mrr']:.3f} |"); print(f"[{h}] {m:16s} hit@5 {v['hit@5']*100:5.1f}%  hit@10 {v['hit@10']*100:5.1f}%")
        L.append("")
    top = sorted(((p, i, c) for p in PARTS for i, c in count[p].items()), key=lambda t: -t[2])[:10]
    L += ["## 남성 사진에서 가장 많은 아이템", ""] + [f"- {p} #{i} {items[p][i]['attrs']} — {c}" for p, i, c in top]
    io.open(os.path.join(OUT, "male_eval.md"), "w", encoding="utf-8").write("\n".join(L)); print("saved data/kfashion_male.json, runs/male_eval.*")

if __name__ == "__main__":
    main()
