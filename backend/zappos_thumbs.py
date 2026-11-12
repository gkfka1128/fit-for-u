"""
신발 컷 — UT Zappos50K (미국 Zappos.com 카탈로그 50,025장, 텍사스대 공개) 에서 우리 신발 어휘 14종 × 성별 대표 이미지를 뽑는다. (9/22)

⚠ 데이터 성격: 서구(미국) 쇼핑몰 상품 사진. 코디 정보 없음 → 여기선 **신발 사진·속성 사전**으로만 쓴다. 성별 라벨(Men/Women)이 있어 남녀 컷을 따로 고를 수 있다.
  라이선스: 학술·연구용 (Yu & Grauman, CVPR 2014). 상용 시 교체.

  .\.venv\Scripts\python.exe zappos_thumbs.py
출력: data/thumbs/신발/{신발명}_{M|F}.jpg, data/zappos_shoes.json (매핑·건수)
"""
import csv, io, json, os, zipfile
import scipy.io as sio
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); ZD = os.path.join(HERE, "..", "Data", "UT-Zappos50K")
OUT = os.path.join(DATA, "thumbs", "신발")

# 우리 신발명 → (Category/SubCategory, 추가 조건 함수)
MAP = {
    "스니커즈":      ("Shoes/Sneakers and Athletic Shoes", lambda r: "Lace up" in r["Closure"] and "Canvas" not in r["Material"]),
    "캔버스 스니커즈": ("Shoes/Sneakers and Athletic Shoes", lambda r: "Canvas" in r["Material"]),
    "러닝화":        ("Shoes/Sneakers and Athletic Shoes", lambda r: "Mesh" in r["Material"] or "Synthetic" in r["Material"]),
    "로퍼":          ("Shoes/Loafers", lambda r: "Suede" not in r["Material"]),
    "스웨이드 로퍼":  ("Shoes/Loafers", lambda r: "Suede" in r["Material"]),
    "옥스포드":      ("Shoes/Oxfords", lambda r: True),
    "샌들":          ("Sandals/Flat", lambda r: True),
    "슬리퍼":        ("Slippers/Slipper Flats", lambda r: True),
    "첼시 부츠":     ("Boots/Ankle", lambda r: "Elastic Gore" in r["Closure"]),
    "앵클 부츠":     ("Boots/Ankle", lambda r: "Elastic Gore" not in r["Closure"] and "Lace up" not in r["Closure"]),
    "워커":          ("Boots/Ankle", lambda r: "Lace up" in r["Closure"]),
    "롱 부츠":       ("Boots/Knee High", lambda r: True),
    "플랫 슈즈":     ("Shoes/Flats", lambda r: True),
    "펌프스":        ("Shoes/Heels", lambda r: True),
}

def main():
    zd = zipfile.ZipFile(os.path.join(ZD, "ut-zap50k-data.zip"))
    rows = list(csv.DictReader(io.StringIO(zd.read("ut-zap50k-data/meta-data.csv").decode("utf-8", "ignore"))))
    paths = [p[0] for p in sio.loadmat(io.BytesIO(zd.read("ut-zap50k-data/image-path.mat")))["imagepath"][:, 0]]
    assert len(rows) == len(paths)
    zi = zipfile.ZipFile(os.path.join(ZD, "ut-zap50k-images-square.zip")); members = set(zi.namelist())
    os.makedirs(OUT, exist_ok=True); meta = {"_doc": "UT Zappos50K 대표 컷 (서구 카탈로그, 연구용). 신발명_{M|F}.jpg", "counts": {}, "picked": {}}
    for name, (cat, cond) in MAP.items():
        for g, tag in (("Men", "M"), ("Women", "F")):
            cands = [(r, p) for r, p in zip(rows, paths) if p.startswith(cat + "/") and g in r["Gender"] and cond(r)]
            meta["counts"][f"{name}_{tag}"] = len(cands)
            # 가죽·검정 계열이 무난하므로 Material 에 Leather 가 있는 것을 앞에, 그 중 첫 번째
            cands.sort(key=lambda t: ("Leather" not in t[0]["Material"], t[1]))
            for r, p in cands:
                m = "ut-zap50k-images-square/" + p
                if m not in members: continue
                img = Image.open(io.BytesIO(zi.read(m))).convert("RGB"); img.thumbnail((360, 360))
                img.save(os.path.join(OUT, f"{name}_{tag}.jpg"), "JPEG", quality=85)
                meta["picked"][f"{name}_{tag}"] = {"path": p, "cid": r["CID"], "material": r["Material"], "closure": r["Closure"]}
                break
    io.open(os.path.join(DATA, "zappos_shoes.json"), "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False, indent=1))
    for k, v in meta["counts"].items(): print(f"  {k:16s} 후보 {v:5d}  {'✓' if k in meta['picked'] else '✗ 없음'}")
    print("saved", OUT)

if __name__ == "__main__":
    main()
