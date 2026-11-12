"""
추천 엔진 신뢰성 지표 (10/14 회의 "재현율·민감도" 요청 — 문하람 파트 몫) → runs/metrics_report.md

  ① 제약 위반률 (안전성): 모든 체형 × 체감온도 × 비 조합에서 추천에 날씨 금지 소재·소매, 성별 제외 아이템,
     아우터 필수/금지 위반, 비 오는 날 제외 신발이 섞이는 비율. 목표 0%.
  ② 체형 민감도: 규칙마다, 그 체형 조건일 때 규칙 대상 속성(예: 상의 핏=오버사이즈)이 추천에 나오는 비율을
     체형 규칙을 켰을 때 vs 껐을 때(use_body=False, 같은 체형·날씨) 비교. 가산 규칙은 늘고 감점 규칙은 줄어야 "반응한다".
     → 방향이 맞는 규칙 비율 = 민감도, 바뀌지 않은 규칙 = 후보에 그 속성이 거의 없거나 다른 신호에 묻힘.
  ③ 재현율@k 는 FITB 로 이미 측정 (runs/compat_eval.md — 가린 정답 1개가 상위 k 에 드는 비율 = recall@k).

  .\\.venv\\Scripts\\python.exe metrics_report.py   (약 5~10분, CPU)
"""
import collections, itertools, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from rule_engine import RuleEngine

FEELS = (-5, 3, 7, 10, 14, 18, 21, 25, 31)
PRECIP = (10, 80)
KEY = {"상의": "top", "하의": "bottom", "아우터": "outer"}


def bodies():
    for sx, g, b in itertools.product("FM", ("상체형", "균형", "하체형"), ("마름", "보통", "통통")):
        yield {"sex": sx, "group": g, "build": b, "leg": "보통"}
    for w in ("굴곡", "직선"):                                    # 허리 규칙 K1~K5 (정면 사진 경로, 여성)
        yield {"sex": "F", "group": "균형", "build": "보통", "leg": "보통", "waist": w}


def violations(e, body, weather, res):
    band = e.band(weather["feels_like"]); rain = res["rain"]; out = []
    for o in res["outfits"]:
        for part, key in KEY.items():
            x = o.get(key)
            if not x: continue
            it = e.items[part][x["id"]]
            if not e.weather_ok(part, it, band, rain): out.append(f"날씨 {part} {x['label']}")
            if not e.sex_ok(body["sex"], part, it): out.append(f"성별 {part} {x['label']}")
        if band["outer"] == "require" and not o.get("outer"): out.append("아우터 필수인데 없음")
        if band["outer"] == "forbid" and o.get("outer"): out.append("아우터 금지인데 있음")
        if rain and o["shoes"] in e.weather["rain"]["shoes_exclude"]: out.append(f"비 신발 {o['shoes']}")
    return out


def main():
    t0 = time.time(); e = RuleEngine()
    n_out = 0; viol = []
    share = collections.defaultdict(lambda: [0, 0, 0])               # rule id → [켬에서 대상 속성 수, 끔에서 수, 아이템 수]
    for body in bodies():
        rules = [r for r in e.body["rules"] if (r["sex"] in ("any", body["sex"])) and all(body.get(k) == v for k, v in r["when"].items())]
        for f, p in itertools.product(FEELS, PRECIP):
            w = {"feels_like": f, "precip_prob": p}
            on = e.recommend(body, w); off = e.recommend(body, w, use_body=False)
            for res in (on, off):
                n_out += len(res["outfits"]); viol += violations(e, body, w, res)
            for r in rules:
                k = KEY[r["part"]]
                for j, res in ((0, on), (1, off)):
                    share[r["id"]][j] += sum(1 for o in res["outfits"] if o.get(k) and o[k].get(r["attr"]) == r["value"])
                share[r["id"]][2] += sum(1 for o in on["outfits"] if o.get(k))
    rmap = {r["id"]: r for r in e.body["rules"]}
    rows, right, testable = [], 0, 0
    for rid, (a, b, n) in sorted(share.items(), key=lambda kv: kv[0]):
        r = rmap[rid]; d = (a - b) / n if n else 0.0
        moot = r["weight"] < 0 and b == 0                      # 감점 규칙인데 끈 상태에서도 0% — 뺄 것이 없어 측정 불가
        ok = (d > 0) if r["weight"] > 0 else (d < 0)
        testable += not moot; right += ok and not moot
        verdict = "✅" if ok else "· 해당 없음 (끈 상태에서도 0%)" if moot else "— 변화 없음" if a == b else "⚠ 반대"
        rows.append(f"| {rid} | {r['part']} {r['attr']}={r['value']} | {r['weight']:+.1f} | {100 * b / max(n, 1):.1f}% → {100 * a / max(n, 1):.1f}% | {verdict} |")
    L = ["# 추천 엔진 신뢰성 지표 — 제약 위반률 · 체형 민감도", "",
         f"체형 {len(list(bodies()))}종 × 체감온도 {len(FEELS)} × 강수 {len(PRECIP)} = {len(list(bodies())) * len(FEELS) * len(PRECIP)} 조건, 조건마다 규칙 켬·끔 2회 → 코디 {n_out}벌 ({time.time() - t0:.0f}초)", "",
         "## ① 제약 위반률 (안전성)", "",
         f"**{len(viol)} / {n_out} 벌 = {100 * len(viol) / n_out:.2f}%** — 날씨 금지 소재·소매, 성별 제외 아이템, 아우터 필수·금지, 비 오는 날 신발을 검사.", ""]
    if viol: L += ["위반 예:", ""] + [f"- {k} ×{c}" for k, c in collections.Counter(viol).most_common(10)] + [""]
    L += ["## ② 체형 민감도 (규칙별, 같은 체형·날씨에서 규칙 끔 → 켬)", "",
          f"**민감도 {right}/{testable} = {100 * right / max(testable, 1):.0f}%** — 측정 가능한 규칙 중 추천을 규칙 방향으로 움직인 비율 "
          f"(전체 {len(rows)}개 중 {len(rows) - testable}개는 감점 대상이 원래 추천에 없어 해당 없음). 비율 = 그 부위 추천 중 규칙 대상 속성이 나온 비율.", "",
          "| 규칙 | 대상 | 가중치 | 끔 → 켬 | 판정 |", "|---|---|---|---|---|"] + rows + ["",
          "판정 \"변화 없음\" = 대상 속성이 그 날씨·성별 후보에 거의 없거나(예: 남성 크롭 제외) 인기도·조합 신호가 더 커서 순위가 안 바뀐 경우. "
          "다리 규칙(L)은 leg 입력이 없어(보통 고정) 측정 대상에서 빠짐.", "",
          "## ③ 재현율@k", "", "FITB (한 부위 가리고 후보 전체에서 맞히기) Hit@k = 정답 1개 기준 recall@k — `runs/compat_eval.md` (상의 18.5% · 하의 44.7% · 아우터 56.1% @5, lbfgs 수렴까지 학습)."]
    out = os.path.join(HERE, "runs", "metrics_report.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
