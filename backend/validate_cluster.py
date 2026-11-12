"""
사진 체형 분석 검증 — 웹이 쓰는 경로(승민님 MediaPipe 추출기 → three_conditional 군집 → CLUSTER_BODY)를
AI Hub 의류 통합 데이터 착용 사진에 돌려, 착용자 실측으로 계산한 체형과 비교한다. (평가 프로토콜 B단계의 사진판)

  정답: 상·하체 = 실측 3분위 (data/body_thresholds.json — 남 가슴−허리 드롭, 여 가슴/엉덩이 둘레비) · 체격 = BMI (<18.5 마름 · <23 보통)
  예측: 정면 사진 1장 (이 데이터엔 측면 컷이 없음 → 웹의 '정면만' 단계와 같음)
  ① 웹과 같은 판정  : 품질 PASS 이고 NEED_SIDE 가 아닐 때만 결과 (웹은 그 외엔 재촬영·측면 요청)
  ② 전부 강제 판정 : 특징이 뽑힌 사진(PASS·REVIEW)은 모두 가장 가까운 군집으로 — 표본을 늘려 본 참고치
  ③ 측정 자체      : 사진 가슴/엉덩이 너비비(U) ↔ 실측 가슴/엉덩이 둘레비 순위상관
  사진은 zip 에서 메모리로만 읽고 저장하지 않는다.

  .\.venv\Scripts\python.exe validate_cluster.py [--n 300] [--seed 0]
출력: runs/cluster_val.csv (사람별, 이미지 없음), runs/cluster_val.md
"""
import argparse, collections, json, math, os, time, zipfile
import numpy as np, pandas as pd

import body_cluster_bridge as bcb
from validate_body import pick, img_zip

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "runs")
PRESET = "three_conditional"
GROUPS = ("상체형", "균형", "하체형")


def truth(sex, chest, waist, hip, h, w):
    th = json.load(open(os.path.join(HERE, "data", "body_thresholds.json"), encoding="utf-8"))[sex]
    v = chest - waist if sex == "M" else chest / hip
    group = "상체형" if v > th["hi"] else "균형" if v > th["lo"] else "하체형"
    bmi = w / (h / 100) ** 2 if w == w else None
    build = None if bmi is None else "마름" if bmi < 18.5 else "보통" if bmi < 23 else "통통"
    return group, build, v


def forced_cluster(sex, ratios):
    """NEED_SIDE 여부와 상관없이 정면 3변수 점수가 가장 높은 군집"""
    m = json.loads((bcb.me.ROOT / bcb.me.REGISTRY[PRESET]["models"][sex]).read_text(encoding="utf-8"))
    return int(bcb.me.gaussian(np.log([[ratios[n] for n in ("U", "W", "H")]]), m["front"])[0].argmax())


def kappa(a, b, labels):
    n = len(a)
    if not n: return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def spearman(x, y):
    if len(x) < 3: return float("nan")
    rx, ry = pd.Series(x).rank(), pd.Series(y).rank()
    return float(np.corrcoef(rx, ry)[0, 1])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=300); ap.add_argument("--seed", type=int, default=0); a = ap.parse_args()
    sel = pick(a.n, a.seed); print(f"선택 {len(sel)}명", flush=True)
    an = bcb._analyzer_class()()
    zips, members, rows, t0 = {}, {}, [], time.time()
    for i, r in enumerate(sel.itertuples(index=False)):
        p = img_zip(r.split, r.category)
        if p not in zips: zips[p] = zipfile.ZipFile(p); members[p] = {os.path.basename(x): x for x in zips[p].namelist()}
        nm = members[p].get(r.name + ".jpg")
        if nm is None: continue
        sex = "M" if r.gender == "MALE" else "F"; sx = bcb.SEX[sex]
        tg, tb, tv = truth(sex, float(r.chest), float(r.waist_size), float(r.hip_seize), float(r.body_height), float(r.weight))
        row = dict(name=r.name, sex=sex, t_group=tg, t_build=tb, t_value=tv, t_chest_hip=float(r.chest) / float(r.hip_seize))
        try:
            v = an.process_single_image(zips[p].read(nm), "FRONT")
        except Exception as e:
            rows.append({**row, "quality": "ERROR", "why": str(e)[:60]}); continue
        q = v["quality"]; row["quality"] = q["status"]; row["why"] = " / ".join(q.get("errors", []) + q.get("warnings", []))[:120]
        f = v.get("features")
        if f:
            ratios = {"U": f["chest_hip_width_ratio"], "W": f["waist_hip_width_ratio"], "H": f["hip_width_to_pose_height"]}
            row["U"] = ratios["U"]
            res = bcb.me.classify(PRESET, sx, ratios)
            row["need_side"] = res["status"] == "NEED_SIDE"
            fc = forced_cluster(sx, ratios); row["cluster_forced"] = fc
            row["p_group_forced"], row["p_build_forced"] = bcb.CLUSTER_BODY[(PRESET, sx)][fc]
            if q["status"] == "PASS" and not row["need_side"]:
                row["cluster"] = res["cluster"]; row["p_group"], row["p_build"] = bcb.CLUSTER_BODY[(PRESET, sx)][res["cluster"]]
        rows.append(row)
        if (i + 1) % 50 == 0: print(f"  {i+1}/{len(sel)}  {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows); os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, "cluster_val.csv"), index=False, encoding="utf-8-sig")
    report(df, a, time.time() - t0)


def pct(x): return f"{100 * x:.1f}%"


def report(df, a, sec):
    L = ["# 사진 체형 분석 검증 — 웹 경로(정면 1장 → three_conditional 군집 → 체형) vs 실측", "",
         f"AI Hub 의류 통합 데이터 착용 사진, 성별당 {a.n}명 (seed {a.seed}, 사람당 얇은 옷 정면 컷 1장), {sec/60:.0f}분.",
         "정답 = 실측 3분위(상·하체) · BMI(체격). 군집→체형 연결은 `body_cluster_bridge.CLUSTER_BODY` (임시). 찍기 기준 = 3분위라 상·하체 33%.", ""]
    L += ["## 1. 사진이 분석까지 가는 비율", "", "| 성별 | 사진 | PASS | REVIEW (경고) | RETAKE (재촬영) | PASS 중 측면 요청 | **웹에서 결과가 나온 비율** |", "|---|---|---|---|---|---|---|"]
    for s, g in df.groupby("sex"):
        n = len(g); qs = g.quality.value_counts()
        pas = g[g.quality == "PASS"]; ns = int(pas.need_side.fillna(False).sum()) if len(pas) else 0
        ok = int(g.p_group.notna().sum()) if "p_group" in g else 0
        L.append(f"| {'남' if s == 'M' else '여'} | {n} | {qs.get('PASS', 0)} | {qs.get('REVIEW', 0)} | {qs.get('RETAKE', 0) + qs.get('ERROR', 0)} | {ns} | **{pct(ok / n)}** ({ok}) |")
    why = collections.Counter(w for x in df.why.dropna() for w in str(x).split(" / ") if w)
    L += ["", "주요 사유: " + " · ".join(f"{k} {v}" for k, v in why.most_common(5)), ""]

    L += ["## 2. 상·하체 판정 일치율 (찍기 33%)", "", "| 성별 | 방식 | n | 일치율 | 카파 | 예측 분포 (상/균/하) |", "|---|---|---|---|---|---|"]
    for s, g in df.groupby("sex"):
        for lab, col in (("① 웹과 같은 판정", "p_group"), ("② 전부 강제 판정", "p_group_forced")):
            h = g[g[col].notna()] if col in g else g.iloc[0:0]
            if not len(h): L.append(f"| {'남' if s == 'M' else '여'} | {lab} | 0 | - | - | - |"); continue
            acc = (h[col] == h.t_group).mean(); k = kappa(list(h.t_group), list(h[col]), GROUPS)
            dist = "/".join(str(int((h[col] == x).sum())) for x in GROUPS)
            L.append(f"| {'남' if s == 'M' else '여'} | {lab} | {len(h)} | **{pct(acc)}** | {k:.2f} | {dist} |")
    L += ["", "카파: 0 = 찍기와 같음, 0.2 이하 = 거의 일치 없음, 0.4 이상 = 쓸 만함.", ""]

    L += ["## 3. 체격 판정 일치율 (BMI 기준)", "", "| 성별 | 방식 | n | 일치율 | 실측 분포 (마름/보통/통통) |", "|---|---|---|---|---|"]
    for s, g in df.groupby("sex"):
        for lab, col in (("① 웹", "p_build"), ("② 강제", "p_build_forced")):
            h = g[g[col].notna() & g.t_build.notna()] if col in g else g.iloc[0:0]
            if not len(h): continue
            dist = "/".join(str(int((h.t_build == x).sum())) for x in ("마름", "보통", "통통"))
            L.append(f"| {'남' if s == 'M' else '여'} | {lab} | {len(h)} | **{pct((h[col] == h.t_build).mean())}** | {dist} |")
    L += [""]

    L += ["## 4. 측정 자체 — 사진 가슴/엉덩이 너비비 ↔ 실측 가슴/엉덩이 둘레비", "", "| 성별 | n | 순위상관 (Spearman) |", "|---|---|---|"]
    for s, g in df.groupby("sex"):
        h = g[g.U.notna()] if "U" in g else g.iloc[0:0]
        L.append(f"| {'남' if s == 'M' else '여'} | {len(h)} | **{spearman(list(h.U), list(h.t_chest_hip)):.2f}** |")
    L += ["", "0.3 미만이면 사진 비율이 실제 몸 비율을 거의 반영하지 못한다는 뜻 (9/18 실루엣 방식은 0.05~0.32).", ""]

    L += ["## 5. 군집별 실측 비교 (② 강제 판정 기준)", "", "군집이 실제 몸 차이를 나누고 있다면 군집마다 실측 평균이 달라야 한다.", "",
          "| 성별 | 군집 | 연결된 체형 | n | 실측 지표 평균 (남 드롭 cm · 여 가슴/엉덩이) | 실측 상체형 비율 |", "|---|---|---|---|---|---|"]
    for s, g in df.groupby("sex"):
        h = g[g.cluster_forced.notna()] if "cluster_forced" in g else g.iloc[0:0]
        for c, hh in h.groupby("cluster_forced"):
            L.append(f"| {'남' if s == 'M' else '여'} | {int(c)} | {hh.p_group_forced.iloc[0]}·{hh.p_build_forced.iloc[0]} | {len(hh)} | {hh.t_value.mean():.3f} | {pct((hh.t_group == '상체형').mean())} |")
    L += ["", "⚠ 한계: 데이터 사진은 옷을 입은 착용 컷(가이드 자세 아님) · 측면 없음 · 뒷모습이 섞여 있음 → 웹 촬영 조건(가이드·팔 벌림)보다 불리할 수 있다.",
          "같은 조건에서 9/18 실루엣 방식 일치율은 32~34% (`runs/body_val.md`)."]
    open(os.path.join(OUT, "cluster_val.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
