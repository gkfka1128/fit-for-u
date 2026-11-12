"""
조합 호환성 학습 모델 — "이 상의·아우터면 어떤 하의?" 를 다항 로지스틱 회귀로 학습한다 (부위별 3개).
  입력  = 주어진 나머지 부위 속성 one-hot (없는 부위는 '없음')
  출력  = 가린 부위의 후보 아이템 id (kfashion_items.json 의 순번)
  학습  = K-Fashion Training 코디 / 평가 = Validation FITB (한 부위 가리고 후보 중 순위, Hit@1/5)
  손실  = 교차 엔트로피(다항 로지스틱 회귀, L2 C=1), 최적화 lbfgs
  멈춤  = 10/20: 이전엔 반복 상한 200 에서 상의·하의가 수렴 전에 끊겼다 → STEP 회마다 손실을 재고,
          Training 의 10% 를 dev 로 떼어 dev 손실이 PATIENCE 번 연속 TOL 보다 덜 줄면 멈춤 (가장 좋았던 가중치 사용).
          Validation 은 멈춤 판단에 쓰지 않고 최종 평가에만 쓴다.
  models/compat_{상의,하의,아우터}.joblib , runs/compat_eval.md , runs/compat_curve.md·png (학습 곡선)

  .\.venv\Scripts\python.exe train_compat.py        (수십 분)
"""
import io, json, os, sys, time
import numpy as np, joblib
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from kfashion_cooc import ITEM_ATTRS, first, item_key, load_labels

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data"); MODELS = os.path.join(HERE, "models"); RUNS = os.path.join(HERE, "runs")
TARGETS = ("상의", "하의", "아우터")
GIVEN = {"상의": ("하의", "아우터"), "하의": ("상의", "아우터"), "아우터": ("상의", "하의")}      # 필수로 있어야 하는 첫 부위, 선택인 둘째 (아우터는 둘 다 필수)
REQUIRED = {"상의": ("하의",), "하의": ("상의",), "아우터": ("상의", "하의")}
C = 1.0
STEP, MAX_ITER, PATIENCE, TOL, DEV_FRAC = 25, 2000, 3, 1e-4, 0.1


def feature_names(part):
    return [f"{p}.{a}" for p in GIVEN[part] for a in ITEM_ATTRS[p]]


def featurize(part, given):
    """given = {부위: 속성 튜플|None} → 문자열 특징 목록 (없는 부위는 '없음')"""
    out = []
    for p in GIVEN[part]:
        key = given.get(p)
        for a, v in zip(ITEM_ATTRS[p], key if key else [None] * len(ITEM_ATTRS[p])):
            out.append(f"{p}.{a}={v if v else ('없음' if key is None else '?')}")
    return out


def samples(recs, part, index):
    """(특징 목록들, 정답 item id 들)"""
    X, y = [], []
    for r in recs:
        P = r["parts"]
        if part not in P or any(q not in P for q in REQUIRED[part]): continue
        tk = item_key(part, P[part][0])
        if "카테고리" not in P[part][0] or tk not in index[part]: continue
        given = {q: (item_key(q, P[q][0]) if q in P and "카테고리" in P[q][0] else None) for q in GIVEN[part]}
        X.append(featurize(part, given)); y.append(index[part][tk])
    return X, np.array(y)


class Vocab:
    def __init__(self, rows):
        self.idx = {}
        for r in rows:
            for f in r: self.idx.setdefault(f, len(self.idx))

    def transform(self, rows):
        ri, ci = [], []
        for i, r in enumerate(rows):
            for f in r:
                j = self.idx.get(f)
                if j is not None: ri.append(i); ci.append(j)
        return sparse.csr_matrix((np.ones(len(ri), dtype=np.float32), (ri, ci)), shape=(len(rows), len(self.idx)))


def hit(scores, y, k):
    top = np.argsort(-scores, axis=1)[:, :k]
    return float((top == y[:, None]).any(1).mean())


def nll(clf, X, y, n_items):
    """평균 교차 엔트로피 (학습에 없던 클래스는 확률 1e-9)"""
    lp = clf.predict_log_proba(X); col = {c: j for j, c in enumerate(clf.classes_)}
    return float(-np.mean([lp[i, col[t]] if t in col else np.log(1e-9) for i, t in enumerate(y)]))


def fit_curve(A, y, D, yd, n_items, log):
    """STEP 회씩 이어 학습하며 (반복, 훈련 손실, dev 손실, dev Hit@5) 기록 → 조기 종료. (clf, curve, 수렴여부)"""
    import copy, warnings
    from sklearn.exceptions import ConvergenceWarning
    clf = LogisticRegression(C=C, max_iter=STEP, solver="lbfgs", warm_start=True)
    curve, best, best_clf, bad, it, converged = [], None, None, 0, 0, False
    sub = np.random.default_rng(1).choice(A.shape[0], min(30000, A.shape[0]), replace=False)   # 훈련 손실은 표본으로 (메모리)
    while it < MAX_ITER:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning); clf.fit(A, y)
        n = int(clf.n_iter_[0]); it += n
        P = np.full((D.shape[0], n_items), -1e9, dtype=np.float32); P[:, clf.classes_] = clf.predict_log_proba(D)
        row = (it, nll(clf, A[sub], y[sub], n_items), nll(clf, D, yd, n_items), hit(P, yd, 5)); curve.append(row)
        log(f"  iter {row[0]:5d}  train {row[1]:.4f}  dev {row[2]:.4f}  dev Hit@5 {row[3]:.1%}")
        if best is None or row[2] < best - TOL: best, best_clf, bad = row[2], copy.deepcopy(clf), 0
        else: bad += 1
        if n < STEP: converged = True; break          # lbfgs 가 스스로 수렴
        if bad >= PATIENCE: break                      # dev 손실이 더 안 줄어듦 → 조기 종료
    return best_clf, curve, converged


def plot_curves(curves, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, len(curves), figsize=(5 * len(curves), 3.6))
    for ax, (part, c) in zip(axes, curves.items()):
        it = [r[0] for r in c]
        ax.plot(it, [r[1] for r in c], label="훈련 손실", color="#9a968c"); ax.plot(it, [r[2] for r in c], label="dev 손실", color="#1c1c1a")
        ax.set_title(part); ax.set_xlabel("반복 (lbfgs)"); ax.set_ylabel("교차 엔트로피"); ax.grid(alpha=.3)
        ax.axvline(200, color="#c0504d", ls="--", lw=1, label="이전 상한 200")
    axes[0].legend(fontsize=8); fig.tight_layout(); fig.savefig(path, dpi=150)


def main():
    t0 = time.time(); os.makedirs(MODELS, exist_ok=True); os.makedirs(RUNS, exist_ok=True)
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    index = {p: {tuple(it["attrs"].get(a) for a in ITEM_ATTRS[p]): i for i, it in enumerate(items[p])} for p in TARGETS}
    recs = load_labels(); tr = [r for r in recs if r["split"] == "train"]; va = [r for r in recs if r["split"] == "valid"]
    lines = ["# 조합 호환성 모델 — FITB 평가 (K-Fashion Validation)", "",
             "한 부위를 가리고 후보 전체 중 정답 순위. 무작위 = k/후보수, 인기도 = 학습 빈도순.", "",
             "| 가린 부위 | 후보 | 학습 n | 평가 n | 무작위 Hit@5 | 인기도 Hit@1 | 인기도 Hit@5 | 모델 Hit@1 | 모델 Hit@5 |", "|---|---|---|---|---|---|---|---|---|"]
    lines[-2] = lines[-2].replace("| 모델 Hit@5 |", "| 모델 Hit@5 | 반복 | 멈춘 이유 |"); lines[-1] += "---|---|"
    curves, log = {}, (lambda m: print(m, flush=True))
    rng = np.random.default_rng(0)
    for part in TARGETS:
        Xtr, ytr = samples(tr, part, index); Xva, yva = samples(va, part, index)
        dev = rng.random(len(ytr)) < DEV_FRAC                     # 멈춤 판단용 (Validation 과 별개)
        Xfit = [x for x, d in zip(Xtr, dev) if not d]; Xdev = [x for x, d in zip(Xtr, dev) if d]
        vocab = Vocab(Xfit); A, B, D = vocab.transform(Xfit), vocab.transform(Xva), vocab.transform(Xdev)
        log(f"[{part}] 학습 {A.shape[0]:,} · dev {D.shape[0]:,} · 특징 {A.shape[1]} · 후보 {len(items[part])}")
        clf, curve, converged = fit_curve(A, ytr[~dev], D, ytr[dev], len(items[part]), log); curves[part] = curve
        stop = "lbfgs 수렴" if converged else (f"dev 손실 정체 (조기 종료)" if curve[-1][0] < MAX_ITER else f"상한 {MAX_ITER}")
        ytr = ytr[~dev]; best_it = min(curve, key=lambda r: r[2])[0]
        P = np.full((B.shape[0], len(items[part])), -1e9, dtype=np.float32); P[:, clf.classes_] = clf.predict_log_proba(B)
        pop = np.bincount(ytr, minlength=len(items[part])).astype(np.float32)
        Pp = np.tile(pop, (len(yva), 1))
        n_c = len(items[part])
        lines.append(f"| {part} | {n_c} | {len(ytr):,} | {len(yva):,} | {5 / n_c:.1%} | {hit(Pp, yva, 1):.1%} | {hit(Pp, yva, 5):.1%} | {hit(P, yva, 1):.1%} | **{hit(P, yva, 5):.1%}** | {best_it} | {stop} |")
        print(lines[-1], f"{time.time()-t0:.0f}s", flush=True)
        joblib.dump({"vocab": vocab.idx, "clf": clf, "classes": clf.classes_, "n_items": n_c, "given": GIVEN[part]}, os.path.join(MODELS, f"compat_{part}.joblib"))
    io.open(os.path.join(RUNS, "compat_eval.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    cl = ["# 조합 모델 학습 곡선 (train_compat.py)", "", f"{STEP}회마다 측정 · dev = Training 의 {DEV_FRAC:.0%} (멈춤 판단용) · 교차 엔트로피 손실", ""]
    for part, c in curves.items():
        cl += [f"## {part}", "", "| 반복 | 훈련 손실 | dev 손실 | dev Hit@5 |", "|---|---|---|---|"] + [f"| {r[0]} | {r[1]:.4f} | {r[2]:.4f} | {r[3]:.1%} |" for r in c] + [""]
    io.open(os.path.join(RUNS, "compat_curve.md"), "w", encoding="utf-8").write("\n".join(cl))
    plot_curves(curves, os.path.join(RUNS, "compat_curve.png"))


if __name__ == "__main__":
    main()
