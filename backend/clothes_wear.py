"""
남성 착용 컷 — K-Fashion 착장 사진은 거의 여성 모델(남성 추정 0.9%)이라, 남성 사용자에겐 **의류 통합 데이터**(AI Hub, 성별 라벨 확실,
남성 착용 사진 7.2만)에서 "그 아이템을 입은 남성" 컷을 부위별로 꺼내 보여준다. 단품 착용 사진이라 코디(상의+하의 조합) 정답은 아니다.

  K-Fashion 후보 아이템 → 의류 통합 속성 매핑(clothes_male.MAP: 카테고리·넥·소매·기장·핏) → 남성 wear 사진 필터
  매칭 3장 미만이면 덜 중요한 조건부터 뺀다 (기장 → 소매 → 넥 → 핏, 카테고리는 유지). 색이 다양하도록 색별 1장씩 최대 6장.
  썸네일은 원천 zip 에서 꺼내 data/thumbs_wear/{부위}/{id}_{k}.jpg (긴 변 420px) — 배포 가능, 런타임에 330GB 필요 없음.

  .\.venv\Scripts\python.exe clothes_wear.py [--dry]
출력: data/clothes_wear_photos.json, data/thumbs_wear/, runs/wear_photos.md
"""
import argparse, collections, io, json, os, sys, time, zipfile
import pandas as pd
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clothes_male import MAP, COLOR
from clothes_meta import ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
THUMBS = os.path.join(DATA, "thumbs_wear"); INDEX = os.path.join(DATA, "clothes_wear_photos.json")
PARTS = {"상의": "02top", "하의": "04bottom", "아우터": "01outer"}
RELAX = ["기장", "소매기장", "넥라인", "핏"]          # 뺄 순서 (뒤로 갈수록 중요)
MAX_PER_ITEM, MIN_MATCH, MAX_SIDE = 6, 3, 420
# 매핑표에 없는 K-Fashion 카테고리 보강 (의류 통합 어휘 기준)
EXTRA = {("상의", "후드티"): ("topneck_color_design", ["hood"]), ("하의", "조거팬츠"): ("category", ["01pants"]),
         ("아우터", "짚업"): ("category", ["03jumper"]), ("아우터", "패딩"): ("category", ["03jumper"])}


def constraints(part, attrs):
    """K-Fashion 속성 → [(속성명, 의류통합 컬럼, 값들)]. 카테고리 매핑이 없으면 None (사진 없음)"""
    out = []
    for attr, v in attrs.items():
        m = MAP.get((part, attr), {}).get(v) or (EXTRA.get((part, v)) if attr == "카테고리" else None)
        if m: out.append((attr, m[0], m[1]))
    if not any(a == "카테고리" for a, _, _ in out): return None
    return out


def pick(df, cons):
    """조건 전부 → 부족하면 RELAX 순서로 하나씩 빼며 재시도. (rows, 뺀 조건 수)"""
    for n in range(len(RELAX) + 1):
        drop = set(RELAX[:n])
        d = df
        for attr, col, vals in cons:
            if attr in drop: continue
            d = d[d[col].isin(vals)]
        if len(d) >= MIN_MATCH: return d, n
    return d, len(RELAX)


def diverse(rows):
    """색별 1장씩(빈도순), 학습 split 우선, 최대 MAX_PER_ITEM"""
    rows = rows.assign(color1=rows.color.str.split(",").str[0])
    order = rows.color1.value_counts().index
    out = []
    for c in order:
        r = rows[rows.color1 == c].sort_values("split")          # train < valid
        out.append(r.iloc[0])
        if len(out) >= MAX_PER_ITEM: break
    return out


def zip_path(row):
    split = "Training" if row.split == "train" else "Validation"
    return os.path.join(ROOT, split, "01.원천데이터", row.zip.replace("TL_", "TS_" if split == "Training" else "VS_"))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true", help="색인만, 썸네일 추출 안 함"); a = ap.parse_args()
    t0 = time.time()
    df = pd.read_csv(os.path.join(DATA, "clothes_meta.csv"), dtype=str, keep_default_na=False)
    df = df[(df.view == "wear") & (df.gender == "MALE")].copy()
    print(f"남성 착용 사진 {len(df):,}")
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    index = {"_doc": "남성 착용 컷 — AI Hub 의류 통합 데이터(성별 라벨) 남성 wear 사진을 K-Fashion 후보 아이템에 속성 매핑으로 연결. "
                     "단품 착용 사진이라 코디 정답이 아니며, K-Fashion 착장 사진(여성 위주)의 남성 대체용. relax = 뺀 매칭 조건 수(0 = 전부 일치).",
             "source": "AI Hub 008.의류 통합 데이터(착용 이미지, 치수 및 원단 정보)", "max_side": MAX_SIDE}
    stats = collections.Counter(); zips = {}; n_img = 0
    for part, code in PARTS.items():
        index[part] = {}
        sub = df[(df.part == code) | (df.category == "05vest")] if part == "아우터" else df[df.part == code]   # 베스트는 의류 통합에선 02top
        for i, it in enumerate(items[part]):
            cons = constraints(part, it["attrs"])
            if cons is None: stats[f"{part} 매핑없음"] += 1; continue
            rows, relax = pick(sub, cons)
            if len(rows) == 0: stats[f"{part} 0장"] += 1; continue
            entries = []
            for k, r in enumerate(diverse(rows)):
                rel = f"data/thumbs_wear/{part}/{i}_{k}.jpg"; path = os.path.join(HERE, rel)
                if not a.dry and not os.path.exists(path):
                    zp = zip_path(r)
                    if zp not in zips: zips[zp] = zipfile.ZipFile(zp)
                    try:
                        img = Image.open(io.BytesIO(zips[zp].read("/" + r["name"] + ".jpg"))).convert("RGB")
                    except KeyError:
                        stats["zip 멤버 없음"] += 1; continue
                    img.thumbnail((MAX_SIDE, MAX_SIDE)); os.makedirs(os.path.dirname(path), exist_ok=True); img.save(path, "JPEG", quality=82)
                entries.append({"file": rel, "color": r.color.split(",")[0], "name": r["name"], "relax": relax}); n_img += 1
            if entries: index[part][str(i)] = entries; stats[f"{part} relax{relax}"] += 1
        print(f"{part}: {len(index[part])}/{len(items[part])} 아이템에 사진")
    io.open(INDEX, "w", encoding="utf-8").write(json.dumps(index, ensure_ascii=False))
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(THUMBS) for f in fs) / 1e6 if os.path.exists(THUMBS) else 0
    lines = ["# 남성 착용 컷 (의류 통합 데이터) — 후보 아이템 연결 결과", "",
             f"남성 wear 사진 {len(df):,} → 아이템 {sum(len(index[p]) for p in PARTS)} / {sum(len(items[p]) for p in PARTS)} 에 사진 {n_img} 장, {size:.0f}MB, {time.time()-t0:.0f}s", "",
             "| 부위 | 사진 있음 | 전부 일치(relax0) | 일부 완화 | 매핑 없음 | 0장 |", "|---|---|---|---|---|---|"]
    for p in PARTS:
        r0 = stats[f"{p} relax0"]; rx = sum(stats[f"{p} relax{n}"] for n in range(1, len(RELAX) + 1))
        lines.append(f"| {p} | {len(index[p])} / {len(items[p])} | {r0} | {rx} | {stats[f'{p} 매핑없음']} | {stats[f'{p} 0장']} |")
    lines += ["", "- 매핑 없음 = K-Fashion 카테고리가 의류 통합에 없음(탑·니트베이스·레깅스·스커트 등 — 남성 제외 항목이 대부분)",
              "- 완화 순서: 기장 → 소매 → 넥 → 핏. 카테고리는 항상 유지", "- ⚠ 단품 착용 사진 — 코디 조합 정답 아님. 남성 사용자에게 K-Fashion 여성 착장 대신 보여주는 용도"]
    os.makedirs(OUT, exist_ok=True); io.open(os.path.join(OUT, "wear_photos.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
