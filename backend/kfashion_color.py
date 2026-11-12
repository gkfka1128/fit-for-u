"""
색상 통계 — K-Fashion 96.8만 코디에서 (1) 아이템별 색상 분포 (2) 부위 간 색상 조합 lift 를 뽑고, Validation 으로 색상 예측 정확도를 잰다.

  아이템별 색상 분포 P(색 | 아이템)   : "와이드 우븐 팬츠"는 블랙 31% · 베이지 18% …  → 추천 아이템에 붙일 색 후보
  색상 조합 lift  P(a,b)/P(a)P(b)   : 상의색×하의색, 아우터색×상의색, 아우터색×하의색
  평가 (FITB) : 하의 색을 가리고 상의 색 + 하의 아이템으로 21색 중 순위.  베이스라인 = 전체 색 인기도 / P(색|아이템)

  .\.venv\Scripts\python.exe kfashion_color.py
출력: data/kfashion_color.json, runs/color_eval.{json,md}
"""
import collections, io, json, math, os, time, zipfile
import numpy as np
from kfashion_cooc import KEYS, first

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
ROOT = os.path.join(HERE, "..", "Data", "K-Fashion 이미지")
PARTS = ("상의", "하의", "아우터")
PAIRS = [("상의", "하의"), ("아우터", "상의"), ("아우터", "하의")]

def load(split, limit=None):
    """코디 → {부위: (item id, 색)}  (후보 아이템에 있는 부위만)"""
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    key_of = lambda p, a: tuple(a.get(k) for k in KEYS[p])
    cand = {p: {key_of(p, it["attrs"]): i for i, it in enumerate(items[p])} for p in PARTS}
    zp = os.path.join(ROOT, "Training" if split == "train" else "Validation", "라벨링데이터.zip")
    z = zipfile.ZipFile(zp); names = [n for n in z.namelist() if n.lower().endswith(".json")]
    if limit: names = names[:limit]
    out = []
    for nm in names:
        try: lab = json.loads(z.read(nm).decode("utf-8"))["데이터셋 정보"]["데이터셋 상세설명"]["라벨링"]
        except Exception: continue
        o = {}
        for p in PARTS:
            lp = [x for x in lab.get(p, []) if x]
            if not lp or not first(lp[0], "카테고리"): continue
            i = cand[p].get(key_of(p, {k: first(lp[0], k) for k in KEYS[p]})); c = first(lp[0], "색상")
            if i is not None and c: o[p] = (i, c)
        if "상의" in o and "하의" in o: out.append(o)
    return out

def build(train):
    item_color = {p: collections.defaultdict(collections.Counter) for p in PARTS}
    pair = {f"{a}×{b}": collections.Counter() for a, b in PAIRS}
    marg = {f"{a}×{b}": (collections.Counter(), collections.Counter()) for a, b in PAIRS}
    for o in train:
        for p, (i, c) in o.items(): item_color[p][i][c] += 1
        for a, b in PAIRS:
            if a in o and b in o:
                k = f"{a}×{b}"; pair[k][(o[a][1], o[b][1])] += 1; marg[k][0][o[a][1]] += 1; marg[k][1][o[b][1]] += 1
    lift = {}
    for k, cnt in pair.items():
        n = sum(cnt.values()); ma, mb = marg[k]
        lift[k] = {f"{a}|{b}": round((v / n) / ((ma[a] / n) * (mb[b] / n)), 3) for (a, b), v in cnt.items() if v >= 30}
    colors = {p: collections.Counter() for p in PARTS}
    for p in PARTS:
        for i, cnt in item_color[p].items(): colors[p].update(cnt)
    return {"item_color": {p: {str(i): dict(cnt.most_common(6)) for i, cnt in item_color[p].items()} for p in PARTS},
            "color_prior": {p: dict(colors[p].most_common()) for p in PARTS},
            "lift": lift, "n_train": len(train)}

def evaluate(model, val):
    """하의 색 FITB: 상의 색 + 하의 아이템 주어짐, 21색 중 진짜 하의 색 순위"""
    res = {}
    for hidden, given in (("하의", "상의"), ("상의", "하의")):
        key = "상의×하의"; cols = list(model["color_prior"][hidden]); prior = np.array([model["color_prior"][hidden][c] for c in cols], float); prior /= prior.sum()
        ranks = {"prior": [], "item": [], "item+lift": []}
        for o in val:
            if hidden not in o or given not in o: continue
            i, truth = o[hidden]; gc = o[given][1]
            if truth not in cols: continue
            ic = model["item_color"][hidden].get(str(i), {}); tot = sum(ic.values()) or 1
            p_item = np.array([(ic.get(c, 0) + 0.5) / (tot + 0.5 * len(cols)) for c in cols])
            def lf(c):
                k = f"{gc}|{c}" if hidden == "하의" else f"{c}|{gc}"
                return model["lift"][key].get(k, 1.0)
            L = np.array([math.log(max(lf(c), 0.05)) for c in cols])
            t = cols.index(truth)
            for m, sc in (("prior", np.log(prior)), ("item", np.log(p_item)), ("item+lift", np.log(p_item) + L)):
                ranks[m].append(int((sc > sc[t]).sum()) + 1 + int((sc == sc[t]).sum() - 1) / 2)
        res[hidden] = {m: {"n": len(r), "hit@1": float(np.mean(np.array(r) <= 1)), "hit@3": float(np.mean(np.array(r) <= 3)), "mrr": float(np.mean(1 / np.array(r)))} for m, r in ranks.items()}
    return res

def main():
    t = time.time(); train = load("train"); print(f"train {len(train):,} ({time.time()-t:.0f}s)")
    model = build(train); os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(DATA, "kfashion_color.json"), "w", encoding="utf-8").write(json.dumps(model, ensure_ascii=False))
    val = load("val"); print(f"val {len(val):,}")
    res = evaluate(model, val)
    io.open(os.path.join(OUT, "color_eval.json"), "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    L = ["# 색상 예측 평가 (K-Fashion Validation, 21색)", "", "가린 부위의 색을 21색 중 몇 등에 놓는지. item = P(색|아이템), lift = 상대 부위 색과의 공출현.", ""]
    for h, r in res.items():
        L += [f"## {h} 색 가림 (n={r['prior']['n']:,})", "", "| 방법 | Hit@1 | Hit@3 | MRR |", "|---|---|---|---|"]
        for m, v in r.items(): L.append(f"| {m} | {v['hit@1']*100:.1f}% | {v['hit@3']*100:.1f}% | {v['mrr']:.3f} |")
        L.append("")
        for m, v in r.items(): print(f"[{h}] {m:10s} hit@1 {v['hit@1']*100:5.1f}%  hit@3 {v['hit@3']*100:5.1f}%  MRR {v['mrr']:.3f}")
    top = sorted(model["lift"]["상의×하의"].items(), key=lambda kv: -kv[1])[:12]
    L += ["## 상의색×하의색 lift 상위", "", "| 상의 | 하의 | lift |", "|---|---|---|"] + [f"| {k.split('|')[0]} | {k.split('|')[1]} | {v} |" for k, v in top]
    io.open(os.path.join(OUT, "color_eval.md"), "w", encoding="utf-8").write("\n".join(L))
    print("top lifts:", top[:6]); print("saved data/kfashion_color.json, runs/color_eval.*")

if __name__ == "__main__":
    main()
