"""
AI 생성 형태 컷(라이트 그레이) → 추천 색으로 칠하기. 재생성 없이 CPU 로 수 ms.
배경은 테두리에서 flood fill 로 잡고(옷 속 밝은 하이라이트는 배경으로 안 빠지게), 옷은 '목표 색 + 원래 명암 차이'로 칠한다.
  tinted(path, "네이비") → PIL.Image
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

COLORS = {   # K-Fashion 색 이름 → 대표 RGB. 11/11 "색이 너무 튄다" 피드백: 실제 옷에서 보이는 톤으로 채도를 낮춤 (이전 값은 원색에 가까워 화면에서 쨍했다)
    "블랙": (35, 35, 38), "화이트": (244, 243, 238), "그레이": (140, 142, 146), "실버": (192, 194, 198),
    "네이비": (38, 52, 92), "블루": (80, 108, 148), "스카이블루": (155, 183, 208), "민트": (165, 203, 188),
    "그린": (84, 115, 90), "카키": (110, 112, 70), "베이지": (215, 196, 165), "브라운": (110, 75, 50),
    "레드": (158, 52, 56), "와인": (110, 30, 45), "핑크": (218, 172, 180), "라벤더": (182, 170, 204),
    "퍼플": (100, 76, 124), "옐로우": (222, 198, 118), "오렌지": (200, 128, 82), "골드": (188, 160, 98),
    "네온": (196, 222, 120),
}
GLOSS = {"골드", "실버"}


def mask_of(img, thresh=14):
    """옷 마스크 (0~1). 네 귀퉁이에서 배경을 flood fill → 남은 게 옷. 경계는 살짝 블러."""
    g = img.convert("L"); w, h = g.size
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if g.getpixel(xy) != 0: ImageDraw.floodfill(g, xy, 0, thresh=thresh)
    m = (np.asarray(g) != 0).astype(np.uint8) * 255
    return np.asarray(Image.fromarray(m).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255


def tint(img, color):
    rgb = COLORS.get(color)
    if rgb is None: return img
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    m = mask_of(img)
    L = a.mean(axis=2)
    ref = np.median(L[m > 0.5]) if (m > 0.5).any() else 200.0
    base = np.array(rgb, dtype=np.float32)
    dark = base.mean() < 70                         # 검정·네이비는 명암을 줄여야 회색 얼룩이 안 생김
    k = 0.55 if dark else (1.15 if color in GLOSS else 0.9)
    shade = base[None, None, :] + k * (L - ref)[..., None]
    out = m[..., None] * np.clip(shade, 0, 255) + (1 - m[..., None]) * a
    return Image.fromarray(out.astype(np.uint8))


def tinted(path, color):
    return tint(Image.open(path), color)
