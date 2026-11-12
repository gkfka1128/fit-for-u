"""
사진 → 체형 특징 벡터 (학습용).  body_measure.py 와 같은 모델(MediaPipe 세그멘테이션 + 포즈)을 쓰되
절대 치수를 '계산'하지 않고, 스케일에 무관한 비율만 뽑아 회귀 모델(train_body.py)의 입력으로 쓴다.

  특징 (모두 사진 픽셀 비율 — 키·카메라 거리와 무관)
    lm_shoulder, lm_hip           : 어깨(11-12)·엉덩이(23-24) 랜드마크 폭 / 전신 높이
    lm_torso, lm_leg, lm_arm      : 어깨~엉덩이, 엉덩이~발목, 어깨~손목 길이 / 전신 높이
    w00..w11                      : 어깨선부터 엉덩이 아래까지 12 등분 행의 몸통 너비(팔 제외 경계 안) / 전신 높이
    w_min, w_max, w_min_pos       : 몸통 너비 최소·최대, 최소 위치(0~1)
    mask_area, mask_h_ratio       : 마스크 면적 / 정규화길이², 마스크 높이 / 정규화길이 (배경 붙음 판별)
    * 정규화 길이 = 코~발목 랜드마크 거리 (마스크 높이는 배경이 붙으면 틀림)
    facing                        : +1 정면(왼어깨가 화면 오른쪽) / −1 뒷모습
    wl_*                          : MediaPipe 3D world landmark 로 잰 어깨폭·골반폭·몸통·다리 길이(m), 어깨/골반 비
    shoulder_tilt, hip_tilt, arm_asym : 촬영 품질 (정면 직립이면 0 근처) — 학습 시 필터
    nose_vis                      : 코 랜드마크 visibility (뒷모습·가림 판별)

  extractor = FeatureExtractor(); f = extractor(img_path)  → dict 또는 None(사람 검출 실패)
"""
import os, sys
import numpy as np, cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision
from body_measure import POSE_MODEL, SEG_MODEL, torso_width_at

N_ROWS = 12
NAMES = ["lm_shoulder", "lm_hip", "lm_torso", "lm_leg", "lm_arm"] + [f"w{i:02d}" for i in range(N_ROWS)] + ["w_min", "w_max", "w_min_pos", "mask_area", "mask_h_ratio", "facing", "nose_vis",
         "wl_shoulder", "wl_hip", "wl_torso", "wl_leg", "wl_sh_hip", "shoulder_tilt", "hip_tilt", "arm_asym"]

class FeatureExtractor:
    def __init__(self):
        self.seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_buffer=open(SEG_MODEL, "rb").read()), output_category_mask=True))
        self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=open(POSE_MODEL, "rb").read()), num_poses=1))

    def __call__(self, img_path):
        bgr = cv2.imread(img_path)
        if bgr is None: return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); H, W = rgb.shape[:2]
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        cat = self.seg.segment(mp_img).category_mask.numpy_view()
        mask = (cat > 0).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
        mask = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else mask.astype(bool)
        res = self.pose.detect(mp_img)
        if not res.pose_landmarks: return None
        lm = res.pose_landmarks[0]
        P = lambda i: np.array([lm[i].x * W, lm[i].y * H])
        rows = np.where(mask.any(axis=1))[0]
        if not len(rows): return None
        # 정규화 길이 = 코 ~ 발목 (랜드마크만 사용). 마스크 높이는 벽의 종이·거울 기둥이 붙으면 틀려서 안 쓴다 (9/20: 마스크 기준일 때 특징이 BMI 와도 r<0.2)
        ankle_y = (P(27)[1] + P(28)[1]) / 2
        body = max(ankle_y - P(0)[1], 1.0)
        mask_h = rows[-1] - rows[0]

        ls, rs, lh, rh = P(11), P(12), P(23), P(24)
        sh_y, hip_y = (ls[1] + rs[1]) / 2, (lh[1] + rh[1]) / 2
        cx = int((lh[0] + rh[0]) / 2); T = hip_y - sh_y
        half = max(abs(ls[0] - rs[0]) * 0.62, abs(lh[0] - rh[0]) * 0.9); bound = (int(cx - half), int(cx + half))
        f = {"lm_shoulder": abs(ls[0] - rs[0]) / body, "lm_hip": abs(lh[0] - rh[0]) / body, "lm_torso": T / body,
             "lm_leg": ((P(27)[1] + P(28)[1]) / 2 - hip_y) / body, "lm_arm": (np.linalg.norm(P(15) - ls) + np.linalg.norm(P(16) - rs)) / 2 / body}
        ws = []
        for i in range(N_ROWS):
            y = int(sh_y + (i / (N_ROWS - 1)) * (T * 1.25))          # 어깨선 ~ 엉덩이 아래 0.25T
            y = min(max(y, 0), H - 1)
            w_px, _, _ = torso_width_at(mask, y, cx, bound); ws.append(w_px / body)
        ws = np.array(ws)
        for i, w in enumerate(ws): f[f"w{i:02d}"] = float(w)
        f["w_min"], f["w_max"], f["w_min_pos"] = float(ws[2:].min()), float(ws.max()), float(np.argmin(ws[2:]) / (N_ROWS - 3))
        f["mask_area"] = float(mask.sum() / body ** 2)
        f["mask_h_ratio"] = float(mask_h / body)                       # 마스크 높이 / 코~발목. 정상 ≈ 1.2~1.4, 크면 배경이 붙은 것
        f["facing"] = 1.0 if ls[0] > rs[0] else -1.0                  # 정면이면 왼어깨(11)가 화면 오른쪽
        f["nose_vis"] = float(lm[0].visibility)
        # MediaPipe 3D world landmarks (미터, 엉덩이 중심 기준) — 카메라 거리·기울기에 덜 민감한 폭·길이
        wl = res.pose_world_landmarks[0] if res.pose_world_landmarks else None
        if wl:
            Wp = lambda i: np.array([wl[i].x, wl[i].y, wl[i].z])
            f["wl_shoulder"] = float(np.linalg.norm(Wp(11) - Wp(12))); f["wl_hip"] = float(np.linalg.norm(Wp(23) - Wp(24)))
            f["wl_torso"] = float(np.linalg.norm((Wp(11) + Wp(12)) / 2 - (Wp(23) + Wp(24)) / 2))
            f["wl_leg"] = float((np.linalg.norm(Wp(23) - Wp(27)) + np.linalg.norm(Wp(24) - Wp(28))) / 2)
            f["wl_sh_hip"] = f["wl_shoulder"] / max(f["wl_hip"], 1e-6)
        else:
            for k in ("wl_shoulder", "wl_hip", "wl_torso", "wl_leg", "wl_sh_hip"): f[k] = float("nan")
        # 촬영 품질: 어깨·골반 기울기(정면·수평이면 0), 팔 길이 비대칭(비스듬한 자세면 커짐)
        f["shoulder_tilt"] = float(abs(ls[1] - rs[1]) / max(abs(ls[0] - rs[0]), 1.0))
        f["hip_tilt"] = float(abs(lh[1] - rh[1]) / max(abs(lh[0] - rh[0]), 1.0))
        aL, aR = np.linalg.norm(P(15) - ls), np.linalg.norm(P(16) - rs)
        f["arm_asym"] = float(abs(aL - aR) / max((aL + aR) / 2, 1.0))
        return f
