"""
만족도 A/B 평가 분석 (평가 프로토콜 D단계) — 데모 "만족도 평가 (A/B)" 화면이 쌓은 data/eval/ab_responses.jsonl → runs/ab_eval.md

  질문: 체형 규칙을 켠 추천이 끈 추천보다 "내 체형에 더 어울린다"고 고르는 비율이 50%보다 높은가?
  · 선택: 규칙 쪽 / 대조 쪽 / 비슷함 → 비슷함 제외 후 양측 이항검정 (H0: p = 0.5)
  · 점수: 규칙 쪽 만족도 − 대조 쪽 만족도 (1~5) → 평균 차이 + 윌콕슨 부호순위 검정
  · 응답자 내 반복이 있으므로 응답자 단위 다수결도 같이 본다 (응답자 수가 실제 표본 크기)
  · identical = 두 추천이 같아 묻지 않은 회차 (체형 규칙이 결과를 안 바꾼 비율)

  .\\.venv\\Scripts\\python.exe eval_ab.py [--log data/eval/ab_responses.jsonl]
"""
import argparse, collections, json, os

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    rows = []
    if not os.path.exists(path): return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except json.JSONDecodeError: pass
    return rows


def binom_p(k, n):
    if n == 0: return None
    from scipy.stats import binomtest
    return binomtest(k, n, 0.5).pvalue


def wilcoxon_p(diffs):
    d = [x for x in diffs if x != 0]
    if len(d) < 6: return None
    from scipy.stats import wilcoxon
    return wilcoxon(d).pvalue


def summarize(rows):
    asked = [r for r in rows if not r.get("identical")]
    dec = [r for r in asked if r.get("prefers_rules") is not None]
    k = sum(r["prefers_rules"] for r in dec)
    diffs = [r["score_rules"] - r["score_plain"] for r in asked if "score_rules" in r]
    by_sid = collections.defaultdict(list)
    for r in dec: by_sid[r["sid"]].append(r["prefers_rules"])
    sid_votes = [sum(v) / len(v) for v in by_sid.values()]
    sid_win = sum(v > 0.5 for v in sid_votes); sid_n = sum(v != 0.5 for v in sid_votes)
    return {"n_rows": len(rows), "n_identical": len(rows) - len(asked), "n_asked": len(asked), "n_tie": len(asked) - len(dec),
            "k_rules": k, "n_dec": len(dec), "rate": k / len(dec) if dec else None, "p": binom_p(k, len(dec)),
            "score_diff": sum(diffs) / len(diffs) if diffs else None, "p_w": wilcoxon_p(diffs),
            "n_sid": len({r["sid"] for r in rows}), "sid_win": sid_win, "sid_n": sid_n, "p_sid": binom_p(sid_win, sid_n)}


def fmt(x, pct=False, nd=2):
    if x is None: return "—"
    return f"{100 * x:.1f}%" if pct else f"{x:+.{nd}f}" if isinstance(x, float) else str(x)


def pv(p):
    return "—" if p is None else "< 0.001" if p < 0.001 else f"{p:.3f}"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--log", default=os.path.join(HERE, "data", "eval", "ab_responses.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "ab_eval.md"))
    a = ap.parse_args()
    rows = load(a.log)
    s = summarize(rows)
    L = ["# 만족도 A/B 평가 — 체형 규칙 켬 vs 끔 (블라인드, 순서 무작위)", "",
         f"응답자 {s['n_sid']}명 · 회차 {s['n_rows']} (두 추천이 같아 건너뜀 {s['n_identical']}, 물어본 회차 {s['n_asked']}, 비슷함 {s['n_tie']})", "",
         "| 지표 | 값 | 검정 |", "|---|---|---|",
         f"| 규칙 쪽을 고른 비율 (비슷함 제외) | **{fmt(s['rate'], True)}** ({s['k_rules']}/{s['n_dec']}) | 이항검정 p = {pv(s['p'])} |",
         f"| 응답자 다수결로 규칙 쪽 | {s['sid_win']}/{s['sid_n']}명 | 이항검정 p = {pv(s['p_sid'])} |",
         f"| 만족도 차이 (규칙 − 대조, 1~5점) | **{fmt(s['score_diff'])}** | 윌콕슨 p = {pv(s['p_w']) if s['p_w'] is not None else '— (차이 있는 응답 6개 미만)'} |",
         f"| 체형 규칙이 결과를 바꾼 회차 | {fmt((s['n_asked'] / s['n_rows']) if s['n_rows'] else None, True)} | — |", ""]
    groups = collections.defaultdict(list)
    for r in rows: groups[f"{r['body'].get('sex')}·{r['body'].get('group')}·{r['body'].get('build')}"].append(r)
    if groups:
        L += ["## 체형별", "", "| 체형 | 회차 | 규칙 쪽 비율 | 만족도 차이 |", "|---|---|---|---|"]
        for g, rs in sorted(groups.items()):
            t = summarize(rs); L.append(f"| {g} | {t['n_rows']} | {fmt(t['rate'], True)} ({t['k_rules']}/{t['n_dec']}) | {fmt(t['score_diff'])} |")
        L.append("")
    L += ["해석: 규칙 쪽 비율이 50% 보다 유의하게 높으면(p < 0.05) \"체형 규칙이 체감 만족을 올린다\". 회차는 같은 응답자가 여러 번 답하므로 "
          "독립이 아니다 — 결론은 응답자 다수결 행을 우선한다. 목표: 응답자 30명 × 5회차 이상."]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
