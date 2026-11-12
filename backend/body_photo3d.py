"""
사진 1장 → 3D 인체 메시(HMR2.0, SMPL) → 가슴·허리·엉덩이 둘레 비율  (실루엣 방식의 대안, 9/20)

  HMR2.0 (4D-Humans, Goel et al. ICCV 2023) 이 사진에서 SMPL 형태 파라미터(betas)를 회귀한다.
  betas 로 T-포즈 메시를 만들고 수평 단면 둘레를 재면 옷·자세·카메라와 무관한 '형태'가 나온다 → 드롭·가슴/엉덩이 비율 → 3대 체형.
  절대 cm 는 메시 키를 사용자 키로 맞춰 환산 (SMPL 형태 자체는 키 정보가 약하므로 비율만 믿는다).

  필요 파일
    - HMR2 가중치: 자동 다운로드 (~/.cache/4DHumans, 공개)
    - SMPL 중립 모델: 라이선스 등록 후 직접 다운로드 → code/data/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl
      (https://smplify.is.tue.mpg.de/ → Downloads → SMPLIFY_CODE_V2.ZIP 안의 models/ 폴더, 또는 https://smpl.is.tue.mpg.de/)

  사용
    from body_photo3d import Photo3D
    p3 = Photo3D(); r = p3(img_path, height_cm=173)  → {"chest","waist","hip","shoulder"(cm), "drop","chest_hip", "betas", "ok"}
    .\.venv\Scripts\python.exe body_photo3d.py samples\me.jpg --height 173           # 단독 실행
    .\.venv\Scripts\python.exe body_photo3d.py --validate 150                        # 의류 통합 데이터 실측으로 채점 → runs/photo3d_val.md
"""
import argparse, io, json, os, sys, tempfile, time, zipfile
os.environ.setdefault("PYOPENGL_PLATFORM", "nt")                       # pyrender 가 EGL 을 찾지 않게 (Windows)
os.environ.setdefault("HOME", os.path.expanduser("~"))                 # hmr2 캐시 경로 (~/.cache/4DHumans)
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "runs")
SMPL_LOCAL = os.path.join(DATA, "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl")

def _ensure_smpl():
    """SMPL pkl 을 hmr2 가 기대하는 캐시 위치로 복사 (py2 pickle → py3 변환 포함)"""
    from hmr2.configs import CACHE_DIR_4DHUMANS
    from hmr2.models import convert_pkl
    dst = os.path.join(CACHE_DIR_4DHUMANS, "data", "smpl", "SMPL_NEUTRAL.pkl")
    if os.path.exists(dst): return dst
    if not os.path.exists(SMPL_LOCAL):
        raise FileNotFoundError(f"SMPL 모델이 없습니다. https://smplify.is.tue.mpg.de/ 에서 등록·다운로드 후 {SMPL_LOCAL} 에 두세요")
    os.makedirs(os.path.dirname(dst), exist_ok=True); convert_pkl(SMPL_LOCAL, dst); return dst

def slice_perimeter(mesh, y):
    """높이 y 의 수평 단면 둘레 (m). 여러 고리가 나오면(팔·몸통) 가장 긴 것 = 몸통"""
    sec = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    if sec is None: return 0.0
    try:
        planar, _ = sec.to_planar()
        return float(max((p.length for p in planar.polygons_closed if p is not None), default=0.0))
    except Exception:
        return 0.0

class Photo3D:
    def __init__(self, device=None):
        import torch
        from hmr2.models import load_hmr2, DEFAULT_CHECKPOINT, download_models
        import hmr2.models.hmr2 as _h
        _h.MeshRenderer = lambda *a, **k: None                                 # 렌더러(pyrender/EGL)는 안 쓴다 — Windows 에서 오프스크린 GL 없이 동작
        download_models(); _ensure_smpl()
        self.torch = torch
        self.dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model, self.cfg = load_hmr2(DEFAULT_CHECKPOINT); self.model = self.model.to(self.dev).eval()
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        from body_measure import POSE_MODEL
        self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=open(POSE_MODEL, "rb").read()), num_poses=1))
        self.mp = mp

    def bbox(self, rgb):
        """MediaPipe 포즈로 사람 상자 (detectron2 대신)"""
        H, W = rgb.shape[:2]
        res = self.pose.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb))
        if not res.pose_landmarks: return None
        xs = [l.x * W for l in res.pose_landmarks[0]]; ys = [l.y * H for l in res.pose_landmarks[0]]
        x0, x1, y0, y1 = max(0, min(xs)), min(W, max(xs)), max(0, min(ys)), min(H, max(ys))
        m = 0.12 * max(x1 - x0, y1 - y0)
        return [max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)]

    def __call__(self, img_path, height_cm=None):
        import cv2, trimesh
        from hmr2.datasets.vitdet_dataset import ViTDetDataset
        torch = self.torch
        bgr = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None: return {"ok": False, "err": "이미지 못 읽음"}
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        box = self.bbox(rgb)
        if box is None: return {"ok": False, "err": "사람 검출 실패"}
        ds = ViTDetDataset(self.cfg, bgr, np.array([box], dtype=np.float32))
        batch = {k: (v.to(self.dev) if hasattr(v, "to") else v) for k, v in next(iter(torch.utils.data.DataLoader(ds, batch_size=1))).items()}
        with torch.no_grad():
            out = self.model(batch)
        betas = out["pred_smpl_params"]["betas"][0]                                  # (10,)
        smpl = self.model.smpl
        zeros = torch.zeros((1, 23, 3, 3), device=betas.device); eye = torch.eye(3, device=betas.device).expand(1, 23, 3, 3)
        tpose = smpl(betas=betas[None], body_pose=eye, global_orient=torch.eye(3, device=betas.device)[None, None], pose2rot=False)
        V = tpose.vertices[0].cpu().numpy(); J = tpose.joints[0].cpu().numpy()
        mesh = trimesh.Trimesh(V, smpl.faces, process=False)
        top, bottom = V[:, 1].max(), V[:, 1].min(); mesh_h = top - bottom
        pelvis, sh = J[0], (J[16] + J[17]) / 2                                       # SMPL joints: 0 pelvis, 16/17 shoulders
        def perim_scan(y0, y1, mode):
            ys = np.linspace(y0, y1, 25); ps = [slice_perimeter(mesh, y) for y in ys]
            i = int(np.argmax(ps) if mode == "max" else np.argmin([p if p > 0 else 9 for p in ps])); return ps[i], ys[i]
        torso = sh[1] - pelvis[1]
        chest, y_c = perim_scan(pelvis[1] + 0.62 * torso, pelvis[1] + 0.85 * torso, "max")
        waist, y_w = perim_scan(pelvis[1] + 0.15 * torso, pelvis[1] + 0.55 * torso, "min")
        hip, y_h = perim_scan(pelvis[1] - 0.25 * torso, pelvis[1] + 0.05 * torso, "max")
        shoulder = float(np.linalg.norm(J[16] - J[17]))
        scale = (height_cm / 100) / mesh_h if height_cm else 1.0                    # 메시 키 → 사용자 키
        cm = lambda v: round(float(v * scale * 100), 1)
        return {"ok": True, "chest": cm(chest), "waist": cm(waist), "hip": cm(hip), "shoulder": cm(shoulder),
                "drop": cm(chest - waist), "chest_hip": round(float(chest / hip), 3), "mesh_height_m": round(float(mesh_h), 3),
                "betas": [round(float(b), 3) for b in betas.cpu().numpy()]}

def validate(n, seed=0):
    import pandas as pd
    from validate_body import pick, img_zip
    from body_thresholds import group_of
    p3 = Photo3D(); sel = pick(n, seed); zips = {}; rows = []; t0 = time.time(); tmp = tempfile.mkdtemp(prefix="p3d_")
    for i, r in enumerate(sel.itertuples(index=False)):
        zp = img_zip(r.split, r.category)
        if zp not in zips: z = zipfile.ZipFile(zp); zips[zp] = (z, {os.path.basename(x): x for x in z.namelist()})
        z, mem = zips[zp]; nm = mem.get(r.name + ".jpg")
        if nm is None: continue
        p = os.path.join(tmp, "img.jpg"); open(p, "wb").write(z.read(nm))
        res = p3(p, float(r.body_height))
        if not res["ok"]: continue
        sex = "M" if r.gender == "MALE" else "F"
        rows.append(dict(name=r.name, sex=sex, height=r.body_height, weight=r.weight, t_chest=r.chest, t_waist=r.waist_size, t_hip=r.hip_seize, t_shoulder=r.shoulders_width,
                         p_chest=res["chest"], p_waist=res["waist"], p_hip=res["hip"], p_shoulder=res["shoulder"],
                         t_group=group_of(sex, r.chest, r.waist_size, r.hip_seize), p_group=group_of(sex, res["chest"], res["waist"], res["hip"])))
        if (i + 1) % 25 == 0: print(f"  {i+1}/{len(sel)}  {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows); os.makedirs(OUT, exist_ok=True); df.to_csv(os.path.join(OUT, "photo3d_val.csv"), index=False, encoding="utf-8-sig")
    L = ["# 사진 3D 메시(HMR2.0) 방식 검증 — 의류 통합 데이터 실측", "", f"성별당 {n}명, 사람당 사진 1장. 절대 cm 는 메시 키를 실제 키로 환산.", ""]
    for sex in ("M", "F"):
        d = df[df.sex == sex]
        if not len(d): continue
        L += [f"## {'남성' if sex == 'M' else '여성'} n={len(d)}", "", "| 항목 | MAE (cm) | 편향 | r | ±5cm |", "|---|---|---|---|---|"]
        for k, nm in (("chest", "가슴둘레"), ("waist", "허리둘레"), ("hip", "엉덩이둘레"), ("shoulder", "어깨너비")):
            e = d[f"p_{k}"] - d[f"t_{k}"]; L.append(f"| {nm} | {e.abs().mean():.1f} | {e.mean():+.1f} | {np.corrcoef(d[f'p_{k}'], d[f't_{k}'])[0,1]:.2f} | {(e.abs() <= 5).mean()*100:.0f}% |")
        tdrop = d.t_chest - d.t_waist; pdrop = d.p_chest - d.p_waist; tch = d.t_chest / d.t_hip; pch = d.p_chest / d.p_hip
        L += ["", f"형태 지표 상관: 드롭 r {np.corrcoef(pdrop, tdrop)[0,1]:.2f}, 가슴/엉덩이 r {np.corrcoef(pch, tch)[0,1]:.2f}",
              f"**3대 체형(3분위) 일치율 {(d.t_group == d.p_group).mean()*100:.1f}%** (찍기 33%)", ""]
    io.open(os.path.join(OUT, "photo3d_val.md"), "w", encoding="utf-8").write("\n".join(L)); print("\n".join(L))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("image", nargs="?"); ap.add_argument("--height", type=float); ap.add_argument("--validate", type=int)
    a = ap.parse_args()
    if a.validate: validate(a.validate)
    elif a.image: print(json.dumps(Photo3D()(a.image, a.height), ensure_ascii=False, indent=1))
    else: ap.print_help()
