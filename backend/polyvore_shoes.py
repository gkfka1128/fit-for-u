"""
신발 통계 — Polyvore Outfits (Marqo/polyvore 6조각) 코디에서 "이 상의·하의·아우터엔 어떤 신발"을 센다. (9/22)

⚠ 데이터 성격 — 결과를 쓸 때 반드시 같이 말할 것
  · 출처: Polyvore (미국 패션 SNS, 2014~2018 서구 쇼핑몰 상품으로 사용자가 짠 코디) — **서구 데이터**, 한국 착장 아님
  · **여성 편향**: 아이템 카테고리 대부분이 여성복·여성 신발(펌프스·앵클부츠). 남성 신발은 1% 미만 → 남성 통계로 쓰면 안 됨 (남성은 규칙 유지)
  · 상품 조합(사용자가 고른 코디)이지 실제 착용 사진이 아님. 날씨·계절 정보 없음 → 날씨는 우리 규칙(warmth)이 담당
  K-Fashion 엔 신발 부위가 없어 이 데이터로 "수기 11종"을 데이터 기반 lift 로 보강하는 것이 목적.

  lift[ctx][shoe] = log P(shoe | ctx) / P(shoe),  ctx = "하의|카테고리|핏/기장", "상의|카테고리", "아우터|카테고리"  (K-Fashion 어휘로 매핑)
  평가: 코디 20% 홀드아웃, 신발 가리고 10종 중 맞히기 — 인기도 vs 문맥 lift

  .\.venv\Scripts\python.exe polyvore_shoes.py
출력: data/polyvore_shoes.json, data/polyvore_outfits.json(코디 목록), runs/shoes_eval.md
"""
import collections, glob, io, json, math, os, random, time
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
PARQ = os.path.join(HERE, "..", "Data", "Polyvore (Marqo)")
CLAMP, MIN_N = 1.5, 15

# Polyvore 카테고리 → (부위, K-Fashion 카테고리, 핏, 기장)
TOP = {"Tops": "티셔츠", "Tank Tops": "탑", "T-Shirts": "티셔츠", "Camisoles": "탑", "Activewear Tank Tops": "탑", "Men's Tank Tops": "탑", "Men's T-Shirts": "티셔츠",
       "Blouses": "블라우스", "Sweaters": "니트웨어", "Sweatshirts": "티셔츠", "Men's Sweatshirts": "티셔츠", "Hoodies": "후드티",
       "Men's Shirts": "셔츠", "Men's Casual Shirts": "셔츠", "Men's Dress Shirts": "셔츠", "Shirts": "셔츠", "Button Down Shirts": "셔츠"}
BOTTOM = {"Skinny Jeans": ("청바지", "스키니", None), "Jeans": ("청바지", "노멀", None), "Men's Jeans": ("청바지", "노멀", None), "Boyfriend Jeans": ("청바지", "루즈", None),
          "Straight Leg Jeans": ("청바지", "노멀", None), "Bootcut Jeans": ("청바지", "벨보텀", None), "Flared Jeans": ("청바지", "벨보텀", None), "Wide Leg Jeans": ("청바지", "와이드", None),
          "Pants": ("팬츠", "노멀", None), "Men's Dress Pants": ("팬츠", "노멀", None), "Men's Casual Pants": ("팬츠", "노멀", None), "Wide Leg Pants": ("팬츠", "와이드", None), "Skinny Pants": ("팬츠", "스키니", None),
          "Capri & Cropped Pants": ("팬츠", "노멀", "미디"), "Shorts": ("팬츠", "노멀", "미니"), "Men's Activewear Shorts": ("팬츠", "노멀", "미니"),
          "Leggings": ("래깅스", "스키니", None), "Activewear Pants": ("조거팬츠", "노멀", None), "Men's Activewear Pants": ("조거팬츠", "노멀", None), "Sweatpants": ("조거팬츠", "루즈", None),
          "Knee Length Skirts": ("스커트", None, "니렝스"), "Mini Skirts": ("스커트", None, "미니"), "Long Skirts": ("스커트", None, "맥시"), "Skirts": ("스커트", None, None), "Midi Skirts": ("스커트", None, "미디")}
OUTER = {"Jackets": "재킷", "Blazers": "재킷", "Men's Jackets": "재킷", "Men's Sportcoats & Blazers": "재킷", "Coats": "코트", "Men's Coats": "코트", "Trench Coats": "코트",
         "Cardigans": "가디건", "Vests": "베스트", "Men's Vests": "베스트", "Outerwear": "재킷", "Leather Jackets": "재킷", "Denim Jackets": "재킷", "Puffer Jackets": "패딩", "Parkas": "점퍼"}
SHOE = {"Sneakers": "스니커즈", "Athletic Shoes": "러닝화", "Men's Sneakers": "스니커즈", "Men's Athletic Shoes": "러닝화", "Slip-On Sneakers": "스니커즈",
        "Ankle Booties": "앵클 부츠", "Knee High Boots": "롱 부츠", "Mid Calf Boots": "롱 부츠", "Over-The-Knee Boots": "롱 부츠", "Men's Boots": "워커", "Combat Boots": "워커",
        "Pumps": "펌프스", "Flats": "플랫 슈즈", "Ballet Flats": "플랫 슈즈", "Sandals": "샌들", "Flat Sandals": "샌들", "Slides": "슬리퍼", "Slippers": "슬리퍼",
        "Loafers & Moccasins": "로퍼", "Oxfords": "옥스포드", "Men's Dress Shoes": "옥스포드", "Men's Loafers": "로퍼", "Boat Shoes": "로퍼"}
SHOES = sorted(set(SHOE.values()))

def load_outfits():
    """parquet 6조각 → [{"set_id", "items": [{"cat": 원문, "part": 상의|하의|아우터|신발, ...}]}]"""
    files = sorted(glob.glob(os.path.join(PARQ, "*.parquet")))
    outfits = collections.defaultdict(list)
    for f in files:
        t = pq.read_table(f, columns=["category", "item_ID"])
        for cat, iid in zip(t.column("category").to_pylist(), t.column("item_ID").to_pylist()):
            outfits[iid.rsplit("_", 1)[0]].append(cat)
    out = []
    for sid, cats in outfits.items():
        o = {"set_id": sid, "cats": cats}
        for c in cats:
            if c in SHOE and "신발" not in o: o["신발"] = SHOE[c]
            elif c in TOP and "상의" not in o: o["상의"] = {"카테고리": TOP[c]}
            elif c in BOTTOM and "하의" not in o:
                cat, fit, length = BOTTOM[c]; o["하의"] = {"카테고리": cat, "핏": fit, "기장": length}
            elif c in OUTER and "아우터" not in o: o["아우터"] = {"카테고리": OUTER[c]}
        out.append(o)
    return out, len(files)

def contexts(o):
    """코디 → 문맥 키 목록 (엔진의 shoes() 와 같은 규칙으로 만든다)"""
    ks = []
    if "하의" in o:
        b = o["하의"]; ks.append(f"하의|{b['카테고리']}")
        if b.get("핏"): ks.append(f"하의|{b['카테고리']}|핏={b['핏']}")
        if b.get("기장"): ks.append(f"하의|{b['카테고리']}|기장={b['기장']}")
    if "상의" in o: ks.append(f"상의|{o['상의']['카테고리']}")
    if "아우터" in o: ks.append(f"아우터|{o['아우터']['카테고리']}")
    return ks

def build(train):
    tot = collections.Counter(o["신발"] for o in train); N = sum(tot.values())
    ctx = collections.defaultdict(collections.Counter)
    for o in train:
        for k in contexts(o): ctx[k][o["신발"]] += 1
    lift = {}
    for k, cnt in ctx.items():
        n = sum(cnt.values())
        if n < MIN_N: continue
        lift[k] = {s: round(max(-CLAMP, min(CLAMP, math.log(((cnt.get(s, 0) + 0.5) / (n + 0.5 * len(SHOES))) / (tot[s] / N)))), 3) for s in SHOES}
        lift[k]["_n"] = n
    return {"_doc": "⚠ Polyvore(서구·여성 편향 SNS 코디) 통계. lift = log P(신발|문맥)/P(신발), ±1.5. 남성 신발 <1% → 남성 사용자엔 적용하지 않는다 (rule_engine.shoes 참조)",
            "source": "Marqo/polyvore (Polyvore Outfits, Vasileva et al. 2018)", "n_outfits": len(train), "prior": {s: tot[s] for s in SHOES}, "lift": lift}

def score(model, o, s):
    ks = [k for k in contexts(o) if k in model["lift"]]
    if not ks: return 0.0
    w = {"하의": 1.0, "상의": 0.5, "아우터": 0.5}
    return sum(w[k.split("|")[0]] * model["lift"][k][s] for k in ks) / sum(w[k.split("|")[0]] for k in ks)

def main():
    t = time.time(); all_o, nf = load_outfits()
    with_shoe = [o for o in all_o if "신발" in o and ("상의" in o or "하의" in o)]
    print(f"parquet {nf}개, 코디 {len(all_o):,}, 신발+상하의 있는 코디 {len(with_shoe):,} ({time.time()-t:.0f}s)")
    random.seed(0); random.shuffle(with_shoe); k = int(len(with_shoe) * 0.8); train, test = with_shoe[:k], with_shoe[k:]
    model = build(train); os.makedirs(OUT, exist_ok=True)
    io.open(os.path.join(DATA, "polyvore_shoes.json"), "w", encoding="utf-8").write(json.dumps(model, ensure_ascii=False, indent=1))
    io.open(os.path.join(DATA, "polyvore_outfits.json"), "w", encoding="utf-8").write(json.dumps([{k: v for k, v in o.items() if k != "cats"} for o in with_shoe], ensure_ascii=False))
    # 평가: 신발 가리고 10종 중 순위
    prior = model["prior"]; hits = {"popularity": [0, 0], "context": [0, 0]}; n = 0
    male_n = sum(1 for o in with_shoe if any(c.startswith("Men's") for c in o["cats"]))
    for o in test:
        truth = o["신발"]; n += 1
        rp = sorted(SHOES, key=lambda s: -prior[s]); rc = sorted(SHOES, key=lambda s: -(math.log(prior[s] / sum(prior.values())) + 0.7 * score(model, o, s)))
        hits["popularity"][0] += rp[0] == truth; hits["popularity"][1] += truth in rp[:2]
        hits["context"][0] += rc[0] == truth; hits["context"][1] += truth in rc[:2]
    L = ["# 신발 통계 평가 — Polyvore Outfits (⚠ 서구 데이터 · 여성 편향)", "",
         f"코디 {len(with_shoe):,} (parquet {nf}조각), 남성 아이템이 포함된 코디 {male_n:,} ({male_n/len(with_shoe)*100:.1f}%) → **남성 통계로는 사용 불가**.", "",
         "신발 분포 (학습): " + ", ".join(f"{s} {prior[s]:,}" for s in sorted(SHOES, key=lambda s: -prior[s])), "",
         f"## 홀드아웃 {len(test):,} 코디, 신발 가리고 {len(SHOES)}종 중 맞히기", "", "| 방법 | Hit@1 | Hit@2 |", "|---|---|---|"]
    for m, (h1, h2) in hits.items(): L.append(f"| {m} | {h1/n*100:.1f}% | {h2/n*100:.1f}% |"); print(f"{m:11s} hit@1 {h1/n*100:.1f}%  hit@2 {h2/n*100:.1f}%")
    L += ["", "## 문맥별 lift 상위 (예)", ""]
    for k in ["하의|청바지|핏=스키니", "하의|스커트|기장=미니", "하의|팬츠|기장=미니", "하의|조거팬츠", "상의|블라우스", "상의|후드티", "아우터|코트"]:
        if k in model["lift"]:
            top = sorted(((s, v) for s, v in model["lift"][k].items() if s != "_n"), key=lambda kv: -kv[1])[:3]
            L.append(f"- **{k}** (n={model['lift'][k]['_n']}): " + ", ".join(f"{s} {v:+.2f}" for s, v in top))
    io.open(os.path.join(OUT, "shoes_eval.md"), "w", encoding="utf-8").write("\n".join(L)); print("saved data/polyvore_shoes.json, runs/shoes_eval.md")

if __name__ == "__main__":
    main()
