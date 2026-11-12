"""kma_forecast 테스트 — 네트워크 없이 발표 시각 계산·응답 파싱 (가짜 응답). .\\.venv\\Scripts\\python.exe test_kma_forecast.py"""
import os, sys
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kma_forecast as k
import ffu_web_bridge as b

ok = fail = 0


def check(name, cond):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    if not cond: print("FAIL", name)


T = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=k.KST)
check("발표 05시 직후 10분 안 → 02시", k.forecast_base(T("2026-10-18 05:05")) == T("2026-10-18 02:00"))
check("05:10 → 05시", k.forecast_base(T("2026-10-18 05:10")) == T("2026-10-18 05:00"))
check("새벽 01시 → 전날 23시", k.forecast_base(T("2026-10-18 01:30")) == T("2026-10-17 23:00"))
check("23:30 → 23시", k.forecast_base(T("2026-10-18 23:30")) == T("2026-10-18 23:00"))


def fake_items(base_dt, start, n, pops, with_tmx=True):
    out = []
    for i in range(n):
        t = start + timedelta(hours=i); d, h = t.strftime("%Y%m%d"), t.strftime("%H%M")
        for cat, v in (("POP", pops[i % len(pops)]), ("TMP", 10 + i % 8), ("SKY", (1, 3, 4)[i % 3])):
            out.append({"fcstDate": d, "fcstTime": h, "category": cat, "fcstValue": str(v)})
    if with_tmx:
        d = start.strftime("%Y%m%d")
        out += [{"fcstDate": d, "fcstTime": "0600", "category": "TMN", "fcstValue": "7.0"},
                {"fcstDate": d, "fcstTime": "1500", "category": "TMX", "fcstValue": "19.0"}]
    return out


now = T("2026-10-18 08:20")
items = fake_items(None, T("2026-10-18 09:00"), 30, [20, 30, 60, 10])
fc = k.parse_forecast(items, now, T("2026-10-18 08:00"))
check("POP 최대 (12시간)", fc["precip_prob"] == 60)
check("TMX/TMN", fc["tmx"] == 19.0 and fc["tmn"] == 7.0)
check("SKY", fc["sky"] == "맑음")
fc2 = k.parse_forecast(fake_items(None, T("2026-10-18 09:00"), 30, [20], with_tmx=False), now, T("2026-10-18 08:00"))
check("TMX 없으면 TMP 로", fc2["tmx"] == 17 and fc2["tmn"] == 10)
check("12시간 밖 POP 무시", k.parse_forecast(fake_items(None, T("2026-10-18 09:00"), 30, [10] * 11 + [90] * 19), now, T("2026-10-18 08:00"))["precip_prob"] == 10)
try:
    k.parse_forecast([], now, now); check("빈 응답 → 오류", False)
except k.ForecastError:
    check("빈 응답 → 오류", True)


class Resp:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


ok_payload = {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}
with mock.patch("kma_forecast.requests.get", return_value=Resp(ok_payload)) as g:
    r = k.fetch_forecast("KEY", "data_go_kr", 60, 127, now=now)
    check("fetch 성공", r["precip_prob"] == 60 and g.call_args.kwargs["params"]["serviceKey"] == "KEY" and g.call_args.kwargs["params"]["base_time"] == "0800")
with mock.patch("kma_forecast.requests.get", return_value=Resp(ok_payload)) as g:
    k.fetch_forecast("KEY", "apihub", 60, 127, now=now); check("API허브 authKey", "authKey" in g.call_args.kwargs["params"] and "apihub" in g.call_args.args[0])
with mock.patch("kma_forecast.requests.get", return_value=Resp({"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}}})):
    try: k.fetch_forecast("KEY", "data_go_kr", 60, 127, now=now); check("키 오류 → ForecastError", False)
    except k.ForecastError as e: check("키 오류 → ForecastError", "30" in str(e))
try: k.fetch_forecast("", "data_go_kr", 60, 127); check("키 없음", False)
except k.ForecastError: check("키 없음", True)

# 위경도 → 기상청 격자 (기상청 공개 격자표와 비교)
for name, lat, lon, exp in (("서울시청", 37.5665, 126.9780, (60, 127)), ("부산", 35.1796, 129.0756, (98, 76)),
                            ("대전", 36.3504, 127.3845, (67, 100)), ("제주", 33.4996, 126.5312, (53, 38))):
    check(f"격자 {name}", k.latlon_to_grid(lat, lon) == exp)
check("국외 좌표 거름", not k.in_korea(35.68, 139.69))
import geo_location
R = {"서울": (60, 127), "부산": (98, 76)}
check("위치 → 격자·근처 지역", geo_location.grid_for({"lat": 37.55, "lon": 127.0}, R)[2] == "서울")
check("위치 거부 → None", geo_location.grid_for({"error": "denied"}, R) is None and geo_location.grid_for(None, R) is None)

# 다리: 예보 강수확률을 쓰고, 지금 비가 오면 최소 80
check("예보 POP 사용", b.engine_weather({"temperature": 15, "precip_prob": 40})["precip_prob"] == 40)
check("지금 비 → 80 이상", b.engine_weather({"temperature": 15, "precip_prob": 40, "precipitation_type": 1})["precip_prob"] == 80)
check("예보 없으면 실황", b.engine_weather({"temperature": 15})["precip_prob"] == 10)
print(f"{ok} ok, {fail} fail"); sys.exit(1 if fail else 0)
