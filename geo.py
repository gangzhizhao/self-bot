#!/usr/bin/env python3
"""AMap helpers extracted from core.py."""

from __future__ import annotations

import json
import os
import time
import urllib.request

from memory import log


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


AMAP_KEY = _env("AMAP_KEY")
AMAP_BASE = _env("AMAP_BASE", "https://restapi.amap.com")

_AMAP_CACHE: dict = {}
_AMAP_CACHE_TTL = 6 * 3600


def _amap_get(path: str, params: dict, timeout: int = 10) -> dict | None:
    try:
        params = {**params, "key": AMAP_KEY}
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{AMAP_BASE}{path}?{qs}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(url), timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"amap {path}: {e}")
        return None


def _cache_get(key: tuple):
    item = _AMAP_CACHE.get(key)
    if not item or time.time() - item["ts"] > _AMAP_CACHE_TTL:
        return None
    return item["v"]


def _cache_put(key: tuple, value):
    _AMAP_CACHE[key] = {"ts": time.time(), "v": value}


def _shape_pois(data: dict | None) -> list[dict]:
    if not data or data.get("status") == "0":
        return []
    out = []
    for p in (data.get("pois") or [])[:10]:
        if not isinstance(p, dict):
            continue
        biz = p.get("biz_ext") or {}
        if not isinstance(biz, dict):
            biz = {}
        out.append(
            {
                "name": str(p.get("name") or ""),
                "addr": str(p.get("address") or ""),
                "type": str(p.get("type") or "").split(";")[-1] if p.get("type") else "",
                "tel": str(p.get("tel") or ""),
                "loc": str(p.get("location") or ""),
                "dist": str(p.get("distance") or ""),
                "tags": str(p.get("atag") or "")[:80],
                "rating": str(biz.get("rating") or ""),
                "cost": str(biz.get("cost") or ""),
                "open": str(biz.get("open_time") or ""),
            }
        )
    return out


def amap_poi_keyword(keyword: str, city: str = "", offset: int = 5) -> list[dict]:
    if not keyword:
        return []
    key = ("kw", keyword, city, offset)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    data = _amap_get("/v3/place/text", {"keywords": keyword, "city": city, "offset": offset, "page": 1, "extensions": "all"})
    out = _shape_pois(data)
    _cache_put(key, out)
    return out


def amap_poi_around(keyword: str, lat: float, lon: float, radius: int = 2000, offset: int = 5) -> list[dict]:
    key = ("around", keyword, round(float(lat), 3), round(float(lon), 3), radius, offset)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    data = _amap_get("/v3/place/around", {"keywords": keyword or "", "location": f"{lon},{lat}", "radius": radius, "offset": offset, "extensions": "all"})
    out = _shape_pois(data)
    _cache_put(key, out)
    return out


def run_poi_query(query: dict) -> list[dict]:
    keyword = query.get("keyword", "").strip()
    if "around" in query:
        try:
            lat, lon = [float(x) for x in query["around"].split(",")[:2]]
        except Exception:
            return []
        radius = int(query.get("radius", "2000") or "2000")
        return amap_poi_around(keyword, lat, lon, radius)
    if "city" in query:
        return amap_poi_keyword(keyword, query["city"])
    return amap_poi_keyword(keyword, "")
