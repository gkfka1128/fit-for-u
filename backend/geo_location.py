"""
브라우저 위치 → 기상청 격자. Streamlit 커스텀 컴포넌트(geo_component/index.html, 설치 없음) + kma_forecast.latlon_to_grid.
위치는 브라우저가 권한을 물어본 뒤에만 오고, 좌표는 격자 계산에만 쓰고 저장하지 않는다. localhost 또는 https 에서만 동작.

  loc = browser_location(key="geo")          # None | {"lat", "lon", "accuracy"} | {"error": "denied"|"unavailable"|"unsupported"}
  nx, ny, near = grid_for(loc, regions)      # regions = {"서울": (60, 127), …} → 가장 가까운 지역 이름도 같이
"""
import os

import streamlit.components.v1 as components

import kma_forecast

_component = components.declare_component("ffu_geolocation", path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_component"))


def browser_location(key="geo"):
    return _component(key=key, default=None)


def grid_for(loc, regions):
    """위치 → (nx, ny, 가장 가까운 지역). 위치가 없거나 국외면 None"""
    if not loc or "lat" not in loc: return None
    lat, lon = float(loc["lat"]), float(loc["lon"])
    if not kma_forecast.in_korea(lat, lon): return None
    nx, ny = kma_forecast.latlon_to_grid(lat, lon)
    near = min(regions, key=lambda r: (regions[r][0] - nx) ** 2 + (regions[r][1] - ny) ** 2) if regions else None
    return nx, ny, near
