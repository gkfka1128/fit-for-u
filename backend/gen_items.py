"""
추천 후보 아이템 제품 컷 AI 생성 (A안, 10/14 회의) — 형태만, 색은 라이트 그레이로 통일.
data/kfashion_items.json 의 상의 492 · 하의 222 · 아우터 132 + 신발 14 → 속성 → 영어 프롬프트 → ComfyUI(FLUX.1 Kontext dev) → PNG.
색 바리에이션(B안: Kontext 편집으로 형태 유지·색만 변경)은 이 결과를 원본으로 다음 단계에서.

  ComfyUI 를 먼저 띄운다: D:\\Study\\Claude\\AIThumnail\\ComfyUI  venv\\Scripts\\python.exe main.py --listen 127.0.0.1 --port 8188
  .\\.venv\\Scripts\\python.exe gen_items.py --dry            # 프롬프트만 출력
  .\\.venv\\Scripts\\python.exe gen_items.py [--limit 20] [--part 상의]   # 이어서 실행 가능 (있는 파일은 건너뜀)
출력: data/gen_items/{top,bottom,outer,shoes}/NNN.png + data/gen_items/manifest.json (파일 ↔ 속성·프롬프트·seed)
  --sex M : 남성 실루엣 컷 (10/27, "남녀 추천이 비슷해 보임") → data/gen_items/m/... — 남녀 실루엣이 실제로 다른 종류(셔츠·니트·바지·재킷·코트 등)만.
            티셔츠·후드티·조거팬츠·패딩·짚업은 남녀 형태 차이가 작아 공용 컷을 그대로 쓴다
⚠ FLUX.1 [dev] 는 비상업 라이선스 — 연구·교육용.
"""
import argparse, json, os, shutil, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "gen_items")
API = "http://127.0.0.1:8188"
COMFY_OUT = r"D:\Study\Claude\AIThumnail\ComfyUI\output"
PART_EN = {"상의": "top", "하의": "bottom", "아우터": "outer", "신발": "shoes"}
COLOR = "light gray"
STYLE = ("studio product photograph of a single {x}, ghost mannequin style, no person, no model, centered, front view, "
         "isolated on pure white background, soft even lighting, e-commerce catalog, sharp fabric texture")
SHOE_STYLE = "studio product photograph of {x}, three-quarter side view, no person, centered, isolated on pure white background, soft even lighting, e-commerce catalog"

CAT = {"티셔츠": "t-shirt", "셔츠": "button-up shirt", "니트웨어": "knit sweater", "블라우스": "blouse", "탑": "top", "후드티": "pullover hoodie",
       "청바지": "jeans", "팬츠": "trousers", "스커트": "skirt", "래깅스": "leggings", "조거팬츠": "jogger pants",
       # 아우터는 '앞이 열리는 겉옷' 을 명시 — 10/15 1차 생성에서 cardigan/jumper/jacket 이 맨투맨처럼, vest 가 민소매 원피스처럼 나옴
       "재킷": "jacket with collar and front buttons", "가디건": "open-front cardigan with buttons down the front", "코트": "coat",
       "베스트": "sleeveless vest worn as outer layer, with front button closure", "점퍼": "zip-front bomber jacket with ribbed collar and hem",
       "패딩": "puffer padded jacket", "짚업": "zip-up hooded jacket"}
FIT = {"루즈": "loose fit", "오버사이즈": "oversized", "타이트": "slim tight fit", "스키니": "skinny", "와이드": "wide-leg", "벨보텀": "flared bootcut"}
LEN = {"상의": {"롱": "longline", "크롭": "cropped"},
       "하의": {"발목": "ankle-length", "미니": "mini length", "미디": "midi length", "니렝스": "knee-length", "맥시": "maxi length"},
       "아우터": {"하프": "hip-length", "롱": "long knee-length", "크롭": "cropped", "맥시": "ankle-length maxi"}}
NECK = {"라운드넥": "crew neck", "터틀넥": "turtleneck", "브이넥": "v-neck", "후드": "hooded", "유넥": "scoop neck", "스퀘어넥": "square neck",
        "오프숄더": "off-the-shoulder", "보트넥": "boat neck"}
SLEEVE = {"긴팔": "long sleeve", "반팔": "short sleeve", "7부소매": "three-quarter sleeve", "없음": "sleeveless", "민소매": "sleeveless", "캡": "cap sleeve"}
MAT = {"저지": "cotton jersey", "우븐": "woven cotton", "니트": "knit", "시폰": "chiffon", "울/캐시미어": "wool cashmere", "실크": "silk", "린넨": "linen",
       "레이스": "lace", "헤어 니트": "fuzzy mohair knit", "데님": "denim", "스판덱스": "stretch spandex", "트위드": "tweed", "가죽": "leather",
       "코듀로이": "corduroy", "스웨이드": "suede", "벨벳": "velvet", "패딩": "quilted nylon", "플리스": "fleece", "퍼": "faux fur"}
SHOE = {"스니커즈": "sneakers", "캔버스 스니커즈": "canvas low top sneakers", "러닝화": "running shoes", "로퍼": "leather penny loafers",
        "스웨이드 로퍼": "suede loafers", "옥스포드": "leather oxford shoes", "샌들": "strappy flat sandals", "슬리퍼": "slide sandals",
        "첼시 부츠": "chelsea boots", "앵클 부츠": "ankle boots", "워커": "lace-up combat boots", "롱 부츠": "knee-high boots",
        "플랫 슈즈": "ballet flat shoes", "펌프스": "pointed toe pumps"}


# 남성 컷: 공용 컷은 크롭 재킷·고무줄 와이드 팬츠처럼 여성복 쪽으로 나와서, 남성복 재단(어깨 넓고 직선, 엉덩이 덮는 기장, 벨트 고리 바지)을 못박는다
MALE_CATS = {"상의": {"셔츠", "니트웨어"}, "하의": {"팬츠", "청바지"}, "아우터": {"재킷", "코트", "가디건", "베스트", "점퍼"}}
FIT_M = {"루즈": "relaxed fit", "오버사이즈": "oversized boxy", "타이트": "slim fit", "스키니": "slim tapered", "와이드": "wide straight-leg", "벨보텀": "bootcut"}
CAT_M = {"셔츠": "men's button-up shirt with point collar, straight hem, broad flat shoulders",
         "니트웨어": "men's knit sweater with straight boxy body and ribbed hem at the hips, broad shoulders",
         "팬츠": "men's tailored trousers with belt loops, zip fly, flat front and pressed crease",
         "청바지": "men's five-pocket jeans with belt loops",
         "재킷": "men's jacket with collar and front buttons, broad shoulders, straight boxy cut covering the hips, not cropped",
         "코트": "men's single-breasted overcoat with notched lapels, broad shoulders, straight cut",
         "가디건": "men's button-front knit cardigan, straight cut covering the hips",
         "베스트": "men's sleeveless vest worn as outer layer, with front button closure",
         "점퍼": "men's zip-front bomber jacket with ribbed collar and hem, broad shoulders"}


def describe(part, a, sex=None):
    """속성 → 영어 묘사 (색 포함). 하의는 'pair of' 를 붙인다. sex='M' 이면 남성복 재단"""
    g = lambda d, k: d.get(a.get(k)) if a.get(k) else None
    if sex == "M":
        words = [COLOR, g(FIT_M, "핏"), g(LEN.get(part, {}), "기장"), None if a.get("소재") in ("우븐",) else g(MAT, "소재")]
        if part == "상의": words += [g(NECK, "넥라인"), g(SLEEVE, "소매기장")]
        if part == "아우터" and a.get("기장") == "롱" and a.get("카테고리") == "점퍼": words[2] = "long"
        if part == "아우터" and a.get("기장") == "롱" and a.get("카테고리") == "재킷": words[2] = "longline upper-thigh length"   # 10/27 QA: 'long' 이 셔츠 원피스처럼 나옴
        if (a.get("소재") == "니트" and a.get("카테고리") in ("니트웨어", "가디건")) or (a.get("소재") == "데님" and a.get("카테고리") == "청바지"): words[3] = None
        if part == "하의":
            cat = CAT_M[a["카테고리"]]
            if a.get("소재") == "저지" and a.get("카테고리") == "팬츠": words[3], cat = None, "men's cotton jersey track pants with drawstring"
            if a.get("기장") in ("미니", "니렝스") and a.get("카테고리") == "청바지":   # 10/27 QA: 'denim shorts, above the knee' 가 여성 핫팬츠처럼 짧게 나옴
                words[2], cat = None, "men's five-pocket denim bermuda shorts with belt loops, knee length, straight wide leg openings"
            elif a.get("기장") in ("미니", "니렝스"): words[2], cat = None, cat.replace("trousers", "shorts").replace("pants", "shorts") + ", above the knee"
            else: words[2] = None                                    # 바지는 발목·맥시 모두 정상 기장
            return "pair of " + " ".join(w for w in words + [cat] if w) + ", full garment visible"
        cat = CAT_M[a["카테고리"]]
        if part == "아우터" and a.get("기장") in ("롱", "맥시") and a.get("카테고리") in ("베스트", "가디건"):   # 10/27 QA: 무릎·발목 길이 → 원피스·가운처럼 나옴
            words[2] = "longline mid-thigh length"
            if a["카테고리"] == "베스트": cat = "men's longline sleeveless gilet with notched lapel collar and front buttons, broad shoulders, layering piece"
            else: words[2], cat = "longline upper-thigh length, hem ending well above the knee,", cat + ", long sleeves"   # mid-thigh 도 무릎까지 나와 가운처럼 보임
        return " ".join(w for w in words if w) + " " + cat
    words = [COLOR, g(FIT, "핏"), g(LEN.get(part, {}), "기장"), g(MAT, "소재")]
    if part == "상의":
        hood = a.get("넥라인") == "후드" and a.get("카테고리") == "후드티"      # 'hooded pullover hoodie' 중복 방지
        words += [None if hood else g(NECK, "넥라인"), g(SLEEVE, "소매기장")]
    cat = CAT.get(a.get("카테고리"), "garment")
    if a.get("소재") == "니트" and a.get("카테고리") == "니트웨어": words[3] = None          # 'knit knit sweater' 방지
    if part == "하의" and a.get("카테고리") != "스커트":                                     # 바지 기장은 스커트와 다르게
        words[2] = {"미니": None, "니렝스": "knee-length", "미디": "cropped capri", "맥시": "full-length"}.get(a.get("기장"), words[2])
        if a.get("기장") in ("미니", "니렝스"): cat = "shorts"
    if part == "아우터" and a.get("카테고리") == "베스트":                                   # 10/16: 롱 베스트가 원피스, 하프 베스트가 나시처럼 나와 형태를 더 못박음
        if a.get("기장") == "롱": words[2], cat = None, "long sleeveless gilet coat with notched lapel collar and open V front with buttons, knee length layering piece"
        else: cat = "sleeveless utility vest with shirt collar, front buttons and chest flap pockets"
    if part == "아우터" and a.get("카테고리") == "점퍼" and a.get("기장") in ("롱", "맥시"):         # 10/20: 'long bomber' 는 짧은 항공점퍼로 나옴 → 롱 점퍼는 파카형으로
        cat = "zip-front long parka jacket with stand collar and straight open hem reaching the knees, no ribbed waistband"
    x = " ".join(w for w in words + [cat] if w)
    if part == "하의" and a.get("카테고리") in ("청바지", "팬츠", "래깅스", "조거팬츠"): x = "pair of " + x + ", full garment visible"
    return x


def jobs(engine_items, shoes, sex=None):
    if sex == "M":
        ex = json.load(open(os.path.join(HERE, "rules", "body_rules.json"), encoding="utf-8"))["sex_exclude"]["M"]
        for part in ("상의", "하의", "아우터"):
            for i, it in enumerate(engine_items[part]):
                a = it["attrs"]
                if a.get("카테고리") not in MALE_CATS[part] or any(a.get(k) in vs for k, vs in ex.get(part, {}).items()): continue
                d = describe(part, a, "M")
                yield {"part": part, "idx": i, "attrs": a, "count": it["count"], "desc": d, "prompt": STYLE.format(x=d) + ", menswear",
                       "seed": 5000 + 1000 * list(PART_EN).index(part) + i, "file": f"m/{PART_EN[part]}/{i:03d}.png", "sex": "M"}
        return
    for part in ("상의", "하의", "아우터"):
        for i, it in enumerate(engine_items[part]):
            d = describe(part, it["attrs"])
            yield {"part": part, "idx": i, "attrs": it["attrs"], "count": it["count"], "desc": d, "prompt": STYLE.format(x=d),
                   "seed": 1000 * list(PART_EN).index(part) + i, "file": f"{PART_EN[part]}/{i:03d}.png"}
    for i, s in enumerate(shoes):
        d = f"pair of {COLOR} {SHOE.get(s['name'], s['name'])}"
        yield {"part": "신발", "idx": i, "attrs": {"카테고리": s["name"]}, "count": None, "desc": d, "prompt": SHOE_STYLE.format(x=d),
               "seed": 3000 + i, "file": f"shoes/{i:03d}.png"}


def workflow(prompt, seed, size, prefix):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev-kontext_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": T5, "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": 3.0}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": size, "height": size, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
                                                    "seed": seed, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


T5 = "t5xxl_fp16.safetensors"


def run_one(job, size):
    req = urllib.request.Request(API + "/prompt", json.dumps({"prompt": workflow(job["prompt"], job["seed"], size, "ffu_items/" + job["file"][:-4].replace("/", "_"))}).encode(),
                                 {"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req))["prompt_id"]
    while True:
        h = json.load(urllib.request.urlopen(f"{API}/history/{pid}"))
        if pid in h:
            if h[pid].get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(h[pid]["status"])[:400])
            imgs = [i for o in h[pid]["outputs"].values() for i in o.get("images", [])]
            if imgs:
                im = imgs[0]; return os.path.join(COMFY_OUT, im["subfolder"], im["filename"])
        time.sleep(0.5)


def main():
    global T5
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true"); ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--part", default=None, choices=list(PART_EN)); ap.add_argument("--size", type=int, default=768)
    ap.add_argument("--t5", default=T5, help="ComfyUI text_encoders 안의 T5 파일명")
    ap.add_argument("--sex", default=None, choices=["M"], help="M: 남성 실루엣 컷 (data/gen_items/m/)")
    ap.add_argument("--first", default=None, help="먼저 만들 파일 목록 JSON (실제 추천에 자주 나오는 것부터)")
    ap.add_argument("--changed", action="store_true", help="이미 있어도 manifest 프롬프트와 지금 프롬프트가 다르면 다시 생성 (프롬프트 수정 후)")
    ap.add_argument("--reseed", default="", help="쉼표로 구분한 파일(m/outer/072.png 등) — seed +100 으로 다시 생성 (배경·모양 불량 컷)")
    a = ap.parse_args(); T5 = a.t5
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", buffering=1, closefd=False)
    items = json.load(open(os.path.join(HERE, "data", "kfashion_items.json"), encoding="utf-8"))
    shoes = json.load(open(os.path.join(HERE, "rules", "weather_rules.json"), encoding="utf-8"))["shoes"]["items"]
    js = [j for j in jobs(items, shoes, a.sex) if a.part in (None, j["part"])]
    if a.dry:
        for j in js[: a.limit or len(js)]: print(j["file"], "|", j["desc"])
        print(len(js), "건"); return
    mpath = os.path.join(OUT, "manifest.json")
    man = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {"_doc": __doc__.strip().splitlines()[0], "items": {}}
    for j in js:      # 중간에 끊겨 manifest 에 못 적힌 기존 파일 보충 (프롬프트·seed 는 결정적이라 다시 계산해도 같음)
        if j["file"] not in man["items"] and os.path.exists(os.path.join(OUT, j["file"])):
            man["items"][j["file"]] = {k: j[k] for k in ("part", "idx", "attrs", "count", "desc", "prompt", "seed", "sex") if k in j} | {"size": a.size, "model": "flux1-dev-kontext_fp8_scaled", "t5": T5}
    reseed = {f.strip() for f in a.reseed.split(",") if f.strip()}
    for j in js:
        if j["file"] in reseed: j["seed"] += 100
    todo = [j for j in js if not os.path.exists(os.path.join(OUT, j["file"])) or j["file"] in reseed
            or (a.changed and man["items"].get(j["file"], {}).get("prompt") not in (None, j["prompt"]))]
    if a.first:
        rank = {f: k for k, f in enumerate(json.load(open(a.first, encoding="utf-8")))}
        todo.sort(key=lambda j: rank.get(j["file"], len(rank)))
    todo = todo[: a.limit]
    print(f"생성 {len(todo)} / 전체 {len(js)} (있는 {len(js) - len([j for j in js if not os.path.exists(os.path.join(OUT, j['file']))])})", flush=True)
    t0 = time.time()
    for n, j in enumerate(todo, 1):
        t = time.time()
        src = run_one(j, a.size)
        dst = os.path.join(OUT, j["file"]); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy(src, dst)
        man["items"][j["file"]] = {k: j[k] for k in ("part", "idx", "attrs", "count", "desc", "prompt", "seed", "sex") if k in j} | {"size": a.size, "model": "flux1-dev-kontext_fp8_scaled", "t5": T5}
        if n % 10 == 0 or n == len(todo):
            json.dump(man, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        el = time.time() - t0
        print(f"[{n}/{len(todo)}] {j['file']} {time.time() - t:.0f}s · 남은 예상 {el / n * (len(todo) - n) / 60:.0f}분", flush=True)
    json.dump(man, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
