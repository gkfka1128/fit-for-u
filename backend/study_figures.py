"""판넬용 그래프 — 평가 참여 결과 (eval_study.py 와 같은 계산) → runs/fig_study_*.png

  ① fig_study_body.png    상·하체 판정 일치율: 찍기 33% · AI Hub 사진 판정(runs/cluster_val.md) · 테스트 사진 판정 · 테스트 본인 1문항
  ② fig_study_ab.png      체형 규칙 켬 vs 끔 블라인드 A/B: 규칙 쪽 / 비슷함 / 대조 쪽 비율 + 이항검정
  ③ fig_study_survey.png  만족도 설문 평균 vs 목표

  .\\.venv\\Scripts\\python.exe study_figures.py [--db data/members.db] [--label "리허설 · 가짜 데이터"]
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import eval_ab, eval_study, members

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 15,
                     "axes.spines.top": False, "axes.spines.right": False})
INK, MUTED, MAIN, SUB = "#222222", "#9a9a9a", "#2f6fdb", "#b9c9e6"
# AI Hub 착용 사진 웹 경로 판정 일치율 (runs/cluster_val.md ①: 여 240명 41.7% · 남 174명 34.5%)
AIHUB_PHOTO = (240 * 0.417 + 174 * 0.345) / (240 + 174), 414


def stamp(fig, label):
    if label: fig.text(0.99, 0.99, label, ha="right", va="top", fontsize=12, color="#d0342c")


def fig_body(people, out, label):
    ans, photo = [], []
    for p in people:
        t = eval_study.truth(p["profile"]["sex"], p["tape"])
        if not t: continue
        g = eval_study.ANSWER.get(p["profile"]["answer"])
        if g: ans.append((g, t))
        ph = p["photo"] or {}
        if ph.get("status") == "ok" and ph.get("group"): photo.append((ph["group"], t))
    bars = [("AI Hub 사진\n판정", *AIHUB_PHOTO, SUB)]
    for name, pairs, c in (("테스트\n사진 판정", photo, SUB), ("테스트\n본인 1문항", ans, MAIN)):
        r = eval_study.agreement(pairs)
        bars.append((name, r["acc"] if r else 0, r["n"] if r else 0, c))
    fig, ax = plt.subplots(figsize=(8, 5.2))
    xs = range(len(bars))
    ax.bar(xs, [100 * b[1] for b in bars], color=[b[3] for b in bars], width=0.6)
    for x, (_, v, n, _) in zip(xs, bars):
        ax.text(x, 100 * v + 2, f"{100 * v:.1f}%\n(n={n})" if n else "자료 없음", ha="center", va="bottom", color=INK)
    ax.axhline(100 / 3, ls="--", color=MUTED); ax.text(-0.45, 100 / 3 - 1, "찍기 33%", color=MUTED, ha="left", va="top")
    ax.axhline(60, ls=":", color=MAIN); ax.text(-0.45, 61, "목표 60%", color=MAIN, ha="left", va="bottom")
    ax.set_xticks(list(xs), [b[0] for b in bars]); ax.set_ylim(0, 105); ax.set_ylabel("줄자 실측과 일치율 (%)")
    ax.set_title("상·하체 형태 판정 — 줄자 실측 3분위 기준", loc="left", color=INK)
    stamp(fig, label); fig.tight_layout(); fig.savefig(out, dpi=300); plt.close(fig)


def fig_ab(people, out, label):
    s = eval_ab.summarize(eval_study.ab_rows(people))
    n = s["n_asked"]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    if n:
        parts = [("체형 규칙 켠 쪽", s["k_rules"], MAIN), ("비슷함", s["n_tie"], "#dddddd"), ("규칙 끈 쪽", s["n_dec"] - s["k_rules"], MUTED)]
        left = 0
        for name, k, c in parts:
            w = 100 * k / n
            ax.barh(0, w, left=left, color=c, height=0.5)
            if w >= 8: ax.text(left + w / 2, 0, f"{name}\n{w:.0f}%", ha="center", va="center", color="white" if c != "#dddddd" else INK)
            left += w
        ax.axvline(50, ls="--", color=INK, lw=1)
    ax.set_xlim(0, 100); ax.set_yticks([]); ax.set_xlabel("물어본 회차 중 비율 (%)")
    ax.set_title("“내 체형에 더 어울리는 코디는?” — 블라인드 A/B", loc="left", color=INK)
    note = (f"참가자 {s['n_sid']}명 · 물어본 회차 {n} (두 코디가 같아 건너뜀 {s['n_identical']})\n"
            f"규칙 쪽 {eval_study.pct(s['rate'])}, 이항검정 p = {eval_ab.pv(s['p'])}  ·  만족도 차 {eval_ab.fmt(s['score_diff'])}점")
    fig.text(0.02, 0.02, note, fontsize=12, color=INK)
    stamp(fig, label); fig.tight_layout(rect=(0, 0.13, 1, 0.95)); fig.savefig(out, dpi=300); plt.close(fig)


def fig_survey(people, out, label):
    sv = [p["survey"] for p in people if p["survey"]]
    items = [("오늘 이 추천을 입겠다", "wear", 4.0), ("추천 신발을 신겠다", "shoes", 3.5), ("왜 이 추천인지 이해됐다", "understand", 4.0)]
    means = [sum(x[k] for x in sv) / len(sv) if sv else 0 for _, k, _ in items]
    fig, ax = plt.subplots(figsize=(8, 4))
    ys = range(len(items))[::-1]
    ax.barh(list(ys), means, color=[MAIN if m >= g else SUB for m, (_, _, g) in zip(means, items)], height=0.55)
    for y, m, (_, _, g) in zip(ys, means, items):
        ax.text(m - 0.06, y, f"{m:.2f}", va="center", ha="right", color="white")
        ax.plot([g, g], [y - 0.35, y + 0.35], color=INK, lw=2); ax.text(g + 0.06, y, f"목표 {g}", va="center", fontsize=11, color=MUTED)
    ax.set_yticks(list(ys), [q for q, _, _ in items]); ax.set_xlim(1, 5.4); ax.set_xlabel("평균 (1~5점)")
    neg = sum(x["negative"] for x in sv)
    ax.set_title(f"만족도 설문 (n={len(sv)}) · 기분 나빴다 {neg}건", loc="left", color=INK, pad=14)
    stamp(fig, label); fig.tight_layout(); fig.savefig(out, dpi=300); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default=members.DB_PATH)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "runs")); ap.add_argument("--label", default="")
    a = ap.parse_args()
    people = members.Members(a.db).study_dump()
    label = a.label or (f"참가자 {len(people)}명 · 목표 30명 전 (참고용)" if len(people) < 30 else "")
    os.makedirs(a.out_dir, exist_ok=True)
    for name, fn in (("body", fig_body), ("ab", fig_ab), ("survey", fig_survey)):
        out = os.path.join(a.out_dir, f"fig_study_{name}.png"); fn(people, out, label); print("→", out)


if __name__ == "__main__":
    main()
