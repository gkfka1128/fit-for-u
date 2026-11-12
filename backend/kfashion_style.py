"""
스타일 조건화 — K-Fashion 스타일 라벨(스트리트·모던·페미닌 … 23종)로 "이 스타일에선 어떤 아이템·색이 더 나오나"를 재고,
사용자가 스타일을 고르면 규칙 엔진이 그쪽으로 기운다 (로드맵 7번, 9/21).

  item_lift[style][part][item id] = log( P(item | style) / P(item) )   ±1.5 클램프, 스타일 내 등장 ≥ 20
  color_lift[style][part][색]     = 같은 방식
  평가: Validation 코디(스타일 라벨 있음) FITB — 조합 모델 vs 조합 모델 + 스타일 lift

  .\.venv\Scripts\python.exe kfashion_style.py
출력: data/kfashion_style.json, runs/style_eval.md
"""
import collections, io, json, math, os, time, zipfile
import numpy as np
from kfashion_cooc import KEYS, first

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
ROOT = os.path.join(HERE, "..", "Data", "K-Fashion 이미지")
PARTS = ("상의", "하의", "아우터")
CLAMP, MIN_N = 1.5, 20

def load(split, limit=None):
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    key_of = lambda p, a: tuple(a.get(k) for k in KEYS[p])
    cand = {p: {key_of(p, it["attrs"]): i for i, it in enumerate(items[p])} for p in PARTS}
    z = zipfile.ZipFile(os.path.join(ROOT, "Training" if split == "train" else "Validation", "라벨링데이터.zip"))
    names = [n for n in z.namelist() if n.lower().endswith(".json")][:limit]
    out = []
    for nm in names:
        try: lab = json.loads(z.read(nm).decode("utf-8"))["데이터셋 정보"]["데이터셋 상세설명"]["라벨링"]
        except Exception: continue
        st = lab.get("스타일"); style = first(st[0], "스타일") if st and st[0] else None
        if not style: continue
        o = {"style": style}
        for p in PARTS:
            lp = [x for x in lab.get(p, []) if x]
            if not lp or not first(lp[0], "카테고리"): continue
            attrs = {k: first(lp[0], k) for k in KEYS[p]}; i = cand[p].get(key_of(p, attrs))
            if i is not None: o[p] = {"id": i, "attrs": attrs, "color": first(lp[0], "색상")}
        if "상의" in o and "하의" in o: out.append(o)
    return out, items

def build(train, items):
    n_style = collections.Counter(o["style"] for o in train); N = len(train)
    cnt = {p: collections.Counter() for p in PARTS}; cnt_s = {p: collections.defaultdict(collections.Counter) for p in PARTS}
    col = {p: collections.Counter() for p in PARTS}; col_s = {p: collections.defaultdict(collections.Counter) for p in PARTS}
    for o in train:
        for p in PARTS:
            if p in o:
                i = o[p]["id"]; cnt[p][i] += 1; cnt_s[p][o["style"]][i] += 1
                if o[p]["color"]: col[p][o[p]["color"]] += 1; col_s[p][o["style"]][o[p]["color"]] += 1
    def lifts(total, per_style):
        out = {}
        for s, ns in n_style.items():
            out[s] = {}
            for p in PARTS:
                tot_p = sum(total[p].values()); tot_sp = sum(per_style[p][s].values())
                if not tot_sp: continue
                for k, c in total[p].items():
                    cs = per_style[p][s].get(k, 0)
                    if cs < MIN_N: continue
                    v = math.log(((cs + 1) / (tot_sp + len(total[p]))) / (c / tot_p))
                    out[s][f"{p}|{k}"] = round(max(-CLAMP, min(CLAMP, v)), 3)
        return out
    return {"styles": dict(n_style.most_common()), "n": N, "item_lift": lifts(cnt, cnt_s), "color_lift": lifts(col, col_s)}

def evaluate(model, val, eng):
    from train_compat import featurize, GIVEN
    from rule_engine import _transform
    from kfashion_cooc import ITEM_ATTRS
    res = {}
    for hidden in PARTS:
        rows, truths, styles = [], [], []
        for o in val:
            if hidden not in o: continue
            given = {p: (tuple(o[p]["attrs"].get(a) for a in ITEM_ATTRS[p]) if p in o else None) for p in GIVEN[hidden]}
            if not any(given.values()): continue
            rows.append(featurize(hidden, given)); truths.append(o[hidden]["id"]); styles.append(o["style"])
        m = eng.compat[hidden]; lp = m["clf"].predict_log_proba(_transform(m["vocab"], rows))
        P = np.full((len(rows), len(eng.items[hidden])), -30.0)
        for j, c in enumerate(m["clf"].classes_): P[:, int(c)] = lp[:, j]
        pop = np.log(eng.prior[hidden] + 1e-9)
        ranks = collections.defaultdict(list)
        for r, (t, s) in enumerate(zip(truths, styles)):
            sl = np.array([model["item_lift"].get(s, {}).get(f"{hidden}|{i}", 0.0) for i in range(len(eng.items[hidden]))])
            for name, sc in (("popularity", pop), ("popularity+style", pop + sl), ("model", P[r]), ("model+style", P[r] + 0.7 * sl)):
                ranks[name].append(int((sc > sc[t]).sum()) + 1 + int((sc == sc[t]).sum() - 1) / 2)
        res[hidden] = {"n": len(truths), **{k: {"hit@1": float(np.mean(np.array(v) <= 1)), "hit@5": float(np.mean(np.array(v) <= 5)), "hit@10": float(np.mean(np.array(v) <= 10))} for k, v in ranks.items()}}
    return res

def main():
    t = time.time(); train, items = load("train"); print(f"train {len(train):,} ({time.time()-t:.0f}s)")
    model = build(train, items); os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(DATA, "kfashion_style.json"), "w", encoding="utf-8").write(json.dumps(model, ensure_ascii=False))
    val, _ = load("val", 40000); print(f"val {len(val):,}")
    from rule_engine import RuleEngine
    eng = RuleEngine(); res = evaluate(model, val, eng)
    L = ["# 스타일 조건화 평가 (K-Fashion Validation FITB, 스타일 라벨 사용)", "", f"학습 {len(train):,} / 검증 {len(val):,} 코디. 스타일 lift = log P(item|style)/P(item), 가중 0.7.", "",
         "## 스타일 분포 (학습)", "", ", ".join(f"{s} {n:,}" for s, n in list(model["styles"].items())[:12]), ""]
    for h, r in res.items():
        L += [f"## {h} 가림 (n={r['n']:,})", "", "| 방법 | Hit@1 | Hit@5 | Hit@10 |", "|---|---|---|---|"]
        for k, v in r.items():
            if k != "n": L.append(f"| {k} | {v['hit@1']*100:.1f}% | {v['hit@5']*100:.1f}% | {v['hit@10']*100:.1f}% |"); print(f"[{h}] {k:17s} hit@5 {v['hit@5']*100:5.1f}%")
        L.append("")
    # 스타일별 대표 아이템
    L += ["## 스타일별 lift 상위 아이템 (예)", ""]
    for s in list(model["styles"])[:8]:
        top = sorted(model["item_lift"].get(s, {}).items(), key=lambda kv: -kv[1])[:4]
        def lab(k):
            p, i = k.split("|"); a = items[p][int(i)]["attrs"]; return f"{p}:" + " ".join(str(v) for v in (a.get("핏"), a.get("기장"), a.get("소재"), a.get("카테고리")) if v)
        L.append(f"- **{s}**: " + ", ".join(f"{lab(k)} ({v:+.1f})" for k, v in top))
    io.open(os.path.join(OUT, "style_eval.md"), "w", encoding="utf-8").write("\n".join(L)); print("saved data/kfashion_style.json, runs/style_eval.md")

if __name__ == "__main__":
    main()
