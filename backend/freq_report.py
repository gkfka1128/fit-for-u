"""
추천 빈도 점검 — 여러 사용자·날씨·상황 조합으로 추천을 돌려 아이템이 얼마나 자주 나오는지 센다.
  너무 자주 나오는 아이템(한 벌이 전체의 큰 몫)과, 후보인데 한 번도 안 나오는 아이템을 찾는 용도.
  .\\.venv\\Scripts\\python.exe freq_report.py [--n 600] [--seed 0]
"""
import argparse, collections, json, random, sys

import ffu_web_bridge as w

GROUPS, BUILDS = ("상체형", "균형", "하체형"), ("마름", "보통", "통통")
TEMPS = (-3, 3, 7, 10, 14, 18, 21, 25, 30)
SITS = ("학교", "데이트", "출근", "친구와 약속", "운동", "여행")
STYLES = ("캐주얼", "미니멀", "스트릿", "스포티", "댄디")
FITS = ("오버핏", "레귤러핏", "슬림핏")


def scenarios(n, seed):
    rnd = random.Random(seed)
    for _ in range(n):
        g = rnd.choice(("남성", "여성"))
        yield ({"gender": g, "height": 170, "weight": 65, "style": rnd.choice(STYLES), "fit": rnd.choice(FITS)},
               {"sex": "M" if g == "남성" else "F", "group": rnd.choice(GROUPS), "build": rnd.choice(BUILDS), "leg": "보통"},
               {"feels_like": rnd.choice(TEMPS), "precip_prob": rnd.choice((10, 10, 10, 70))}, rnd.choice(SITS))


def run(n=600, seed=0, eng=None):
    eng = eng or w.engine()
    first = {p: collections.Counter() for p in ("상의", "하의", "아우터")}
    allo = {p: collections.Counter() for p in ("상의", "하의", "아우터")}
    slots = collections.Counter()
    for prof, body, wx, sit in scenarios(n, seed):
        style = w.engine_style(prof, sit, body["sex"])
        res = eng.recommend(body, w.engine_weather(wx), style=style, pref=w.FitPreference(prof["fit"]))
        for k, o in enumerate(res["outfits"]):
            for part, key in (("상의", "top"), ("하의", "bottom"), ("아우터", "outer")):
                x = o.get(key)
                if not x: continue
                name = " ".join(v for v in (x.get("핏") if x.get("핏") != "노멀" else None, x.get("기장"), x.get("소재"), x.get("카테고리")) if v)
                allo[part][(x["id"], name)] += 1; slots[part] += 1
                if k == 0: first[part][(x["id"], name)] += 1
    return {"n": n, "first": first, "all": allo, "slots": slots, "pool": {p: len(eng.items[p]) for p in allo}}


def summary(r, top=8):
    out = []
    for p in ("상의", "하의", "아우터"):
        c, f = r["all"][p], r["first"][p]; tot = sum(c.values()) or 1; ftot = sum(f.values()) or 1
        out.append(f"\n[{p}] 후보 {r['pool'][p]}개 중 {len(c)}개 사용 · 1순위에 쓰인 것 {len(f)}개")
        out.append("  전체 3안 기준 상위: " + ", ".join(f"{nm}#{i} {100 * v / tot:.1f}%" for (i, nm), v in c.most_common(top)))
        out.append("  1순위 기준 상위:   " + ", ".join(f"{nm}#{i} {100 * v / ftot:.1f}%" for (i, nm), v in f.most_common(top)))
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=600); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    print(summary(run(a.n, a.seed)))
