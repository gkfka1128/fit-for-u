"""
남성 통계 v2 — AI Hub 의류 통합 데이터의 **성별 라벨**(착용 사진 29.7만, 남 7.2만)로 "이 속성/색을 남성이 얼마나 입나"를 잰다.
CLIP 추정(kfashion_sex.py, 1%·노이즈)을 대체. 결과는 data/kfashion_male.json 에 item_lift / color_lift 로 들어가고 rule_engine.male_lift 가 우선 사용.

  속성별 lift  = log( P(남 | 속성값) / P(남) )   ← 의류 통합 데이터 착용 사진에서
  K-Fashion 후보 아이템 lift = 매핑되는 속성(카테고리·넥·소매·기장·핏) lift 의 가중 평균, ±1.5 클램프
  어휘가 달라 매핑표(MAP)를 둔다. 매핑 안 되는 값(탑·짚업·패딩·래깅스 등)은 0.

  .\.venv\Scripts\python.exe clothes_male.py
출력: data/kfashion_male.json (갱신), runs/male_eval_v2.md
"""
import collections, io, json, math, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
PARTS = ("상의", "하의", "아우터")
CLAMP = 1.5

# K-Fashion 값 → (의류통합 컬럼, 값들)
MAP = {
    ("상의", "카테고리"): {"티셔츠": ("category", ["02t-shirt"]), "블라우스": ("category", ["01blouse"]), "니트웨어": ("category", ["03sweater"]), "셔츠": ("category", ["04shirt"]),
                       "후드티": ("topneck_color_design", ["hood"])},
    ("상의", "넥라인"): {"라운드넥": ("topneck_color_design", ["round neck"]), "브이넥": ("topneck_color_design", ["V-neck"]), "터틀넥": ("topneck_color_design", ["turtle neck"]),
                      "유넥": ("topneck_color_design", ["U-neck"]), "후드": ("topneck_color_design", ["hood"]), "스퀘어넥": ("topneck_color_design", ["square neck"]),
                      "오프숄더": ("topneck_color_design", ["off shoulder"]), "보트넥": ("topneck_color_design", ["boat neck"])},
    ("상의", "소매기장"): {"긴팔": ("sleeve_length_type", ["long sleeves"]), "반팔": ("sleeve_length_type", ["short sleeves"]), "민소매": ("sleeve_length_type", ["sleeveless"])},
    ("상의", "기장"): {"크롭": ("top_length_type", ["crop"]), "롱": ("top_length_type", ["long"]), "노멀": ("top_length_type", ["normal"])},
    ("하의", "카테고리"): {"팬츠": ("category", ["01pants"]), "청바지": ("category", ["01pants"]), "조거팬츠": ("category", ["01pants"]), "스커트": ("category", ["02skirt"])},
    ("하의", "핏"): {"노멀": ("pants_silhouette", ["normal"]), "루즈": ("pants_silhouette", ["loose"]), "스키니": ("pants_silhouette", ["skinny"]), "와이드": ("pants_silhouette", ["wide"]), "벨보텀": ("pants_silhouette", ["bell-bottom"])},
    ("아우터", "카테고리"): {"재킷": ("category", ["02jacket"]), "가디건": ("category", ["04cardigan"]), "베스트": ("category", ["05vest"]), "코트": ("category", ["01coat"]), "점퍼": ("category", ["03jumper"])},
    ("아우터", "기장"): {"크롭": ("top_length_type", ["crop"]), "롱": ("top_length_type", ["long"]), "노말": ("top_length_type", ["normal"]), "하프": ("top_length_type", ["midi", "short"])},
}
WEIGHT = {"카테고리": 1.0, "넥라인": 0.7, "소매기장": 0.5, "기장": 0.5, "핏": 0.8}
COLOR = {"블랙": "Black", "화이트": "White", "그레이": "Gray", "베이지": "Beige", "블루": "Blue", "그린": "Green", "브라운": "Brown", "핑크": "Pink", "레드": "Red",
         "퍼플": "Purple", "옐로우": "Yellow", "오렌지": "Orange", "네이비": "Blue", "스카이블루": "Blue", "카키": "Green", "와인": "Red", "라벤더": "Purple",
         "민트": "Green", "실버": "Gray", "골드": "Yellow", "네온": "Yellow"}

def main():
    df = pd.read_csv(os.path.join(DATA, "clothes_meta.csv"), dtype=str, keep_default_na=False)
    df = df[df.view == "wear"].copy(); df["male"] = (df.gender == "MALE").astype(int)
    df["color1"] = df.color.str.split(",").str[0]
    pM = df.male.mean(); print(f"착용 사진 {len(df):,}, P(남) = {pM:.3f}")
    def lift(col, values, part=None):
        d = df
        if col == "category": part = None                      # 카테고리는 부위 필터 없이 (베스트는 02top_05vest 로 들어 있음)
        if part == "상의": d = df[df.part == "02top"]
        elif part == "하의": d = df[df.part == "04bottom"]
        elif part == "아우터": d = df[df.part == "01outer"]
        s = d[d[col].isin(values)]
        if len(s) < 30: return None, len(s)
        return max(-CLAMP, min(CLAMP, math.log(((s.male.sum() + 1) / (len(s) + 2)) / pM))), len(s)

    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    item_lift, attr_table = {}, []
    for part in PARTS:
        item_lift[part] = {}
        cache = {}
        for i, it in enumerate(items[part]):
            num = den = 0.0
            for attr, w in WEIGHT.items():
                v = it["attrs"].get(attr); m = MAP.get((part, attr), {}).get(v)
                if not m: continue
                if (part, attr, v) not in cache:
                    L, n = lift(m[0], m[1], part); cache[(part, attr, v)] = L
                    attr_table.append((part, attr, v, L, n))
                L = cache[(part, attr, v)]
                if L is None: continue
                num += w * L; den += w
            item_lift[part][str(i)] = round(max(-CLAMP, min(CLAMP, num / den)), 3) if den else 0.0
    color_lift = {}
    for part in PARTS:
        color_lift[part] = {}
        for kc, ec in COLOR.items():
            L, n = lift("color1", [ec], part); color_lift[part][kc] = round(L, 3) if L is not None else 0.0

    f = os.path.join(DATA, "kfashion_male.json")
    male = json.loads(io.open(f, encoding="utf-8").read()) if os.path.exists(f) else {}
    male.update({"source_v2": "AI Hub 의류 통합 데이터 성별 라벨 (착용 사진)", "p_male": round(pM, 4), "n_wear": int(len(df)),
                 "item_lift": item_lift, "color_lift": color_lift})
    io.open(f, "w", encoding="utf-8").write(json.dumps(male, ensure_ascii=False)); print("updated", f)

    # ---- 리포트 + 남성 검증 FITB (CLIP 추정 검증셋 311 코디 — 비교용)
    L = ["# 남성 통계 v2 — 의류 통합 데이터 성별 라벨", "", f"착용 사진 {len(df):,} (남 {int(df.male.sum()):,}, P(남)={pM:.3f}). lift = log(P(남|속성)/P(남)), ±{CLAMP} 클램프.", "",
         "## 속성별 남성 lift (K-Fashion 값 → 의류통합 값)", "", "| 부위 | 속성 | 값 | lift | n |", "|---|---|---|---|---|"]
    for part, attr, v, Lv, n in sorted(attr_table, key=lambda t: (t[0], t[1], -(t[3] or -9))):
        L.append(f"| {part} | {attr} | {v} | {'—' if Lv is None else f'{Lv:+.2f}'} | {n:,} |")
    L += ["", "## 색 남성 lift (상의)", "", "| 색 | lift |", "|---|---|"] + [f"| {k} | {v:+.2f} |" for k, v in sorted(color_lift["상의"].items(), key=lambda kv: -kv[1])]
    top = sorted(((p, i, v) for p in PARTS for i, v in item_lift[p].items()), key=lambda t: -t[2])[:8]
    bot = sorted(((p, i, v) for p in PARTS for i, v in item_lift[p].items()), key=lambda t: t[2])[:8]
    L += ["", "## K-Fashion 후보 아이템 중 남성 lift 상·하위", ""] + [f"- {p} {v:+.2f} {items[p][int(i)]['attrs']}" for p, i, v in top] + ["", "(하위)", ""] + [f"- {p} {v:+.2f} {items[p][int(i)]['attrs']}" for p, i, v in bot]
    try:
        from kfashion_male import load_sex, scan, evaluate
        from rule_engine import RuleEngine
        m_ids, _, _, _ = load_sex(0.8, 0.95); _, _, _, _, va = scan("val", m_ids["val"], items)
        res = evaluate(RuleEngine(), None, va)
        L += ["", "## 남성 검증 FITB (CLIP 추정 val 311 코디, 비교용 — v2 lift 적용)", ""]
        for h, r in res.items():
            L += [f"### {h} (n={r['n']})", "", "| 방법 | Hit@1 | Hit@5 | Hit@10 | MRR |", "|---|---|---|---|---|"]
            for mname, v in r.items():
                if mname != "n": L.append(f"| {mname} | {v['hit@1']*100:.1f}% | {v['hit@5']*100:.1f}% | {v['hit@10']*100:.1f}% | {v['mrr']:.3f} |"); print(f"[{h}] {mname:16s} hit@5 {v['hit@5']*100:5.1f}%")
            L.append("")
    except Exception as e:
        L.append(f"(평가 생략: {e})")
    os.makedirs(OUT, exist_ok=True); io.open(os.path.join(OUT, "male_eval_v2.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[4:40])); print("saved runs/male_eval_v2.md")

if __name__ == "__main__":
    main()
