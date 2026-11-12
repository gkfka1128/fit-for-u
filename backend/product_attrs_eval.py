"""
속성 분류기 평가 보강 (9/29) — 강의(훈련/테스트 엄격 분리 · 편향 · 모델 비교) 기준으로 product_attrs.py train 을 다시 본다.

  1) 누수 확인: train() 은 crop 을 무작위 20% 홀드아웃으로 나눈다. K-Fashion 파일명 앞부분(쇼핑몰·촬영 세트)이 같은 사진은 같은 모델·배경·조명이라
     학습과 시험에 섞이면 정확도가 부풀 수 있다 → 파일명 접두사 단위(GroupShuffleSplit)로 나눠 다시 잰다.
  2) 지표: 정확도뿐 아니라 macro-F1(클래스 불균형에 강함)·다수 클래스 기준선·클래스별 재현율.
  3) 모델 비교: 같은 CLIP 특징에 로지스틱 회귀 vs 선형 SVM (수업에서 다룬 SVM).

  .\\.venv\\Scripts\\python.exe product_attrs_eval.py        → runs/product_attrs_eval.md
"""
import collections, io, json, os, pickle, sys, time
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, recall_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.svm import LinearSVC

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data"); PD = os.path.join(DATA, "product"); OUT = os.path.join(HERE, "runs")
from kfashion_cooc import KEYS
PARTS = ("상의", "하의", "아우터")


def group_of(fname):
    """'nb799c94-nb799c94-s_7.jpg' → 'nb799c94' (같은 쇼핑몰·촬영 세트)"""
    return fname.split("-")[0].split("_")[0]


def main():
    t0 = time.time()
    rows = json.loads(io.open(os.path.join(PD, "crops.json"), encoding="utf-8").read())
    items = json.loads(io.open(os.path.join(DATA, "kfashion_items.json"), encoding="utf-8").read())
    fname = {r["id"]: r["file"] for r in pickle.load(open(os.path.join(DATA, "kfashion_labels.pkl"), "rb"))}
    L = ["# 속성 분류기 평가 보강 — 누수 · macro-F1 · SVM 비교", "",
         "같은 CLIP(ViT-B-32) 특징으로 K-Fashion crop 의 속성(카테고리·핏·기장·넥라인·소매·소재·색)을 맞힌다. 홀드아웃 20%.", "",
         "- **무작위 분할** = product_attrs.py train 과 같은 방식 (crop 단위)", "- **그룹 분할** = 사진 파일명 접두사(같은 촬영 세트)가 학습·시험에 섞이지 않게 나눔 → 누수 없는 값", "",
         "| 부위 | 속성 | 클래스 | 다수 클래스 | 로지스틱(무작위) 정확도 | 로지스틱(그룹) 정확도 | 로지스틱(그룹) macro-F1 | 선형 SVM(그룹) 정확도 | 선형 SVM(그룹) macro-F1 |", "|---|---|---|---|---|---|---|---|---|"]
    per_class = []; drops = []
    for p in PARTS:
        X = np.load(os.path.join(PD, f"kf_{p}.npy")); keep = json.load(open(os.path.join(PD, f"kf_{p}_idx.json")))
        g = np.array([group_of(fname.get(rows[p][k]["img"], str(rows[p][k]["img"]))) for k in keep])
        for a in list(KEYS[p]) + ["색상"]:
            y = np.array([(items[p][rows[p][k]["item"]]["attrs"].get(a) or "없음") if a != "색상" else (rows[p][k]["color"] or "없음") for k in keep])
            maj = collections.Counter(y).most_common(1)[0][1] / len(y)
            tr, te = train_test_split(np.arange(len(y)), test_size=0.2, random_state=0)
            lr = LogisticRegression(max_iter=2000, C=2.0).fit(X[tr], y[tr]); acc_r = accuracy_score(y[te], lr.predict(X[te]))
            tr, te = next(GroupShuffleSplit(1, test_size=0.2, random_state=0).split(X, y, g))
            lr = LogisticRegression(max_iter=2000, C=2.0).fit(X[tr], y[tr]); pr = lr.predict(X[te])
            acc_g, f1_g = accuracy_score(y[te], pr), f1_score(y[te], pr, average="macro")
            sv = LinearSVC(C=1.0, max_iter=5000).fit(X[tr], y[tr]); ps = sv.predict(X[te])
            acc_s, f1_s = accuracy_score(y[te], ps), f1_score(y[te], ps, average="macro")
            L.append(f"| {p} | {a} | {len(set(y))} | {maj:.1%} | {acc_r:.1%} | **{acc_g:.1%}** | {f1_g:.1%} | {acc_s:.1%} | {f1_s:.1%} |"); print(L[-1], f"{time.time()-t0:.0f}s", flush=True)
            drops.append(acc_r - acc_g)
            if a in ("핏", "카테고리"):
                cls = sorted(set(y[te])); rec = recall_score(y[te], pr, labels=cls, average=None, zero_division=0); cnt = collections.Counter(y[te])
                per_class.append((p, a, [(c, float(r), cnt[c]) for c, r in zip(cls, rec)]))
    L += ["", f"- 무작위 → 그룹 분할 평균 정확도 변화: {-np.mean(drops) * 100:+.2f}%p (음수면 무작위 분할이 낙관적이었다는 뜻)", "", "## 클래스별 재현율 (그룹 분할, 로지스틱) — 핏·카테고리", ""]
    for p, a, rs in per_class:
        L.append(f"- **{p} {a}**: " + ", ".join(f"{c} {r:.0%} (n={n})" for c, r, n in rs))
    L += ["", "## 읽는 법", "", "- macro-F1 은 클래스를 같은 비중으로 본다. 정확도가 다수 클래스와 비슷한데 macro-F1 이 낮으면 소수 클래스를 못 맞히는 것.",
          "- 학습 데이터는 사람이 입은 K-Fashion crop, 적용 대상은 흰 배경 제품 컷 → 도메인 차이는 이 표에 안 들어간다 (제품 컷엔 정답 라벨이 없음).",
          "- 이 평가로 서비스 성능이 바뀌지는 않는다 — 문서에 적는 정확도의 신뢰도를 높이는 검증."]
    io.open(os.path.join(OUT, "product_attrs_eval.md"), "w", encoding="utf-8").write("\n".join(L) + "\n"); print("saved runs/product_attrs_eval.md")


if __name__ == "__main__":
    main()
