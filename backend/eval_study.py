"""
평가 참여 결과 분석 (평가 프로토콜 §5) — 웹 "평가 참여" 화면이 data/members.db 에 쌓은 기록 → runs/study_eval.md

  B. 형태 판정: 본인 1문항 답 · 사진 판정  vs  줄자 실측 3분위 (data/body_thresholds.json — 남 가슴−허리 드롭, 여 가슴/엉덩이 둘레비)
     일치율 · 카파 · 인접 일치율(한 칸 차이까지) · 혼동표.  목표: 1문항 일치율 ≥ 60% (찍기 33%)
     사진 너비비 U ↔ 실측 가슴/엉덩이 둘레비 순위상관 (AI Hub 착용 사진에서는 0.04~0.08)
  D. 체형 규칙 A/B (블라인드) — eval_ab.summarize 와 같은 계산 · 설문 평균 (입겠다 ≥ 4.0 · 신발 ≥ 3.5 · 이해됐다 ≥ 4.0 · 기분 나빴다 0건)

  .\\.venv\\Scripts\\python.exe eval_study.py [--db data/members.db]
"""
import argparse, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import eval_ab, members

GROUPS = ("상체형", "균형", "하체형")
ANSWER = {"상체": "상체형", "균형": "균형", "하체": "하체형"}


def truth(sex, tape):
    """실측 3분위 유형 (validate_cluster.truth 와 같은 기준). 필요한 둘레가 없으면 None"""
    th = json.load(open(os.path.join(HERE, "data", "body_thresholds.json"), encoding="utf-8"))[sex]
    t = tape or {}
    if sex == "M":
        if not (t.get("chest") and t.get("waist")): return None
        v = t["chest"] - t["waist"]
    else:
        if not (t.get("chest") and t.get("hip")): return None
        v = t["chest"] / t["hip"]
    return "상체형" if v > th["hi"] else "균형" if v > th["lo"] else "하체형"


def agreement(pairs):
    """[(예측, 정답)] → 일치율 · 카파 · 인접 일치율 · 혼동표"""
    n = len(pairs)
    if not n: return None
    acc = sum(p == t for p, t in pairs) / n
    pe = sum((sum(p == g for p, _ in pairs) / n) * (sum(t == g for _, t in pairs) / n) for g in GROUPS)
    kappa = (acc - pe) / (1 - pe) if pe < 1 else 0.0
    adj = sum(abs(GROUPS.index(p) - GROUPS.index(t)) <= 1 for p, t in pairs) / n
    cm = collections.Counter(pairs)
    return {"n": n, "acc": acc, "kappa": kappa, "adj": adj, "cm": cm}


def spearman(xs, ys):
    if len(xs) < 5: return None
    from scipy.stats import spearmanr
    return spearmanr(xs, ys).statistic


def ab_rows(people):
    rows = []
    for p in people:
        for a in p["ab"]:
            base = {"sid": p["pid"], "body": a["meta"]["body"]}
            if a["identical"]: rows.append({**base, "identical": True}); continue
            if a["choice"] is None: continue                                  # 보여 줬지만 답하기 전에 그만둔 회차
            rows.append({**base, "identical": False,
                         "prefers_rules": None if a["choice"] == "same" else (a["choice"] == "A") == a["a_is_rules"],
                         "score_rules": a["score_a"] if a["a_is_rules"] else a["score_b"],
                         "score_plain": a["score_b"] if a["a_is_rules"] else a["score_a"]})
    return rows


def pct(x): return "—" if x is None else f"{100 * x:.1f}%"


def cm_table(cm, label):
    L = [f"| {label} \\ 실측 | " + " | ".join(GROUPS) + " |", "|---|" + "---|" * len(GROUPS)]
    for p in GROUPS: L.append(f"| {p} | " + " | ".join(str(cm.get((p, t), 0)) for t in GROUPS) + " |")
    return L


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default=members.DB_PATH); ap.add_argument("--out", default=os.path.join(HERE, "runs", "study_eval.md"))
    a = ap.parse_args()
    people = members.Members(a.db).study_dump()
    sx = collections.Counter(p["profile"]["sex"] for p in people)
    L = ["# 평가 참여 결과 — 형태 1문항·사진 vs 줄자 실측, 체형 규칙 A/B, 만족도", "",
         f"참가자 **{len(people)}명** (남 {sx.get('M', 0)} · 여 {sx.get('F', 0)}) · 실측 입력 {sum(bool(truth(p['profile']['sex'], p['tape'])) for p in people)}명 · "
         f"사진 시도 {sum(bool(p['photo']) for p in people)}명 (분석까지 간 사람 {sum((p['photo'] or {}).get('status') == 'ok' for p in people)}명)", ""]
    if len(people) < 30: L += [f"⚠ 목표 30명 중 {len(people)}명 — 숫자는 참고용. 30명이 모이면 다시 돌린다.", ""]

    # B. 형태 판정
    ans, photo, xs, ys, dunno = [], [], [], [], 0
    for p in people:
        t = truth(p["profile"]["sex"], p["tape"])
        if not t: continue
        g = ANSWER.get(p["profile"]["answer"])
        if g: ans.append((g, t))
        else: dunno += 1
        ph = p["photo"] or {}
        if ph.get("status") == "ok" and ph.get("group"): photo.append((ph["group"], t))
        if ph.get("ratios", {}).get("U") and p["tape"].get("chest") and p["tape"].get("hip"):
            xs.append(ph["ratios"]["U"]); ys.append(p["tape"]["chest"] / p["tape"]["hip"])
    L += ["## B. 상·하체 형태 판정 vs 줄자 실측 3분위 (찍기 33%)", "",
          "| 방식 | n | 일치율 | 카파 | 인접 일치율 | 목표 |", "|---|---|---|---|---|---|"]
    for name, pairs, goal in (("본인 1문항", ans, "≥ 60%"), ("사진 판정", photo, "—")):
        r = agreement(pairs)
        kappa = f"{r['kappa']:.2f}" if r else "—"
        L.append(f"| {name} | {r['n'] if r else 0} | **{pct(r and r['acc'])}** | {kappa} | {pct(r and r['adj'])} | {goal} |")
    L += ["", f"1문항에 '잘 모르겠어요' {dunno}명 (일치율에서 제외).", ""]
    for name, pairs in (("1문항", ans), ("사진", photo)):
        r = agreement(pairs)
        if r: L += [f"**{name} 혼동표**", ""] + cm_table(r["cm"], name) + [""]
    rho = spearman(xs, ys)
    L += [f"사진 가슴/엉덩이 너비비 U ↔ 실측 가슴/엉덩이 둘레비 순위상관: **{'—' if rho is None else f'{rho:.2f}'}** (n={len(xs)}, 5명 미만이면 계산 안 함 · AI Hub 착용 사진 0.04~0.08)", ""]

    # D. A/B
    s = eval_ab.summarize(ab_rows(people))
    L += ["## D-1. 체형 규칙 켬 vs 끔 (블라인드 A/B, 순서 무작위)", "",
          f"회차 {s['n_rows']} (두 코디가 같아 건너뜀 {s['n_identical']}, 물어본 회차 {s['n_asked']}, 비슷함 {s['n_tie']})", "",
          "| 지표 | 값 | 검정 | 목표 |", "|---|---|---|---|",
          f"| 규칙 쪽을 고른 비율 (비슷함 제외) | **{pct(s['rate'])}** ({s['k_rules']}/{s['n_dec']}) | 이항검정 p = {eval_ab.pv(s['p'])} | ≥ 60% |",
          f"| 참가자 다수결로 규칙 쪽 | {s['sid_win']}/{s['sid_n']}명 | 이항검정 p = {eval_ab.pv(s['p_sid'])} | — |",
          f"| 만족도 차이 (규칙 − 대조, 1~5점) | **{eval_ab.fmt(s['score_diff'])}** | 윌콕슨 p = {eval_ab.pv(s['p_w']) if s['p_w'] is not None else '— (차이 있는 응답 6개 미만)'} | > 0 |", ""]

    # D. 설문
    sv = [p for p in people if p["survey"]]
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    f2 = lambda x: "—" if x is None else f"{x:.2f}"
    L += ["## D-2. 만족도 설문 (1~5점)", "", "| 문항 | 전체 | 남 | 여 | 목표 |", "|---|---|---|---|---|"]
    for k, q, goal in (("wear", "오늘 이 추천을 입겠다", "≥ 4.0"), ("shoes", "추천 신발을 신겠다", "≥ 3.5"), ("understand", "왜 이 추천인지 이해됐다", "≥ 4.0")):
        by = lambda sx: [p["survey"][k] for p in sv if sx is None or p["profile"]["sex"] == sx]
        L.append(f"| {q} | **{f2(mean(by(None)))}** (n={len(by(None))}) | {f2(mean(by('M')))} | {f2(mean(by('F')))} | {goal} |")
    neg = sum(p["survey"]["negative"] for p in sv)
    L += [f"| 결과를 보고 기분이 나빴다 | **{neg}건** / {len(sv)} | | | 0건 |", ""]
    comments = [p["survey"]["comment"] for p in sv if p["survey"].get("comment")]
    if comments: L += ["**자유 의견**", ""] + [f"- {c}" for c in comments] + [""]

    L += ["---", "정답 기준·검정 방법: `md파일/평가_프로토콜.md` §2-B·§2-D·§5. 기록은 익명 참가자 번호로만 남고 사진은 저장하지 않는다 (분석 숫자만)."]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"→ {a.out} (참가자 {len(people)}명)")


if __name__ == "__main__":
    main()
