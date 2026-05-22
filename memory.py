#!/usr/bin/env python3
"""Memory/storage helpers extracted from core.py."""

from __future__ import annotations

import json
import os
import re
import ssl
import threading
import time
import urllib.request
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
HIST_DIR = BOT_DIR / 'history'
NOW_FILE = BOT_DIR / 'now.json'
LASTDAY_FILE = BOT_DIR / 'lastday.json'

SUPA_URL = os.environ.get('SUPABASE_URL', '')
SUPA_KEY = os.environ.get('SUPABASE_KEY', '')
_SH = {'apikey': SUPA_KEY, 'Authorization': f'Bearer {SUPA_KEY}', 'Content-Type': 'application/json'}

MAX_HISTORY = 80
TOKEN_BUDGET = 3500


def log(msg: str):
    import core as _core
    return _core.log(msg)


def normalize_user_id(user_id=None, chat_id=None) -> str:
    import core as _core
    return _core.normalize_user_id(user_id=user_id, chat_id=chat_id)


def estimate_tokens(text: str) -> int:
    import core as _core
    return _core.estimate_tokens(text)


def fetch_url_text(url: str, max_chars: int = 12000, timeout: int = 30) -> str:
    import core as _core
    return _core.fetch_url_text(url, max_chars=max_chars, timeout=timeout)


def _supa_ctx():
    return ssl.create_default_context()


def supa_insert(table: str, row: dict):
    try:
        req = urllib.request.Request(
            f"{SUPA_URL}/{table}",
            data=json.dumps(row).encode(),
            headers={**_SH, "Prefer": "return=minimal"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10, context=_supa_ctx())
    except Exception as e:
        log(f"supa {table}: {e}")


def supa_select(table: str, params: dict) -> list:
    try:
        url = f"{SUPA_URL}/{table}?" + "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(url, headers=_SH)
        with urllib.request.urlopen(req, timeout=10, context=_supa_ctx()) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"supa select {table}: {e}")
        return []


def supa_bg(table: str, row: dict):
    threading.Thread(target=supa_insert, args=(table, row), daemon=True).start()


def save_history(chat_id, items: list, user_id=None):
    HIST_DIR.mkdir(exist_ok=True)
    (HIST_DIR / f"{chat_id}.json").write_text(
        json.dumps(items[-MAX_HISTORY:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_history(chat_id, user_id=None) -> list:
    path = HIST_DIR / f"{chat_id}.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"load_history {chat_id}: {e}")
        return []

    out = []
    used = 0
    for row in reversed(rows):
        content = row.get("content", "")
        tok = estimate_tokens(content)
        if used + tok > TOKEN_BUDGET:
            break
        out.append(
            {
                "role": row.get("role", "user"),
                "content": content,
                "at": row.get("at", ""),
            }
        )
        used += tok
    return list(reversed(out))


def append_history(chat_id, role: str, content: str, user_id=None, meta: dict | None = None):
    items = load_history(chat_id, user_id=user_id)
    items.append(
        {
            "role": role,
            "content": content,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "meta": meta or {},
        }
    )
    save_history(chat_id, items, user_id=user_id)


def describe_last_gap(chat_id, user_id=None) -> str | None:
    history = load_history(chat_id, user_id=user_id)
    if not history:
        return None
    last_at = next((m.get("at", "") for m in reversed(history) if m.get("at")), "")
    if not last_at:
        return None
    try:
        stamp = last_at.replace("T", " ")[:19]
        last_ts = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None
    gap = int((time.time() - last_ts) / 60)
    if gap < 60:
        return f"{gap} min"
    if gap < 1440:
        return f"{gap // 60} h"
    return f"{gap // 1440} d"


def get_memories(n=30, user_id=None) -> str:
    uid = normalize_user_id(user_id=user_id)
    rows = supa_select("memories", {"select": "content,prefix,ts", "user_id": f"eq.{uid}", "order": "ts.asc", "limit": str(n)})
    return "\n".join(r.get("content", "") for r in rows if r.get("content"))


def recall_memories(query: str, n: int = 8, user_id=None) -> str:
    uid = normalize_user_id(user_id=user_id)
    q = (query or "").strip()
    if not q or not uid:
        return ""
    encoded = urllib.request.quote(q, safe="")
    rows = supa_select(
        "memories",
        {
            "select": "content,prefix,ts",
            "user_id": f"eq.{uid}",
            "content": f"ilike.*{encoded}*",
            "order": "ts.desc",
            "limit": str(n),
        },
    )
    return "\n".join(r.get("content", "") for r in rows if r.get("content"))


def list_pref_memories(user_id=None, limit: int = 8) -> list[str]:
    uid = normalize_user_id(user_id=user_id)
    rows = supa_select("memories", {"select": "content,prefix,ts", "user_id": f"eq.{uid}", "prefix": "eq.PREF", "order": "ts.desc", "limit": str(limit)})
    return [r.get("content", "").strip() for r in rows if r.get("content")]


def load_self_insights(user_id=None, token_budget: int = 300) -> list[str]:
    uid = normalize_user_id(user_id=user_id)
    rows = supa_select(
        "self_insights",
        {
            "select": "content,tokens_est,retired_at,ts",
            "user_id": f"eq.{uid}",
            "retired_at": "is.null",
            "order": "ts.desc",
            "limit": "50",
        },
    )
    out: list[str] = []
    used = 0
    for row in rows:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        tok = row.get("tokens_est") or estimate_tokens(content)
        if used + tok > token_budget:
            break
        out.append(content)
        used += tok
    return list(reversed(out))


def get_reference(n=5) -> str:
    rows = supa_select("reference", {"order": "id.desc", "limit": str(n)})
    return "\n".join(f"[{r.get('category', '')}] {r.get('content', '')}" for r in reversed(rows))


def add_reminder(time_str: str, date_str: str, content: str):
    supa_insert("reminders", {"time": time_str, "date": date_str, "content": content, "done": False})


def _load_now() -> dict:
    try:
        return json.loads(NOW_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_now(data: dict):
    NOW_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_now_activity(chat_id, activity: str):
    data = _load_now()
    if activity:
        data[str(chat_id)] = {"activity": activity, "since": int(time.time())}
    else:
        data.pop(str(chat_id), None)
    _save_now(data)


def get_now_activity(chat_id) -> tuple[str, int] | None:
    data = _load_now()
    item = data.get(str(chat_id))
    if not item:
        return None
    return item.get("activity", ""), item.get("since", 0)


def _load_lastday() -> dict:
    try:
        return json.loads(LASTDAY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_first_of_day(chat_id) -> bool:
    today = time.strftime("%Y-%m-%d")
    data = _load_lastday()
    prev = data.get(str(chat_id))
    if prev == today:
        return False
    data[str(chat_id)] = today
    LASTDAY_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return True


def get_user_location_memo(user_id=None) -> str | None:
    uid = normalize_user_id(user_id=user_id)
    rows = supa_select("memories", {"select": "content,prefix,ts", "user_id": f"eq.{uid}", "order": "ts.desc", "limit": "30"})
    for row in rows:
        content = row.get("content") or ""
        if "location" in content.lower() or "user location" in content.lower() or "geolocation" in content.lower():
            return content
    return None


def _ambient_weather_for(loc_memo: str) -> str | None:
    m = re.search(r"([\d.]+),([\d.]+)", loc_memo)
    if not m:
        return None
    lat, lon = m.group(1), m.group(2)
    try:
        return fetch_url_text(
            f"https://wttr.in/{lat},{lon}?format=%C+%t+%w&lang=zh&m",
            max_chars=80,
            timeout=8,
        ) or None
    except Exception:
        return None


def get_annual_alerts(user_id=None) -> list[tuple[int, str]]:
    uid = normalize_user_id(user_id=user_id)
    rows = supa_select("memories", {"select": "content,prefix,ts", "user_id": f"eq.{uid}", "order": "ts.desc", "limit": "300"})
    annuals = []
    for row in rows:
        prefix = row.get("prefix") or ""
        content = (row.get("content") or "").strip()
        if prefix.startswith("ANNUAL_") and len(prefix) == 11:
            annuals.append((prefix[-4:], content))
        else:
            m = re.match(r"\[ANNUAL_(\d{4})\]\s*(.*)", content)
            if m:
                annuals.append((m.group(1), m.group(2).strip()))
    out = []
    for days_ahead in (0, 1, 3, 7):
        future_mmdd = time.strftime("%m%d", time.localtime(time.time() + days_ahead * 86400))
        for mmdd, content in annuals:
            if mmdd == future_mmdd:
                out.append((days_ahead, content))
    return out


def pick_open_loop(user_id=None) -> str | None:
    uid = normalize_user_id(user_id=user_id)
    rows = supa_select("memories", {"select": "content,prefix,ts", "user_id": f"eq.{uid}", "prefix": "eq.LOOP_OPEN", "order": "ts.desc", "limit": "30"})
    for row in rows:
        content = (row.get("content") or "").strip()
        if content:
            return content
    return None
