"""
색별 K-Fashion 아이템 컷 — 기존 data/thumbs/{부위}/{id}.jpg 는 아이템당 1장이라 "화이트 티셔츠" 추천에 갈색 컷이 붙는다.
product_attrs.py scan 이 모은 crop 표본(data/product/crops.json, 33,761장, 라벨 색 포함)에서 아이템×색마다 bbox 가 가장 큰 컷 1장을 잘라
data/thumbs/{부위}/{id}_{색}.jpg 로 저장. 런타임 kfashion_photos.thumb(part, id, color=…) 가 색 일치 컷을 우선한다.

  .\\.venv\\Scripts\\python.exe kfashion_color_thumbs.py     (원천 zip 필요, ~3분)
"""
import io, itertools, json, os, time
def itertools_groupby(keys):
    for g, ks in itertools.groupby(keys, key=lambda k: (k[0], k[1])): yield g, ks
from kfashion_photos import read_image, HERE, DATA, THUMBS

def main():
    rows = json.loads(io.open(os.path.join(DATA, "product", "crops.json"), encoding="utf-8").read())
    import collections
    t0 = time.time(); n = 0; best = {}; cnt = collections.Counter()
    for part, rs in rows.items():
        for r in rs:
            if not r["color"]: continue
            k = (part, r["item"], r["color"]); area = r["bbox"][2] * r["bbox"][3]; cnt[k] += 1
            if k not in best or area > best[k][0]: best[k] = (area, r)
    keep = set()                                                   # 아이템당 빈도 상위 6색만 (용량)
    for (part, item), ks in itertools_groupby(sorted(best, key=lambda k: (k[0], k[1], -cnt[k]))): keep.update(list(ks)[:6])
    best = {k: v for k, v in best.items() if k in keep}
    print(f"아이템×색 {len(best):,}")
    for (part, item, color), (_, r) in sorted(best.items()):
        rel = f"data/thumbs/{part}/{item}_{color}.jpg"; path = os.path.join(HERE, rel)
        if os.path.exists(path): continue
        img = read_image(r["img"])
        if img is None: continue
        x, y, w, h = r["bbox"]; m = 0.06
        crop = img.crop((int(max(0, x - w * m)), int(max(0, y - h * m)), int(min(img.width, x + w * (1 + m))), int(min(img.height, y + h * (1 + m)))))
        crop.thumbnail((300, 300)); os.makedirs(os.path.dirname(path), exist_ok=True); crop.save(path, "JPEG", quality=80); n += 1
        if n % 500 == 0: print(f"  {n}  {time.time()-t0:.0f}s", flush=True)
    print(f"저장 {n} 장 ({time.time()-t0:.0f}s) → {THUMBS}")

if __name__ == "__main__":
    main()
