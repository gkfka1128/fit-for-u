"""
제품 컷 속성 추정 — AI Hub 143.패션상품 및 착용 영상(흰 배경 제품 컷 13,907 + 착용 컷 86,380, 아이템↔착용 페어)엔
카테고리·핏·기장·넥·소매·소재·색 라벨이 없다. K-Fashion 라벨(bbox crop)로 속성 분류기를 학습해 제품 컷에 라벨을 붙이고,
후보 아이템 846종에 매핑한다. 결과: 아이템 칸 = 스튜디오 제품 컷, 착장 칸 = 그 제품을 입은 착용 컷(상의·하의 동시 일치).

  단계 (각각 따로 실행, 결과는 data/product/ 에 캐시)
  scan    K-Fashion 라벨 스캔 → 후보 아이템별 crop 표본 (아이템당 ≤40)                 ~5분
  feats   crop 추출 + CLIP(ViT-B-32) 특징 / 143 제품 컷 특징                          ~20분 (GPU)
  train   부위×속성별 로지스틱 회귀, 홀드아웃 정확도 → runs/product_attrs.md
  assign  제품 컷 → 속성 확률 → 후보 아이템 매핑(속성 log P 합) → data/product_photos.json + data/thumbs_product/
          + 착용 컷 조합 색인 (winfo: 착용 컷 ↔ 아이템) → data/product_wearing.json + data/thumbs_wearing/

  .\.venv\Scripts\python.exe product_attrs.py scan|feats|train|assign|all
"""
import argparse, collections, io, json, os, random, sys, time, zipfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs"); PD = os.path.join(DATA, "product")
D143 = os.path.join(HERE, "..", "Data", "143.패션상품 및 착용 영상", "01.데이터")
ITEM_ZIP = os.path.join(D143, "1.Training", "원천데이터_230515_add", "2021_Fashion_train_itemimages_v230428.zip")
MODEL_ZIP = os.path.join(D143, "1.Training", "원천데이터_230515_add", "2021_Fashion_train_modelimages_v230428.zip")
LABEL_ZIP_143 = os.path.join(D143, "1.Training", "라벨링데이터_230515_add", "2021_Fashion_train_labels_v230428.zip")
PARTS = ("상의", "하의", "아우터")
PART_OF_143 = {"tops": "상의", "bottoms": "하의", "outerwear": "아우터"}
PER_ITEM, CLIP_MODEL, CLIP_PRE = 40, "ViT-B-32", "laion2b_s34b_b79k"
MIN_CONF = 0.15         # (구) 매핑 확신 하한
ITEM_MIN = 0.05         # 아이템 중심 선택: 그 아이템일 확률이 이 값 이상인 제품 컷만 후보
PER_COLOR, PER_ITEM_MAX = 3, 20   # 아이템당 색별 최대 3장, 전체 20장
GRAY = 224              # 제품 컷 배경 — 흰 옷이 흰 배경에 묻히지 않게 회색
os.makedirs(PD, exist_ok=True)


# ---------------------------------------------------------------- scan
def scan():
    from kfashion_cooc import KEYS, first
    from kfashion_photos import LABEL_ZIP
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    key_of = lambda p, a: tuple(a.get(k) for k in KEYS[p])
    cand = {p: {key_of(p, it["attrs"]): i for i, it in enumerate(items[p])} for p in PARTS}
    z = zipfile.ZipFile(LABEL_ZIP); names = [n for n in z.namelist() if n.lower().endswith(".json")]
    random.seed(0); random.shuffle(names)
    seen = {p: collections.Counter() for p in PARTS}; rows = {p: [] for p in PARTS}; t0 = time.time()
    for n, nm in enumerate(names):
        try:
            lab = json.loads(z.read(nm).decode("utf-8")); info = lab["이미지 정보"]; d = lab["데이터셋 정보"]["데이터셋 상세설명"]
        except Exception:
            continue
        img_id, W, H = info["이미지 식별자"], info["이미지 너비"], info["이미지 높이"]
        for p in PARTS:
            lab_p = [x for x in d["라벨링"].get(p, []) if x]
            if not lab_p or not first(lab_p[0], "카테고리"): continue
            i = cand[p].get(key_of(p, {k: first(lab_p[0], k) for k in KEYS[p]}))
            if i is None or seen[p][i] >= PER_ITEM: continue
            rect = [r for r in d["렉트좌표"].get(p, []) if r]
            if not rect or not W or not H: continue
            r = rect[0]
            if r["가로"] * r["세로"] < 0.03 * W * H: continue                     # 너무 작은 컷 제외
            seen[p][i] += 1
            rows[p].append({"item": i, "img": img_id, "bbox": [r["X좌표"], r["Y좌표"], r["가로"], r["세로"]], "color": first(lab_p[0], "색상")})
        if n % 100000 == 0 and n: print(f"  {n:,}/{len(names):,}  {time.time()-t0:.0f}s  {[len(rows[p]) for p in PARTS]}", flush=True)
        if all(len(seen[p]) == len(items[p]) and min(seen[p].values()) >= PER_ITEM for p in PARTS): break
    io.open(os.path.join(PD, "crops.json"), "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False))
    print(f"crops: {[len(rows[p]) for p in PARTS]}  items covered {[len(seen[p]) for p in PARTS]}  ({time.time()-t0:.0f}s)")


# ---------------------------------------------------------------- feats
def _clip():
    import torch, open_clip
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, pre = open_clip.create_model_and_transforms(CLIP_MODEL, pretrained=CLIP_PRE, device=dev); model.eval()
    def embed(imgs):
        with torch.no_grad():
            x = torch.stack([pre(im) for im in imgs]).to(dev)
            f = model.encode_image(x); f = f / f.norm(dim=-1, keepdim=True)
        return f.float().cpu().numpy()
    embed.text = lambda prompts: _text(model, prompts, dev)
    return embed

def _text(model, prompts, dev):
    import torch, open_clip
    tok = open_clip.get_tokenizer(CLIP_MODEL)
    with torch.no_grad():
        f = model.encode_text(tok(prompts).to(dev)); f = f / f.norm(dim=-1, keepdim=True)
    return f.float().cpu().numpy()

PATTERNS = {"무지": "a plain solid color garment with no pattern", "스트라이프": "a striped garment", "체크": "a checked plaid garment",
            "그래픽": "a garment with a large graphic print or logo", "플로럴": "a floral pattern garment", "도트": "a polka dot garment"}

def patterns(embed, X):
    """CLIP zero-shot 무늬 — 6개 프롬프트 중 최고. 반환 (라벨 배열, 확률 배열)"""
    T = embed.text(list(PATTERNS.values())); z = 100.0 * X @ T.T; z = z - z.max(1, keepdims=True); p = np.exp(z); p /= p.sum(1, keepdims=True)
    names = np.array(list(PATTERNS))
    return names[p.argmax(1)], p.max(1)

def backdrop(im, gray=GRAY, diff_thr=10, min_frac=0.02, washed_frac=0.03):
    """제품 컷의 배경(테두리 색)을 회색으로 바꾼다. 옷이 프레임의 3% 미만인 컷(배경에 씻겨 나간 흰 옷)은 None"""
    from scipy import ndimage
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    bg = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), 0)
    fg = np.abs(a - bg).max(2) > diff_thr
    fg = ndimage.binary_closing(fg, iterations=8)              # 좁은 틈을 메워 옷 안쪽 구멍 방지
    fg = ndimage.binary_fill_holes(fg)
    lab, n = ndimage.label(fg)
    if not n: return None
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    fg = np.isin(lab, [i + 1 for i, sz in enumerate(sizes) if sz > 0.05 * sizes.max()])   # 그림자·먼지 조각 제거
    fg = ndimage.binary_dilation(fg, iterations=2)
    if fg.mean() < max(min_frac, washed_frac): return None
    out = np.full(a.shape, gray, dtype=np.uint8); out[fg] = a[fg].astype(np.uint8)
    return Image.fromarray(out)

def _batches(it, n=64):
    b = []
    for x in it:
        b.append(x)
        if len(b) == n: yield b; b = []
    if b: yield b

def feats():
    from kfashion_photos import read_image
    embed = _clip(); t0 = time.time()
    rows = json.loads(io.open(os.path.join(PD, "crops.json"), encoding="utf-8").read())
    for p in PARTS:
        fp = os.path.join(PD, f"kf_{p}.npy")
        if os.path.exists(fp): print("skip", fp); continue
        X, keep = [], []
        for bi, batch in enumerate(_batches(list(enumerate(rows[p])))):
            imgs, idx = [], []
            for k, r in batch:
                img = read_image(r["img"])
                if img is None: continue
                x, y, w, h = r["bbox"]; m = 0.06
                crop = img.crop((int(max(0, x - w * m)), int(max(0, y - h * m)), int(min(img.width, x + w * (1 + m))), int(min(img.height, y + h * (1 + m)))))
                imgs.append(crop); idx.append(k)
            if imgs: X.append(embed(imgs)); keep += idx
            if bi % 50 == 0: print(f"  {p} {len(keep):,}/{len(rows[p]):,}  {time.time()-t0:.0f}s", flush=True)
        np.save(fp, np.concatenate(X)); json.dump(keep, open(os.path.join(PD, f"kf_{p}_idx.json"), "w"))
        print(f"{p}: {len(keep)} feats  ({time.time()-t0:.0f}s)")
    # 143 제품 컷 (앞면)
    fp = os.path.join(PD, "prod.npy")
    if not os.path.exists(fp):
        zi = zipfile.ZipFile(ITEM_ZIP); names = sorted(x for x in zi.namelist() if x.endswith("_F.jpg"))
        X, ids = [], []
        for bi, batch in enumerate(_batches(names)):
            X.append(embed([Image.open(io.BytesIO(zi.read(n))).convert("RGB") for n in batch])); ids += [os.path.basename(n)[:-6] for n in batch]
            if bi % 50 == 0: print(f"  prod {len(ids):,}/{len(names):,}  {time.time()-t0:.0f}s", flush=True)
        np.save(fp, np.concatenate(X)); json.dump(ids, open(os.path.join(PD, "prod_ids.json"), "w"))
        print(f"prod: {len(ids)} feats  ({time.time()-t0:.0f}s)")


# ---------------------------------------------------------------- train
def _labels(p, rows, keep, items):
    from kfashion_cooc import KEYS
    attrs = list(KEYS[p]) + ["색상"]
    Y = {a: [] for a in attrs}
    for k in keep:
        r = rows[p][k]; it = items[p][r["item"]]["attrs"]
        for a in KEYS[p]: Y[a].append(it.get(a) or "없음")
        Y["색상"].append(r["color"] or "없음")
    return attrs, Y

def train():
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    import joblib
    rows = json.loads(io.open(os.path.join(PD, "crops.json"), encoding="utf-8").read())
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    lines = ["# 제품 컷 속성 분류기 — K-Fashion crop 으로 학습, 홀드아웃 20%", "", "CLIP ViT-B-32(laion2b) 특징 + 로지스틱 회귀. 다수 클래스 = 항상 최빈값을 찍었을 때.", "",
             "| 부위 | 속성 | 클래스 | n | 정확도 | 다수 클래스 |", "|---|---|---|---|---|---|"]
    models = {}
    for p in PARTS:
        X = np.load(os.path.join(PD, f"kf_{p}.npy")); keep = json.load(open(os.path.join(PD, f"kf_{p}_idx.json")))
        attrs, Y = _labels(p, rows, keep, items)
        for a in attrs:
            y = np.array(Y[a]); cls = sorted(set(y))
            Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=0, stratify=y if min(collections.Counter(y).values()) >= 2 else None)
            clf = LogisticRegression(max_iter=2000, C=2.0).fit(Xtr, ytr)
            acc = (clf.predict(Xte) == yte).mean(); maj = collections.Counter(yte).most_common(1)[0][1] / len(yte)
            models[(p, a)] = LogisticRegression(max_iter=2000, C=2.0).fit(X, y)       # 전체로 재학습
            lines.append(f"| {p} | {a} | {len(cls)} | {len(y):,} | **{acc:.1%}** | {maj:.1%} |"); print(lines[-1], flush=True)
    joblib.dump(models, os.path.join(PD, "attr_clf.joblib"))
    lines += ["", "- 학습 데이터는 사람이 입은 K-Fashion crop, 적용 대상은 흰 배경 제품 컷 → 도메인 차이로 실제 정확도는 이보다 낮다. 핏·기장은 특히 주의",
              "- 제품 컷엔 정답 라벨이 없어 매핑 정확도는 눈으로 확인 (`runs/_peek/product_check.jpg`)"]
    io.open(os.path.join(OUT, "product_attrs.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- assign
def _prod_scores(items):
    """143 제품 컷 → 부위·아이템 확률 P[r, j], 색·무늬 추정. 반환 dict"""
    import joblib
    from kfashion_cooc import KEYS
    models = joblib.load(os.path.join(PD, "attr_clf.joblib"))
    X = np.load(os.path.join(PD, "prod.npy")); ids = json.load(open(os.path.join(PD, "prod_ids.json")))
    z = zipfile.ZipFile(LABEL_ZIP_143); part_of = {}
    for n in z.namelist():
        if n.startswith("Item-Pose/") and n.endswith("_F.json"):
            j = json.loads(z.read(n)); part_of[os.path.basename(n)[:-7]] = PART_OF_143.get(j["category_name"])
    pat, pat_p = patterns(_clip(), X)
    out = {"ids": ids, "part_of": part_of, "pattern": dict(zip(ids, pat)), "P": {}, "sel": {}, "color": {}}
    for p in PARTS:
        sel = [k for k, i in enumerate(ids) if part_of.get(i) == p]
        if not sel: continue
        Xp = X[sel]
        logp = {a: (models[(p, a)].classes_, np.log(models[(p, a)].predict_proba(Xp) + 1e-9)) for a in KEYS[p]}
        ccls, cprob = models[(p, "색상")].classes_, models[(p, "색상")].predict_proba(Xp)
        S = np.zeros((len(sel), len(items[p])))
        for j, it in enumerate(items[p]):
            for a in KEYS[p]:
                cls, lp = logp[a]; v = it["attrs"].get(a) or "없음"
                col = np.where(cls == v)[0]
                S[:, j] += lp[:, col[0]] if len(col) else np.log(1e-9)
        P = np.exp(S - S.max(1, keepdims=True)); P /= P.sum(1, keepdims=True)
        out["P"][p] = P; out["sel"][p] = sel
        out["color"][p] = [(ccls[cprob[r].argmax()], float(cprob[r].max())) for r in range(len(sel))]
    return out


def assign():
    """아이템 중심 선택: 아이템 j 마다 "그 아이템일 확률"이 높은 제품 컷을 색별로 모은다 (무지 우선, 색당 ≤3, 전체 ≤20).
    제품 컷 배경은 회색(224)으로 바꿔 저장 — 흰 옷이 안 묻히게. 옷이 프레임의 3% 미만인 컷은 버린다."""
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    sc = _prod_scores(items); ids, pattern = sc["ids"], sc["pattern"]
    zi = zipfile.ZipFile(ITEM_ZIP); stats = collections.Counter(); index = {p: {} for p in PARTS}; prod_item = {}
    done = {}                                               # 제품 id → 썸네일 상대경로 (None = 배경 처리 실패)

    def thumb_of(pid, p):
        if pid in done: return done[pid]
        rel = f"data/thumbs_product/{p}/{pid}.jpg"; path = os.path.join(HERE, rel)
        if not os.path.exists(path):
            im = backdrop(Image.open(io.BytesIO(zi.read(f"Item-Image/{pid}_F.jpg"))))
            if im is None: done[pid] = None; return None
            os.makedirs(os.path.dirname(path), exist_ok=True); im.thumbnail((420, 420)); im.save(path, "JPEG", quality=85)
        done[pid] = rel; return rel

    for p in PARTS:
        if p not in sc["P"]: continue
        P, sel, cols = sc["P"][p], sc["sel"][p], sc["color"][p]
        for r, k in enumerate(sel):                         # 제품 컷 → argmax 아이템 (착용 컷 색인용)
            j = int(P[r].argmax()); prod_item[ids[k]] = [p, j, cols[r][0], pattern[ids[k]]]
        for j in range(len(items[p])):
            order = [r for r in np.argsort(-P[:, j]) if P[r, j] >= ITEM_MIN][:150]
            bycol = collections.defaultdict(list)
            for r in order: bycol[cols[r][0]].append(r)
            entries = []
            for col, rs in sorted(bycol.items(), key=lambda kv: -P[kv[1][0], j]):
                rs.sort(key=lambda r: (pattern[ids[sel[r]]] != "무지", -P[r, j])); taken = 0
                for r in rs:
                    pid = ids[sel[r]]; rel = thumb_of(pid, p)
                    if rel is None: stats[f"{p} 배경실패"] += 1; continue
                    entries.append({"id": pid, "conf": round(float(P[r, j]), 3), "color": col, "color_p": round(cols[r][1], 3), "pattern": pattern[pid], "file": rel})
                    taken += 1
                    if taken >= PER_COLOR: break
                if len(entries) >= PER_ITEM_MAX: break
            if entries: index[p][str(j)] = entries; stats[f"{p} 아이템"] += 1
    out = {"_doc": "제품 컷 — AI Hub 143.패션상품 및 착용 영상(흰 배경 스튜디오, 국내). 라벨이 없어 K-Fashion 으로 학습한 CLIP+로지스틱 분류기로 속성을 추정해 후보 아이템에 매핑(아이템 확률 ≥5%). "
                   "conf = 그 아이템일 확률, color = 추정 색(런타임에 색이 다르면 쓰지 않음), pattern = CLIP 무늬 추정(무지 우선). 추정이므로 핏·기장은 틀릴 수 있다. 배경은 회색 224 로 교체.",
           "source": "AI Hub 143.패션상품 및 착용 영상 (2021)", **index}
    io.open(os.path.join(DATA, "product_photos.json"), "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
    io.open(os.path.join(PD, "prod_item.json"), "w", encoding="utf-8").write(json.dumps(prod_item, ensure_ascii=False))
    from PIL import ImageDraw
    random.seed(1); tiles = []
    for p in PARTS:
        for j in random.sample(sorted(index[p], key=int), min(8, len(index[p]))):
            e = index[p][j][0]; im = Image.open(os.path.join(HERE, e["file"])).convert("RGB"); im.thumbnail((150, 200))
            tile = Image.new("RGB", (160, 250), "white"); tile.paste(im, (5, 5)); a = items[p][int(j)]["attrs"]
            ImageDraw.Draw(tile).text((5, 208), " ".join(v for v in a.values() if v)[:22], fill="black"); ImageDraw.Draw(tile).text((5, 222), f"{e['color']} {e['pattern']} {e['conf']:.2f}", fill="gray")
            tiles.append(tile)
    sheet = Image.new("RGB", (160 * 8, 250 * 3), "white")
    for k, t in enumerate(tiles): sheet.paste(t, ((k % 8) * 160, (k // 8) * 250))
    os.makedirs(os.path.join(OUT, "_peek"), exist_ok=True); sheet.save(os.path.join(OUT, "_peek", "product_check.jpg"))
    n_full = sum(1 for p in PARTS for es in index[p].values() for e in es)
    lines = ["", "## 매핑 결과 (아이템 중심)", "", f"제품 컷 {len(ids):,} → 썸네일 {sum(1 for v in done.values() if v):,} 장 (배경 처리 실패·씻김 {sum(1 for v in done.values() if not v)} 제외), 아이템 항목 {n_full:,}",
             f"후보 아이템 커버: 상의 {len(index['상의'])}/{len(items['상의'])} · 하의 {len(index['하의'])}/{len(items['하의'])} · 아우터 {len(index['아우터'])}/{len(items['아우터'])}", "", "눈 검사: `runs/_peek/product_check.jpg`"]
    io.open(os.path.join(OUT, "product_attrs.md"), "a", encoding="utf-8").write("\n".join(lines) + "\n"); print("\n".join(lines))


# ---------------------------------------------------------------- wearing
MAX_COMBO = 8


def wearing():
    """착용 컷 색인: 143 winfo(착용 컷 ↔ 상의·하의·아우터 제품) → 제품→아이템 매핑(prod_item.json)으로 "상의-하의-아우터" 조합.
    조합·상의별·하의별로 색 조합이 다양하도록 최대 8장. 선택된 착용 컷만 CLIP 으로 모델 성별(zero-shot)을 재고 썸네일 저장."""
    prod_item = json.loads(io.open(os.path.join(PD, "prod_item.json"), encoding="utf-8").read())
    z = zipfile.ZipFile(LABEL_ZIP_143); w = json.loads(z.read("winfo_train.json").decode("utf-8"))
    cand = []
    for r in w:
        top = out_ = bot = None
        for key in ("main_top", "inner_top"):
            pi = prod_item.get(r.get(key) or "")
            if pi and pi[0] == "상의" and top is None: top = pi
            elif pi and pi[0] == "아우터" and out_ is None: out_ = pi
        pb = prod_item.get(r.get("bottom") or "")
        if pb and pb[0] == "하의": bot = pb
        if top and bot: cand.append((r["wearing"], top, bot, out_))

    def diverse(rows, cap):
        seen, out = set(), []
        for fid, t, b, o in rows:
            k = (t[2], b[2], o[2] if o else None)
            if k in seen: continue
            seen.add(k); out.append(fid)
            if len(out) >= cap: break
        return out

    groups = {"combos": collections.defaultdict(list), "by_top": collections.defaultdict(list), "by_bottom": collections.defaultdict(list)}
    for fid, t, b, o in cand:
        groups["combos"][f"{t[1]}-{b[1]}-{o[1] if o else -1}"].append((fid, t, b, o))
        groups["by_top"][str(t[1])].append((fid, t, b, o)); groups["by_bottom"][str(b[1])].append((fid, t, b, o))
    index = {g: {k: diverse(v, MAX_COMBO) for k, v in d.items()} for g, d in groups.items()}
    need = sorted({fid for d in index.values() for v in d.values() for fid in v})
    print(f"착용 컷 후보 {len(cand):,}, 색인에 쓰이는 컷 {len(need):,}", flush=True)
    info = {fid: (t, b, o) for fid, t, b, o in cand}
    zm = zipfile.ZipFile(MODEL_ZIP); names = {os.path.basename(n): n for n in zm.namelist() if n.lower().endswith(".jpg")}
    embed = _clip(); T = embed.text(["a photo of a man wearing clothes", "a photo of a woman wearing clothes"])
    os.makedirs(os.path.join(DATA, "thumbs_wearing"), exist_ok=True); frames = {}; t0 = time.time()
    fids = [f for f in need if f"{f}.jpg" in names or f in names]
    for bi, batch in enumerate(_batches(fids, 64)):
        ims, keep = [], []
        for fid in batch:
            nm = names.get(f"{fid}.jpg") or names.get(fid)
            try: im = Image.open(io.BytesIO(zm.read(nm))).convert("RGB")
            except Exception: continue
            ims.append(im); keep.append(fid)
        if not ims: continue
        X = embed(ims); z_ = 100.0 * X @ T.T; z_ = z_ - z_.max(1, keepdims=True); pr = np.exp(z_); pr /= pr.sum(1, keepdims=True)
        for fid, im, pm in zip(keep, ims, pr[:, 0]):
            im.thumbnail((640, 640)); rel = f"data/thumbs_wearing/{fid}.jpg"; im.save(os.path.join(HERE, rel), "JPEG", quality=82)
            t, b, o = info[fid]
            frames[fid] = {"file": rel, "top": t[2], "bottom": b[2], "outer": o[2] if o else None, "sex": "M" if pm >= 0.8 else ("F" if pm <= 0.2 else "?"), "pm": round(float(pm), 3), "pattern": t[3]}
        if bi % 20 == 0: print(f"  {len(frames):,}/{len(fids):,}  {time.time()-t0:.0f}s", flush=True)
    for g in index:                                         # 썸네일 없는 컷은 색인에서 뺀다
        index[g] = {k: [f for f in v if f in frames] for k, v in index[g].items()}; index[g] = {k: v for k, v in index[g].items() if v}
    doc = ("착용 컷 색인 — 143 winfo 로 연결. frames[id] = 파일 · 상의색·하의색·아우터색(추정) · 모델 성별(CLIP zero-shot M/F/?) · P(남) · 상의 무늬. "
           "combos = '상의-하의-아우터'(-1 = 아우터 없음), by_top / by_bottom = 한쪽만 일치. 사진은 wearing_photo() 가 색·성별 조건으로 고른다.")
    io.open(os.path.join(DATA, "product_wearing.json"), "w", encoding="utf-8").write(json.dumps({"_doc": doc, "frames": frames, **index}, ensure_ascii=False))
    n_m = sum(1 for f in frames.values() if f["sex"] == "M")
    lines = ["", "## 착용 컷 색인", "", f"착용 컷 {len(frames):,} 장 (모델 성별 추정: 남 {n_m:,} / 여 {sum(1 for f in frames.values() if f['sex'] == 'F'):,} / 불명 {sum(1 for f in frames.values() if f['sex'] == '?'):,})",
             f"조합(동시 일치) {len(index['combos']):,} · 상의 기준 {len(index['by_top']):,} · 하의 기준 {len(index['by_bottom']):,}"]
    io.open(os.path.join(OUT, "product_attrs.md"), "a", encoding="utf-8").write("\n".join(lines) + "\n"); print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("step", choices=["scan", "feats", "train", "assign", "wearing", "all"]); a = ap.parse_args()
    for s in (["scan", "feats", "train", "assign", "wearing"] if a.step == "all" else [a.step]): globals()[s]()
