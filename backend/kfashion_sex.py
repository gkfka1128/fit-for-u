"""
K-Fashion 모델 성별 추정 — CLIP zero-shot (K-Fashion 에는 성별 라벨이 없다)

  사진마다 "a photo of a man …" vs "a photo of a woman …" 유사도 → p_male.  얼굴은 가려져 있어 체형·머리·옷으로 판단.
  결과 = data/kfashion_sex.csv (img_id, split, style, p_male).  남성 서브셋 = p_male ≥ 0.5 (kfashion_male.py 가 사용)

  .\.venv\Scripts\python.exe kfashion_sex.py [--limit N] [--bench]
"""
import argparse, csv, io, os, sys, time, zipfile
import numpy as np, torch
from PIL import Image, ImageOps
from torch.utils.data import Dataset, DataLoader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "Data", "K-Fashion 이미지")
ZIPS = [("train", os.path.join(ROOT, "Training", f"원천데이터_{i}.zip")) for i in (1, 2, 3)] + [("val", os.path.join(ROOT, "Validation", "원천데이터.zip"))]
OUT = os.path.join(HERE, "data", "kfashion_sex.csv")
MODEL, PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"
MALE = ["a photo of a man", "a photo of a man wearing clothes", "a male fashion model", "a photo of a boy", "menswear outfit photo"]
FEMALE = ["a photo of a woman", "a photo of a woman wearing clothes", "a female fashion model", "a photo of a girl", "womenswear outfit photo"]

def fix(name):
    try: return name.encode("cp437").decode("cp949")
    except Exception: return name

class ZipImages(Dataset):
    def __init__(self, entries, preprocess):
        self.entries = entries; self.pre = preprocess; self.z = {}
    def __len__(self): return len(self.entries)
    def __getitem__(self, i):
        split, zp, nm = self.entries[i]
        if zp not in self.z: self.z[zp] = zipfile.ZipFile(zp)          # worker 마다 자기 핸들
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(self.z[zp].read(nm)))).convert("RGB")   # 회전 정보 반영
            return self.pre(img), i, True
        except Exception:
            return torch.zeros(3, 224, 224), i, False

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int); ap.add_argument("--bench", action="store_true")
    ap.add_argument("--workers", type=int, default=6); ap.add_argument("--batch", type=int, default=256); ap.add_argument("--only", help="train|val 만")
    a = ap.parse_args()
    import open_clip
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, pre = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED, device=dev)
    model.eval(); tok = open_clip.get_tokenizer(MODEL)
    with torch.no_grad():
        T = model.encode_text(tok(MALE + FEMALE).to(dev)); T = T / T.norm(dim=-1, keepdim=True)
        t_m, t_f = T[:len(MALE)].mean(0), T[len(MALE):].mean(0)
        t_m, t_f = t_m / t_m.norm(), t_f / t_f.norm()

    done = set()
    if os.path.exists(OUT) and not a.bench:
        with io.open(OUT, encoding="utf-8") as f:
            done = {int(r["img_id"]) for r in csv.DictReader(f)}
    entries, meta = [], []
    for split, zp in ZIPS:
        if not os.path.exists(zp) or (a.only and split != a.only): continue
        for nm in zipfile.ZipFile(zp).namelist():
            if not nm.lower().endswith(".jpg"): continue
            iid = int(os.path.splitext(os.path.basename(nm))[0])
            if iid in done: continue
            entries.append((split, zp, nm)); meta.append((iid, split, fix(nm.split("/")[0])))
    if a.limit: entries, meta = entries[:a.limit], meta[:a.limit]
    print(f"{len(entries):,} images to do (already {len(done):,})", flush=True)
    if not entries: return

    dl = DataLoader(ZipImages(entries, pre), batch_size=a.batch, num_workers=a.workers, pin_memory=(dev == "cuda"))
    mode = "a" if os.path.exists(OUT) and not a.bench else "w"
    f = io.open(OUT if not a.bench else os.devnull, mode, encoding="utf-8", newline=""); w = csv.writer(f)
    if mode == "w": w.writerow(["img_id", "split", "style", "p_male"])
    t0 = time.time(); n = 0
    with torch.no_grad(), torch.autocast(device_type=dev, dtype=torch.float16, enabled=(dev == "cuda")):
        for x, idx, ok in dl:
            e = model.encode_image(x.to(dev, non_blocking=True)); e = e / e.norm(dim=-1, keepdim=True)
            logits = torch.stack([e @ t_m, e @ t_f], 1).float() * 100                  # CLIP logit scale
            p = torch.softmax(logits, 1)[:, 0].cpu().numpy()
            for j, i, o in zip(range(len(idx)), idx.tolist(), ok.tolist()):
                iid, split, style = meta[i]
                w.writerow([iid, split, style, f"{p[j]:.3f}" if o else ""])
            n += len(idx)
            if n % (a.batch * 20) == 0 or n == len(entries):
                el = time.time() - t0; print(f"  {n:,}/{len(entries):,}  {el:.0f}s  {n/el:.0f} img/s  ETA {(len(entries)-n)/max(n/el,1e-9)/60:.0f} min", flush=True); f.flush()
    f.close(); print("done", OUT)

if __name__ == "__main__":
    main()
