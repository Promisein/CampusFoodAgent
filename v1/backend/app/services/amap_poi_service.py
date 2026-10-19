"""AMap POI API client and field normalization."""
import json
import time
from collections.abc import Callable
from typing import Any

import httpx

AMAP_POI_SEARCH_URL = "https://restapi.amap.com/v3/place/around"


class AmapPoiError(Exception):
    """AMap API related error."""


def _clean_text(value: Any) -> str | None:
    """Trim text values and convert empty/non-scalar values to None."""
    if value is None:
        return None
    if isinstance(value, (list, dict, tuple, set)):
        return None
    v = str(value).strip()
    return v if v else None


def _parse_location(location: Any) -> tuple[float | None, float | None]:
    """Parse AMap location field: 'longitude,latitude' -> (lon, lat)."""
    if not location:
        return None, None
    parts = str(location).split(",")
    if len(parts) != 2:
        return None, None
    try:
        lon = float(parts[0].strip())
        lat = float(parts[1].strip())
        return lon, lat
    except (ValueError, TypeError):
        return None, None


def normalize_amap_poi(poi: dict, campus: str = "清水河") -> dict:
    """Map raw AMap POI JSON to shops table fields."""
    lon, lat = _parse_location(poi.get("location", ""))
    poi_id = _clean_text(poi.get("id") or poi.get("poiid"))

    typecode = _clean_text(poi.get("typecode")) or ""
    tags_list = ["高德POI"]
    if typecode:
        tags_list.append(typecode)

    return {
        "poi_id": poi_id,
        "name": _clean_text(poi.get("name")),
        "campus": campus,
        "area": _clean_text(poi.get("business_area")) or _clean_text(poi.get("adname")) or "清水河周边",
        "address": _clean_text(poi.get("address")),
        "phone": _clean_text(poi.get("tel")),
        "category": _clean_text(poi.get("type")),
        "latitude": lat,
        "longitude": lon,
        "tags": json.dumps(tags_list, ensure_ascii=False),
        "tastes": json.dumps([], ensure_ascii=False),
        "scenes": json.dumps([], ensure_ascii=False),
        "image_urls": json.dumps([], ensure_ascii=False),
        "review_count": 0,
    }


def fetch_amap_poi_page(
    key: str,
    center: str,
    radius: int,
    page: int = 1,
    types: str = "050000",
    keywords: str = "",
    city: str = "成都",
    offset: int = 25,
    timeout: int = 15,
    max_retries: int = 1,
) -> dict:
    """Fetch one page from AMap around-search POI API."""
    params: dict[str, Any] = {
        "key": key,
        "location": center,
        "radius": radius,
        "types": types,
        "city": city,
        "offset": offset,
        "page": page,
        "extensions": "all",
        "output": "json",
    }
    if keywords:
        params["keywords"] = keywords

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(AMAP_POI_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            break
        except (httpx.HTTPError, ValueError) as e:
            last_error = e
        if attempt < max_retries:
            time.sleep(0.5)
    else:
        raise AmapPoiError(f"高德 API 请求失败: {last_error}")

    if data.get("status") != "1":
        raise AmapPoiError(
            f"高德 API 返回错误 status={data.get('status')} info={data.get('info', 'unknown')}"
        )

    return data


def fetch_all_amap_pois(
    key: str,
    center: str,
    radius: int = 4000,
    types: str = "050000",
    keywords: str = "",
    city: str = "成都",
    max_pages: int = 8,
    offset: int = 25,
    on_page: Callable[[int, list[dict]], None] | None = None,
) -> list[dict]:
    """Fetch multiple pages of raw POIs."""
    all_pois: list[dict] = []
    for page in range(1, max_pages + 1):
        data = fetch_amap_poi_page(
            key=key,
            center=center,
            radius=radius,
            page=page,
            types=types,
            keywords=keywords,
            city=city,
            offset=offset,
        )
        pois = data.get("pois") or []
        if on_page:
            on_page(page, pois)
        if not pois:
            break
        all_pois.extend(pois)
        if len(pois) < offset:
            break
        time.sleep(0.3)
    return all_pois
