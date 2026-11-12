"""
후보 아이템 + 공출현 lift.
  아이템 = 부위별 속성 조합 (Training 에서 200회 이상 나온 것): 상의 492 / 하의 222 / 아우터 132 / 원피스 157
    상의·원피스: 카테고리·핏·기장·넥라인·소매기장·소재 (원피스는 핏 포함 6개 중 위 순서)  하의·아우터: 카테고리·핏·기장·소재 (아우터는 소매·넥 없이)
    소재가 여러 개면 첫 번째. 카테고리 없는 인스턴스는 제외.
  공출현 lift = P(a, b) / (P(a) P(b))  같은 사진 안에서 (Training, 쌍 등장 30회 이상)

  data/kfashion_items.json, data/kfashion_cooc.json, data/kfashion_cooc.md
"""
import collections, io, json, os, pickle

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data")
ITEM_ATTRS = {"상의": ["카테고리", "핏", "기장", "넥라인", "소매기장", "소재"], "하의": ["카테고리", "핏", "기장", "소재"],
              "아우터": ["카테고리", "핏", "기장", "소재"], "원피스": ["카테고리", "핏", "기장", "소매기장", "넥라인", "소재"]}
MIN_COUNT = 200
PAIRS = [("상의", "핏", "하의", "핏"), ("상의", "카테고리", "하의", "카테고리"), ("상의", "기장", "하의", "기장"),
         ("아우터", "핏", "상의", "핏"), ("아우터", "카테고리", "상의", "카테고리"), ("아우터", "카테고리", "하의", "카테고리"),
         ("아우터", "기장", "하의", "기장"), ("아우터", "기장", "상의", "기장")]


KEYS = ITEM_ATTRS


def first(d, k):
    """속성 dict 에서 k 의 첫 값 (소재·프린트처럼 목록이면 첫 번째)"""
    v = d.get(k)
    return v[0] if isinstance(v, list) and v else v


def item_key(part, it):
    return tuple(first(it, a) for a in ITEM_ATTRS[part])


def load_labels():
    return pickle.load(open(os.path.join(DATA, "kfashion_labels.pkl"), "rb"))


def attrs_of(part, key):
    return {a: v for a, v in zip(ITEM_ATTRS[part], key) if v}


def main():
    recs = [r for r in load_labels() if r["split"] == "train"]
    items, cooc_out, lines = {}, {}, ["# 후보 아이템 · 공출현 lift", ""]
    for part, A in ITEM_ATTRS.items():
        c = collections.Counter(item_key(part, it) for r in recs for it in r["parts"].get(part, []) if "카테고리" in it)
        rows = [(k, n) for k, n in c.most_common() if n >= MIN_COUNT]
        items[part] = [{"attrs": attrs_of(part, k), "count": n} for k, n in rows]
        lines.append(f"- {part}: 후보 {len(rows)}종 (전체 조합 {len(c):,}, 상위 커버 {sum(n for _, n in rows) / sum(c.values()):.0%})")
    for pa, aa, pb, ab in PAIRS:
        ca, cb, cab, n = collections.Counter(), collections.Counter(), collections.Counter(), 0
        for r in recs:
            xa = [first(i, aa) for i in r["parts"].get(pa, []) if first(i, aa)]
            xb = [first(i, ab) for i in r["parts"].get(pb, []) if first(i, ab)]
            if not xa or not xb: continue
            n += 1; a, b = xa[0], xb[0]; ca[a] += 1; cb[b] += 1; cab[(a, b)] += 1
        rows = [{"a": a, "b": b, "n": m, "lift": round(m * n / (ca[a] * cb[b]), 3)} for (a, b), m in cab.items() if m >= 30]
        rows.sort(key=lambda r: -r["lift"])
        cooc_out[f"{pa}.{aa} × {pb}.{ab}"] = {"n_images": n, "rows": rows}
        lines.append(f"- {pa}.{aa} × {pb}.{ab}: 사진 {n:,}장, 쌍 {len(rows)}개")
    io.open(os.path.join(DATA, "kfashion_items.json"), "w", encoding="utf-8").write(json.dumps(items, ensure_ascii=False))
    io.open(os.path.join(DATA, "kfashion_cooc.json"), "w", encoding="utf-8").write(json.dumps(cooc_out, ensure_ascii=False))
    io.open(os.path.join(DATA, "kfashion_cooc.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
