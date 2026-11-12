"""
코디 보드 — 추천 1안을 잡지 플랫레이 한 장으로 합성한다 (칸 나눠 보여주는 대신).

  제품 컷(data/thumbs_product/**, 배경이 정확히 회색 224)에서 배경을 빼 누끼 → 흰 캔버스에 역할별 위치·크기로 배치 → 라벨(카테고리 태그 + 이름 + 검색어)
  제품 컷이 없는 부위는 K-Fashion 색별 컷(배경 있는 사진)을 둥근 사각형으로 넣는다. 신발은 Zappos 컷(흰 배경) — 누끼 처리 동일.

  from outfit_board import board;  board(outfit, "out.jpg")        # outfit = rule_engine.recommend()["outfits"][i]
  .\\.venv\\Scripts\\python.exe outfit_board.py                       # 샘플 6장 → runs/_peek/board_*.jpg
"""
import io, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BG = 224                      # thumbs_product 의 배경 값 (product_attrs.backdrop)
W, H = 1000, 1240
FONT = "C:/Windows/Fonts/malgun.ttf"; FONT_B = "C:/Windows/Fonts/malgunbd.ttf"
# 참고 레이아웃: 큰 아우터 좌상 · 하의 좌하 · 상의 우중 · 신발 우하. 라벨은 빈 자리를 찾아 자동 배치(_place)
SLOTS = {                     # 역할 → (중심 x, 중심 y, 최대 너비, 최대 높이)
    "main":   (285, 315,  470, 460),
    "bottom": (300, 840,  470, 540),
    "sub":    (735, 505,  360, 320),
    "shoes":  (745, 1075, 290, 190),
}


def _font(size, bold=False):
    path = FONT_B if bold else FONT
    return ImageFont.truetype(path, size) if os.path.exists(path) else ImageFont.load_default()


def cutout(rel, keyed=True):
    """옷 사진 → (RGB, alpha). keyed=True 면 배경(테두리 색: 제품 컷 회색 224 · 신발 컷 흰색)을 투명으로 빼고 구멍 메움·가장자리 정리.
    keyed=False (K-Fashion 크롭처럼 배경이 실사) 면 알파 없이 그대로"""
    from scipy import ndimage
    path = rel if os.path.isabs(rel) else os.path.join(HERE, rel)
    if not os.path.exists(path): return None, None
    im = Image.open(path).convert("RGB"); a = np.asarray(im).astype(np.int16)
    if not keyed: return im, None
    bg = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), 0)
    fg = np.abs(a - bg).max(2) > 12
    fg = ndimage.binary_closing(fg, iterations=2)
    fg = ndimage.binary_fill_holes(fg)                                  # 옷 안쪽에 배경색이 남아 구멍 나는 것 방지
    lab, n = ndimage.label(fg)
    if not n or fg.mean() < 0.02: return im, None
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    fg = np.isin(lab, [i + 1 for i, sz in enumerate(sizes) if sz > 0.15 * sizes.max()])   # 작은 얼룩(그림자·먼지) 제거
    fg = ndimage.binary_fill_holes(ndimage.binary_closing(fg, iterations=3))
    ys, xs = np.where(fg)
    box = (max(0, xs.min() - 2), max(0, ys.min() - 2), min(im.width, xs.max() + 3), min(im.height, ys.max() + 3))
    al = Image.fromarray((fg[box[1]:box[3], box[0]:box[2]] * 255).astype(np.uint8))
    return im.crop(box), al.filter(ImageFilter.GaussianBlur(0.8))       # 가장자리 톱니 완화


def _paste(canvas, im, alpha, cx, cy, mw, mh):
    """(cx, cy) 중심에 (mw, mh) 안에 들어가게 축소해 붙이고 실제 상자를 돌려준다"""
    im = im.copy(); ratio = min(mw / im.width, mh / im.height)
    size = (max(1, int(im.width * ratio)), max(1, int(im.height * ratio)))
    im = im.resize(size, Image.LANCZOS)
    x, y = int(cx - size[0] / 2), int(cy - size[1] / 2)
    if alpha is not None:
        canvas.paste(im, (x, y), alpha.resize(size, Image.LANCZOS))
    else:                                                     # 배경 있는 사진(K-Fashion 컷)은 옅은 테두리로 구분
        canvas.paste(im, (x, y)); ImageDraw.Draw(canvas).rectangle([x, y, x + size[0] - 1, y + size[1] - 1], outline=(224, 224, 224), width=1)
    return (x, y, x + size[0], y + size[1])


def _label_size(d, tag, lines):
    f_tag, f_name, f_sub = _font(21, True), _font(28, True), _font(20)
    w = max([d.textlength(tag, font=f_tag) + 20] + [d.textlength(ln, font=f_name if i == 0 else f_sub) for i, ln in enumerate(lines)])
    return int(w), 44 + sum(36 if i == 0 else 28 for i in range(len(lines)))


def _draw_label(d, x, y, tag, lines, right_align=False, width=0):
    f_tag, f_name, f_sub = _font(21, True), _font(28, True), _font(20)
    tw = d.textlength(tag, font=f_tag) + 20
    tx = x + width - tw if right_align else x
    d.rectangle([tx, y, tx + tw, y + 32], fill=(20, 20, 20)); d.text((tx + 8, y + 5), tag, font=f_tag, fill="white")
    ty = y + 44
    for i, ln in enumerate(lines):
        f = f_name if i == 0 else f_sub
        lx = x + width - d.textlength(ln, font=f) if right_align else x
        d.text((lx, ty), ln, font=f, fill=(20, 20, 20) if i == 0 else (130, 130, 130)); ty += 36 if i == 0 else 28


def _place(d, box, tag, lines, taken, margin=34):
    """사진 상자(box) 옆 빈 자리에 라벨을 놓는다 — 오른쪽 → 왼쪽 → 아래 → 위 순, 이미 찬 곳(taken)과 안 겹치게"""
    lw, lh = _label_size(d, tag, lines)
    x0, y0, x1, y1 = box
    cy = (y0 + y1) / 2
    cands = [(x1 + 26, y0 + 16, False), (x1 + 26, cy - lh / 2, False), (x1 + 26, y1 - lh - 16, False),
             (x0 - 26 - lw, y0 + 16, True), (x0 - 26 - lw, cy - lh / 2, True), (x0 - 26 - lw, y1 - lh - 16, True),
             (x0, y1 + 14, False), (x0, y0 - lh - 14, False)]

    def fits(x, y):
        r = (x - 8, y - 6, x + lw + 8, y + lh + 6)
        if r[0] < margin or r[2] > W - margin or r[1] < margin or r[3] > H - 70: return None
        return None if any(r[0] < t[2] and t[0] < r[2] and r[1] < t[3] and t[1] < r[3] for t in taken) else r

    for x, y, ra in cands:
        r = fits(x, y)
        if r: _draw_label(d, x, y, tag, lines, ra, lw); taken.append(r); return True
    best = None                                              # 후보가 다 막히면 캔버스를 훑어 가장 가까운 빈 자리
    for gy in range(margin, H - 70 - lh, 20):
        for gx in range(margin, W - margin - lw, 20):
            r = fits(gx, gy)
            if r:
                dist = (gx + lw / 2 - (x0 + x1) / 2) ** 2 + (gy + lh / 2 - cy) ** 2
                if best is None or dist < best[0]: best = (dist, gx, gy, r)
    if best:
        _, gx, gy, r = best; _draw_label(d, gx, gy, tag, lines, False, lw); taken.append(r); return True
    return False


def _lines(tag, it, query=None, ref=False):
    """굵은 줄 = 무신사 검색어(색 + 카테고리), 작은 줄 = 나머지 속성. ref 면 '참고 컷' 표시"""
    label = it["label"]; head = query or label
    rest = [w for w in label.split() if w not in head.split()]
    sub = [" ".join(rest)] if rest else []
    if ref: sub.append("참고 컷 (K-Fashion)")
    return [head] + sub


def board(outfit, out_path=None, footer="FIT-FOR-U · 오늘의 코디"):
    """추천 1안 → 플랫레이 보드 이미지 (PIL Image). out_path 를 주면 저장도 한다"""
    ph = outfit.get("photo") or {}; prod = ph.get("product") or {}; th = ph.get("items") or {}
    canvas = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(canvas)
    # 역할 배정: 아우터가 있으면 아우터가 main·상의가 sub, 없으면 상의가 main
    parts = []
    if outfit.get("outer"): parts += [("main", "아우터", outfit["outer"], prod.get("outer"), th.get("outer")), ("sub", "상의", outfit["top"], prod.get("top"), th.get("top"))]
    else: parts += [("main", "상의", outfit["top"], prod.get("top"), th.get("top"))]
    parts += [("bottom", "하의", outfit["bottom"], prod.get("bottom"), th.get("bottom")),
              ("shoes", "신발", {"label": outfit["shoes"]}, None, th.get("shoes"))]
    q = dict(zip(["아우터", "상의", "하의"] if outfit.get("outer") else ["상의", "하의"], outfit.get("query") or []))
    boxes = []
    for slot, tag, it, p_rel, k_rel in parts:
        cx, cy, mw, mh = SLOTS[slot]
        im, al = cutout(p_rel) if p_rel else (None, None)
        ref = im is None
        if im is None and k_rel: im, al = cutout(k_rel, keyed=(tag == "신발"))
        if im is None: continue
        boxes.append((_paste(canvas, im, al, cx, cy, mw, mh), tag, it, ref and tag != "신발"))
    taken = [b for b, _, _, _ in boxes]
    for box, tag, it, ref in boxes:
        _place(d, box, tag, _lines(tag, it, q.get(tag), ref), taken)
    f = _font(20); tw = d.textlength(footer, font=f)
    d.line([(W / 2 - tw / 2 - 60, H - 46), (W / 2 - tw / 2 - 20, H - 46)], fill=(30, 30, 30), width=1)
    d.line([(W / 2 + tw / 2 + 20, H - 46), (W / 2 + tw / 2 + 60, H - 46)], fill=(30, 30, 30), width=1)
    d.text((W / 2 - tw / 2, H - 54), footer, font=f, fill=(30, 30, 30))
    if out_path: canvas.save(out_path, "JPEG", quality=90)
    return canvas


def main():
    import sys; sys.path.insert(0, HERE)
    from rule_engine import RuleEngine
    e = RuleEngine(); os.makedirs(os.path.join(HERE, "runs", "_peek"), exist_ok=True)
    for sex in ("F", "M"):
        r = e.recommend({"sex": sex, "group": "균형", "build": "보통", "leg": "보통"}, {"feels_like": 12, "precip_prob": 10})
        for i, o in enumerate(r["outfits"], 1):
            p = os.path.join(HERE, "runs", "_peek", f"board_{sex}{i}.jpg"); board(o, p); print(p)


if __name__ == "__main__":
    main()
