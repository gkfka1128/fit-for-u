"""판넬용 비교 그림 — 같은 성별·날씨·상황에서 체형(상·하체 형태)만 바꿨을 때 추천 1안이 어떻게 달라지는지 → runs/fig_compare_*.png

  열 = 상체형 · 균형 · 하체형 (체격 보통), 칸 = 웹 카드와 같은 생성 이미지에 색 입힘 + 이름 + 체형 이유.
  .\\.venv\\Scripts\\python.exe compare_board.py                       # 아래 CASES 전부
  .\\.venv\\Scripts\\python.exe compare_board.py --sex F --situation 데이트 --temp 22
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from PIL import Image, ImageDraw, ImageFont
import ffu_web_bridge as w, tint
from rule_engine import RuleEngine

FONT = "C:/Windows/Fonts/malgun.ttf"; FONT_B = "C:/Windows/Fonts/malgunbd.ttf"
GROUPS = (("상체형", "어깨·가슴이 엉덩이보다 넓은 편"), ("균형", "상·하체 비슷"), ("하체형", "엉덩이·허벅지가 넓은 편"))
PROFILE = {"F": {"gender": "여성", "height": 162, "weight": 55}, "M": {"gender": "남성", "height": 175, "weight": 70}}
CASES = [("F", "데이트", 22), ("F", "친구와 약속", 15), ("M", "출근", 8)]   # 세 체형이 모두 다르게 나오는 조건 중에서 고름
INK, MUTED, ACCENT = (25, 25, 25), (120, 120, 120), (47, 111, 219)
COL, CELL, PAD = 760, 340, 40


def font(size, bold=False): return ImageFont.truetype(FONT_B if bold else FONT, size)


def wrap(d, text, f, width):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > width: lines.append(cur); cur = ch
        else: cur += ch
    return lines + ([cur] if cur else [])


def item_img(card):
    im = Image.open(card["image"]).convert("RGB")
    im = tint.tint(im, card["color"]) if card.get("color") else im
    im.thumbnail((CELL, CELL)); return im


def column(card_list, reasons, title, sub):
    n = len(card_list); rows = (n + 1) // 2
    hdr, name_h = 150, 70
    reason_lines = []
    d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for r in reasons: reason_lines += [("• " if i == 0 else "  ") + ln for i, ln in enumerate(wrap(d0, r, font(26), COL - 2 * PAD - 30))]
    h = hdr + rows * (CELL + name_h) + 30 + 40 * max(len(reason_lines), 1) + PAD
    col = Image.new("RGB", (COL, h), "white"); d = ImageDraw.Draw(col)
    d.text((PAD, 30), title, font=font(52, True), fill=ACCENT); d.text((PAD, 98), sub, font=font(26), fill=MUTED)
    for i, c in enumerate(card_list):
        x = PAD + (i % 2) * (CELL + 0); y = hdr + (i // 2) * (CELL + name_h)
        im = item_img(c); col.paste(im, (x + (CELL - im.width) // 2, y + (CELL - im.height) // 2))
        for k, ln in enumerate(wrap(d, c["name"], font(23), CELL - 10)[:2]):
            d.text((x + CELL // 2, y + CELL + 6 + 28 * k), ln, font=font(23), fill=INK, anchor="ma")
    y = hdr + rows * (CELL + name_h) + 30
    for ln in reason_lines or ["(체형 규칙이 이번 조건에서는 결과를 바꾸지 않음)"]:
        d.text((PAD, y), ln, font=font(26), fill=INK); y += 40
    return col


def board(sex, situation, temp, eng, out):
    cols = []
    for g, sub in GROUPS:
        r = w.recommend_for_web(PROFILE[sex], None, {"feels_like": temp, "precip_prob": 10}, situation, eng=eng,
                                body={"sex": sex, "group": g, "build": "보통", "leg": "보통"})
        o = r["outfits"][0]
        cols.append(column(o["items"], [x["text"] for x in o.get("why", []) if x["kind"] == "체형"], g, sub))
    top = 170; H = top + max(c.height for c in cols)
    img = Image.new("RGB", (COL * len(cols), H), "white"); d = ImageDraw.Draw(img)
    d.text((PAD, 36), f"같은 날씨·상황, 체형만 다르게 — {PROFILE[sex]['gender']} · {situation} · 체감 {temp}°", font=font(54, True), fill=INK)
    d.text((PAD, 112), "Fit-For-U 추천 1안 (체격 보통 · 비 안 옴). 이미지는 AI 생성 예시 컷에 추천 색을 입힌 것", font=font(28), fill=MUTED)
    for i, c in enumerate(cols):
        img.paste(c, (COL * i, top))
        if i: d.line([(COL * i, top + 30), (COL * i, H - 30)], fill=(220, 220, 220), width=3)
    img.save(out, dpi=(300, 300)); print("→", out)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sex", choices=("F", "M")); ap.add_argument("--situation"); ap.add_argument("--temp", type=float)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "runs"))
    a = ap.parse_args()
    cases = [(a.sex, a.situation, a.temp)] if a.sex else CASES
    eng = RuleEngine(); os.makedirs(a.out_dir, exist_ok=True)
    for sex, sit, t in cases:
        t = int(t) if float(t).is_integer() else t
        board(sex, sit, t, eng, os.path.join(a.out_dir, f"fig_compare_{sex}_{sit.replace(' ', '')}_{t}.png"))


if __name__ == "__main__":
    main()
