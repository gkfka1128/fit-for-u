"""
기상청 단기예보(getVilageFcst) — 강수확률(POP)·최고/최저기온·하늘상태. 초단기실황(getUltraSrtNcst)과 같은 서비스(VilageFcstInfoService_2.0)라 키 하나로 둘 다 된다.

  발표: 하루 8번 (02·05·08·11·14·17·20·23시), 각 발표 약 10분 뒤부터 조회 가능
  쓰는 값: 지금부터 HOURS 시간 안의 POP 최댓값 = "나가 있는 동안 비 올 확률" → 규칙 엔진 precip_prob
           오늘 TMX/TMN (없으면 오늘 TMP 의 최대/최소), 가장 가까운 시각의 SKY (1 맑음 · 3 구름많음 · 4 흐림)

  fc = fetch_forecast(api_key, "data_go_kr", 60, 127)   # provider: "data_go_kr"(공공데이터포털) | "apihub"(기상청 API허브)
  → {"precip_prob": 60, "pop_now": 30, "tmx": 18.0, "tmn": 9.0, "sky": "구름많음", "base": "2026-10-18T17:00", "hours": 12}
"""
from datetime import datetime, timedelta, timezone

import requests
from urllib.parse import unquote

KST = timezone(timedelta(hours=9))
BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
HOURS = 12                                             # 나가 있는 시간으로 보는 범위
SKY = {1: "맑음", 3: "구름많음", 4: "흐림"}
URL = {"data_go_kr": "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst",
       "apihub": "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"}


class ForecastError(Exception):
    pass


def latlon_to_grid(lat, lon):
    """위도·경도 → 기상청 동네예보 격자 (nx, ny). 기상청 공개 변환식 (Lambert 정각원추, 5km 격자)"""
    import math
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    d = math.pi / 180.0; re = RE / GRID
    s1, s2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(math.tan(math.pi / 4 + s2 / 2) / math.tan(math.pi / 4 + s1 / 2))
    sf = math.tan(math.pi / 4 + s1 / 2) ** sn * math.cos(s1) / sn
    ro = re * sf / math.tan(math.pi / 4 + olat / 2) ** sn
    ra = re * sf / math.tan(math.pi / 4 + lat * d / 2) ** sn
    theta = lon * d - olon
    theta = theta - 2 * math.pi if theta > math.pi else theta + 2 * math.pi if theta < -math.pi else theta
    theta *= sn
    return int(ra * math.sin(theta) + XO + 0.5), int(ro - ra * math.cos(theta) + YO + 0.5)


def in_korea(lat, lon):
    return 32.5 <= lat <= 39.5 and 124.0 <= lon <= 132.0


def forecast_base(now):
    """now(KST) 기준 조회 가능한 가장 최근 발표 시각 (발표 후 10분 지연 고려)"""
    t = now - timedelta(minutes=10)
    for h in reversed(BASE_HOURS):
        if t.hour >= h: return t.replace(hour=h, minute=0, second=0, microsecond=0)
    return (t - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)


def parse_forecast(items, now, base, hours=HOURS):
    """items = 응답 item 목록 → 요약 dict. 값이 하나도 없으면 ForecastError"""
    rows = {}
    for it in items:
        try:
            at = datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M").replace(tzinfo=KST)
            rows.setdefault(at, {})[it["category"]] = it["fcstValue"]
        except (KeyError, ValueError, TypeError):
            continue
    start = now.replace(minute=0, second=0, microsecond=0)
    window = sorted(t for t in rows if start <= t < start + timedelta(hours=hours))
    pops = [int(float(rows[t]["POP"])) for t in window if "POP" in rows[t]]
    if not pops: raise ForecastError("단기예보에 강수확률(POP)이 없습니다")
    today = now.strftime("%Y%m%d")
    day = [t for t in rows if t.strftime("%Y%m%d") == today]
    num = lambda t, k: float(rows[t][k]) if k in rows[t] else None
    tmx = next((num(t, "TMX") for t in day if num(t, "TMX") is not None), None)
    tmn = next((num(t, "TMN") for t in day if num(t, "TMN") is not None), None)
    tmps = [num(t, "TMP") for t in day if num(t, "TMP") is not None]
    if tmx is None and tmps: tmx = max(tmps)                 # 오후 발표엔 오늘 TMN/TMX 가 빠짐 → 남은 시각 TMP 로 근사
    if tmn is None and tmps: tmn = min(tmps)
    sky = next((SKY.get(int(float(rows[t]["SKY"]))) for t in window if "SKY" in rows[t]), None)
    first = rows[window[0]]                                  # 가장 가까운 예보 시각의 기온·습도·풍속 (체감온도 계산용)
    f = lambda k: float(first[k]) if k in first else None
    return {"precip_prob": max(pops), "pop_now": pops[0], "tmx": tmx, "tmn": tmn, "sky": sky,
            "temp": f("TMP"), "humidity": f("REH"), "wind": f("WSD"),
            "base": base.isoformat(timespec="minutes"), "hours": hours}


def fetch_forecast(api_key, provider, nx, ny, now=None, timeout=(5, 10)):
    if not api_key: raise ForecastError("KMA_API_KEY 가 없습니다")
    now = now or datetime.now(KST)
    if "%" in api_key: api_key = unquote(api_key)               # 포털의 Encoding 키를 붙여 넣어도 됨 (requests 가 다시 인코딩하므로 먼저 풀어 둔다)
    auth = {"authKey": api_key} if provider == "apihub" else {"serviceKey": api_key}
    base = forecast_base(now)
    for back in range(2):                                     # 막 발표된 직후 비어 있으면 한 회차 전으로
        b = base - timedelta(hours=3 * back)
        params = dict(auth, pageNo=1, numOfRows=1000, dataType="JSON", base_date=b.strftime("%Y%m%d"), base_time=b.strftime("%H%M"), nx=nx, ny=ny)
        try:
            r = requests.get(URL[provider], params=params, timeout=timeout); r.raise_for_status()
            payload = r.json()["response"]
        except requests.RequestException as e:
            raise ForecastError(f"단기예보 요청 실패 ({type(e).__name__})") from None
        except (ValueError, KeyError, TypeError):
            raise ForecastError("단기예보 응답이 JSON 이 아닙니다 — 키·발급처·활용신청 승인을 확인해 주세요") from None
        code = str(payload.get("header", {}).get("resultCode", "")).zfill(2)
        if code == "03": continue                              # NODATA
        if code != "00": raise ForecastError(f"단기예보 오류 코드 {code} {payload.get('header', {}).get('resultMsg', '')}".strip())
        items = (payload.get("body", {}).get("items") or {}).get("item", [])
        if isinstance(items, dict): items = [items]
        if items: return parse_forecast(items, now, b)
    raise ForecastError("단기예보 자료가 아직 없습니다. 잠시 후 다시 시도해 주세요")
