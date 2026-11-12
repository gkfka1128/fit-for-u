"""
K-Fashion 실제 사진 — 후보 아이템별 대표 컷(crop) + 코디 조합별 사진 색인

  1) 라벨 96.8만 장 스캔 → 후보 아이템(kfashion_items.json, 부위별 index = id)마다 잘 보이는 컷 6장 (bbox 큰 순)
     + 조합 색인 "상의id-하의id-아우터id" → 그 코디를 실제로 입은 사진 id (아우터 없으면 -1)
  2) 원천데이터 zip 3개에서 아이템별 1장을 bbox 로 잘라 data/thumbs/{부위}/{id}.jpg (846장, 배포용)
  런타임: outfit_photo(top,bottom,outer) — 조합 색인에 있는 사진을 원천 zip 에서 꺼내 data/photo_cache 에 캐시.
          원천 zip 이 없는 환경(Backend)에선 썸네일만 쓴다.

  .\.venv\Scripts\python.exe kfashion_photos.py            # 1)+2)  (라벨 스캔 ~5분)
  .\.venv\Scripts\python.exe kfashion_photos.py --skip-scan # 색인 있으면 2)만
출력: data/kfashion_photo_index.json, data/thumbs/**, data/kfashion_thumbs.json
"""
import argparse, collections, io, json, os, time, zipfile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
TRAIN = os.path.join(HERE, "..", "Data", "K-Fashion 이미지", "Training")
LABEL_ZIP = os.path.join(TRAIN, "라벨링데이터.zip")
IMG_ZIPS = [os.path.join(TRAIN, f"원천데이터_{i}.zip") for i in (1, 2, 3)]
INDEX = os.path.join(DATA, "kfashion_photo_index.json")
THUMBS = os.path.join(DATA, "thumbs"); THUMB_META = os.path.join(DATA, "kfashion_thumbs.json")
CACHE = os.path.join(DATA, "photo_cache")
PARTS = ("상의", "하의", "아우터")
PER_ITEM, PER_COMBO = 6, 8


# ---------------------------------------------------------------- 1) 라벨 스캔
def scan(limit=None):
    from kfashion_cooc import KEYS, first
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    key_of = lambda p, a: tuple(a.get(k) for k in KEYS[p])
    cand = {p: {key_of(p, it["attrs"]): i for i, it in enumerate(items[p])} for p in PARTS}

    z = zipfile.ZipFile(LABEL_ZIP); names = [n for n in z.namelist() if n.lower().endswith(".json")]
    if limit: names = names[:limit]
    best = {p: collections.defaultdict(list) for p in PARTS}     # part → item id → [(area_ratio, img id, bbox, style)]
    combos = collections.defaultdict(list)                        # "t-b-o" → [(전신점수, img id, 상의색, 하의색, 아우터색)]
    t0 = time.time()
    for n, nm in enumerate(names):
        try:
            lab = json.loads(z.read(nm).decode("utf-8"))
            info = lab["이미지 정보"]; d = lab["데이터셋 정보"]["데이터셋 상세설명"]
        except Exception:
            continue
        img_id, W, H = info["이미지 식별자"], info["이미지 너비"], info["이미지 높이"]
        style = (first(d["라벨링"].get("스타일", [{}])[0], "스타일") if d["라벨링"].get("스타일") else None)
        ids, rects, cols = {}, {}, {}
        for p in PARTS:
            lab_p = [x for x in d["라벨링"].get(p, []) if x]
            if not lab_p or not first(lab_p[0], "카테고리"): continue
            i = cand[p].get(key_of(p, {k: first(lab_p[0], k) for k in KEYS[p]}))
            if i is None: continue
            ids[p] = i; cols[p] = first(lab_p[0], "색상")
            rect = [r for r in d["렉트좌표"].get(p, []) if r]
            if rect and W and H:
                r = rect[0]; ratio = (r["가로"] * r["세로"]) / (W * H); rects[p] = r
                b = best[p][i]
                if len(b) < PER_ITEM or ratio > b[-1][0]:
                    b.append((ratio, img_id, [r["X좌표"], r["Y좌표"], r["가로"], r["세로"]], style))
                    b.sort(key=lambda t: -t[0]); del b[PER_ITEM:]
        if "상의" in ids and "하의" in ids and "상의" in rects and "하의" in rects and H:
            # 코디 사진은 전신이 잘리지 않은 컷 우선: 상의 bbox 가 위 끝에, 하의 bbox 가 아래 끝에 붙어 있으면 감점
            full = 2 - (rects["상의"]["Y좌표"] < 0.03 * H) - (rects["하의"]["Y좌표"] + rects["하의"]["세로"] > 0.97 * H) + 0.1 * (H >= 1000)
            k = f"{ids['상의']}-{ids['하의']}-{ids.get('아우터', -1)}"; b = combos[k]
            if len(b) < PER_COMBO or full > b[-1][0]:
                b.append((full, img_id, cols.get("상의"), cols.get("하의"), cols.get("아우터"))); b.sort(key=lambda t: -t[0]); del b[PER_COMBO:]
        if n % 100000 == 0 and n: print(f"  {n:,}/{len(names):,}  {time.time()-t0:.0f}s", flush=True)
    out = {"items": {p: {str(i): [dict(ratio=round(r, 3), id=g, bbox=bb, style=s) for r, g, bb, s in v] for i, v in best[p].items()} for p in PARTS},
           "combos": {k: [list(t[1:]) for t in v] for k, v in combos.items()}}
    io.open(INDEX, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
    print(f"index: items {[len(out['items'][p]) for p in PARTS]}, combos {len(combos):,}  ({time.time()-t0:.0f}s)")
    return out


# ---------------------------------------------------------------- 원천 zip 접근 (lazy)
_zips, _where = None, None
def _open_zips():
    global _zips, _where
    if _zips is None:
        _zips, _where = [], {}
        for zp in IMG_ZIPS:
            if not os.path.exists(zp): continue
            z = zipfile.ZipFile(zp); _zips.append(z)
            for nm in z.namelist():
                if nm.lower().endswith(".jpg"):
                    _where[int(os.path.splitext(os.path.basename(nm))[0])] = (len(_zips) - 1, nm)
    return _zips, _where

def read_image(img_id):
    """원천 zip 에서 사진 1장 (없으면 None)"""
    zips, where = _open_zips()
    hit = where.get(int(img_id))
    if hit is None: return None
    z, nm = zips[hit[0]], hit[1]
    return Image.open(io.BytesIO(z.read(nm))).convert("RGB")


# ---------------------------------------------------------------- 2) 썸네일 추출
def extract(index, max_side=360, margin=0.06):
    meta = {}
    t0 = time.time(); n = 0
    for p in PARTS:
        os.makedirs(os.path.join(THUMBS, p), exist_ok=True)
        for i, cuts in index["items"][p].items():
            for c in cuts:                                        # 첫 번째 성공하는 컷
                img = read_image(c["id"])
                if img is None: continue
                x, y, w, h = c["bbox"]; mx, my = w * margin, h * margin
                box = (max(0, x - mx), max(0, y - my), min(img.width, x + w + mx), min(img.height, y + h + my))
                crop = img.crop(tuple(int(v) for v in box))
                crop.thumbnail((max_side, max_side))
                rel = f"data/thumbs/{p}/{i}.jpg"
                crop.save(os.path.join(HERE, rel), "JPEG", quality=82)
                meta[f"{p}/{i}"] = {"path": rel, "img_id": c["id"], "style": c["style"]}
                n += 1; break
        print(f"  {p}: {sum(1 for k in meta if k.startswith(p))}/{len(index['items'][p])}  ({time.time()-t0:.0f}s)", flush=True)
    io.open(THUMB_META, "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False, indent=0))
    print(f"thumbs {n} → {THUMBS}")


# ---------------------------------------------------------------- 런타임
_index = None
def outfit_photo(top, bottom, outer=None, colors=None, max_side=640):
    """추천 조합을 실제로 입은 K-Fashion 사진 → (캐시된 파일 경로(코드 폴더 기준) 또는 None, 아우터까지 일치 여부).
    아우터까지 일치하는 사진을 먼저, 없으면 상의+하의만 일치(아우터 없이 찍힌 컷). colors={"상의":색,"하의":색,"아우터":색} 를 주면 색이 맞는 컷 우선."""
    global _index
    if _index is None:
        _index = json.loads(io.open(INDEX, encoding="utf-8").read())["combos"] if os.path.exists(INDEX) else {}
    keys = [f"{top}-{bottom}-{outer if outer is not None else -1}"]
    if outer is not None: keys.append(f"{top}-{bottom}--1")
    colors = colors or {}
    def match(row):  # 색 일치 수 (상의·하의 2점, 아우터 1점)
        return 2 * (row[1] == colors.get("상의")) + 2 * (row[2] == colors.get("하의")) + (row[3] == colors.get("아우터"))
    for k in keys:
        rows = sorted(enumerate(_index.get(k, [])), key=lambda t: (-match(t[1]), t[0]))   # 색 일치 → 전신 컷 순
        for _, row in rows:
            img_id = row[0]
            rel = f"data/photo_cache/{img_id}.jpg"; path = os.path.join(HERE, rel)
            if os.path.exists(path): return rel, k == keys[0]
            try:
                img = read_image(img_id)
            except Exception:
                img = None
            if img is None: continue                              # 원천 zip 없는 환경
            os.makedirs(CACHE, exist_ok=True); img.thumbnail((max_side, max_side)); img.save(path, "JPEG", quality=85)
            return rel, k == keys[0]
    return None, False

_fam = None
def _family():
    global _fam
    if _fam is None:
        p = os.path.join(HERE, "rules", "body_rules.json")
        _fam = {c: f for f, cs in json.loads(io.open(p, encoding="utf-8").read())["color_family"].items() for c in cs} if os.path.exists(p) else {}
    return _fam


def _jload(name):
    p = os.path.join(DATA, name)
    return json.loads(io.open(p, encoding="utf-8").read()) if os.path.exists(p) else {}


def _exists(rel):
    return bool(rel) and os.path.exists(os.path.join(HERE, rel))


def thumb(part, item_id, sex=None, color=None):
    """아이템 컷 경로. 색을 주면 그 색으로 입은 K-Fashion 컷(data/thumbs/{부위}/{id}_{색}.jpg)을 우선, 없으면 대표 컷 (없으면 None).
    sex 는 호환용 인자 — K-Fashion 크롭은 옷만 잘라낸 컷이라 성별로 나누지 않는다"""
    if color:
        rel = f"data/thumbs/{part}/{item_id}_{color}.jpg"
        if _exists(rel): return rel
    rel = f"data/thumbs/{part}/{item_id}.jpg"
    return rel if _exists(rel) else None


_wear = None
def wear_photo(part, item_id, color=None):
    """남성 단품 착용 컷 (AI Hub 의류 통합 데이터, clothes_wear.py) — 색이 맞는 컷 우선"""
    global _wear
    if _wear is None: _wear = _jload("clothes_wear_photos.json")
    rows = [r for r in _wear.get(part, {}).get(str(item_id), []) if _exists(r["file"])]
    rows.sort(key=lambda r: r.get("color") != color)
    return rows[0]["file"] if rows else None


_prod = None
def product_photo(part, item_id, color=None):
    """스튜디오 제품 컷 (AI Hub 143). 색이 다르면 쓰지 않는다(색 엄격). 무늬 없는 컷 우선"""
    global _prod
    if _prod is None: _prod = _jload("product_photos.json")
    rows = [r for r in _prod.get(part, {}).get(str(item_id), []) if r.get("file") and _exists(r["file"])]
    if color: rows = [r for r in rows if r.get("color") == color]
    rows.sort(key=lambda r: (r.get("pattern") != "무지", -r.get("conf", 0)))
    return rows[0]["file"] if rows else None


_wearing = None
def wearing_photo(top, bottom, outer=None, colors=None, sex=None):
    """143 착용 컷 → (경로, 일치 수준, 모델 성별 추정). 수준 exact(상의·하의·아우터) > top_bottom > top > bottom.
    색 규칙: 상의만/하의만 일치면 그 부위 색 동일, 둘 다면 한쪽 동일 + 다른 쪽 같은 색 계열. 성별: 남성은 남성 모델만, 여성은 남성 모델 제외"""
    global _wearing
    if _wearing is None: _wearing = _jload("product_wearing.json")
    W = _wearing
    if not W: return None, None, None
    colors = colors or {}; fam = _family(); frames = W.get("frames", {})
    def same(f, part): return bool(colors.get(part)) and f.get(part) == colors[part]
    def similar(f, part): return bool(colors.get(part)) and f.get(part) is not None and (f[part] == colors[part] or (fam.get(f[part]) and fam.get(f[part]) == fam.get(colors[part])))
    def color_ok(f, level):
        if level == "top": return same(f, "top")
        if level == "bottom": return same(f, "bottom")
        return (same(f, "top") and similar(f, "bottom")) or (same(f, "bottom") and similar(f, "top"))
    def sex_ok(f):
        if sex == "M": return f.get("sex") == "M"
        if sex == "F": return f.get("sex") != "M"
        return True
    tries = (("exact", f"{top}-{bottom}-{outer}" if outer is not None else None, W.get("combos", {})),
             ("top_bottom", f"{top}-{bottom}--1", W.get("combos", {})), ("top", str(top), W.get("by_top", {})), ("bottom", str(bottom), W.get("by_bottom", {})))
    for level, key, table in tries:
        if key is None: continue
        for fid in table.get(key, []):
            f = frames.get(fid)
            if f and sex_ok(f) and color_ok(f, level) and _exists(f["file"]): return f["file"], level, f.get("sex")
    return None, None, None


def shoe_thumb(name, sex):
    rel = f"data/thumbs/신발/{name}_{'M' if sex == 'M' else 'F'}.jpg"
    if _exists(rel): return rel
    rel = f"data/thumbs/신발/{name}_{'F' if sex == 'M' else 'M'}.jpg"
    return rel if _exists(rel) else None


def outfit_photos(engine, top, bot, out, colors, sex, shoe):
    """rule_engine 이 부르는 진입점 → photo dict. top/bot/out = (item id, item) 또는 None"""
    ids = {"상의": top[0], "하의": bot[0], "아우터": out[0] if out else None}; colors = colors or {}
    kc = {"상의": colors.get("상의"), "하의": colors.get("하의"), "아우터": colors.get("아우터")}
    photo = {"outfit": None, "outfit_exact": False, "outfit_male": False, "wearing": None, "wearing_match": None, "product": {}, "wear": {}, "items": {}}
    if sex != "M":                                            # K-Fashion 착장 사진은 거의 여성 모델 → 남성에게는 보여주지 않는다
        try:
            rel, exact = outfit_photo(ids["상의"], ids["하의"], ids["아우터"], kc)
            photo["outfit"], photo["outfit_exact"] = rel, exact
        except Exception:
            pass
    w, level, sx = wearing_photo(ids["상의"], ids["하의"], ids["아우터"], {"top": kc["상의"], "bottom": kc["하의"], "outer": kc["아우터"]}, sex)
    if w: photo["wearing"], photo["wearing_match"], photo["wearing_sex"] = w, level, sx
    for part, key in (("상의", "top"), ("하의", "bottom"), ("아우터", "outer")):
        if ids[part] is None: continue
        photo["items"][key] = thumb(part, ids[part], sex, kc[part])
        p = product_photo(part, ids[part], kc[part])
        if p: photo["product"][key] = p
        if sex == "M":
            wp = wear_photo(part, ids[part], kc[part])
            if wp: photo["wear"][key] = wp
    if shoe: photo["items"]["shoes"] = shoe_thumb(shoe, sex)
    return photo


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--skip-scan", action="store_true"); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.skip_scan and os.path.exists(INDEX):
        index = json.loads(io.open(INDEX, encoding="utf-8").read())
    else:
        print("scanning labels …"); index = scan(a.limit)
    print("extracting thumbs …"); extract(index)

if __name__ == "__main__":
    main()
