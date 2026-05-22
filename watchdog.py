#!/usr/bin/env python3
"""Minimal health check: telegram_bot process + mihomo proxy node switching."""

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PROXY = "http://127.0.0.1:7890"
MIHOMO_API = "http://127.0.0.1:9090"
PROXY_PROBE = "https://www.baidu.com"
LOG_FILE = Path(__file__).resolve().parent / "watchdog.log"
STATE_FILE = Path(__file__).resolve().parent / "watchdog_state.json"
HEARTBEAT_FILE = Path(__file__).resolve().parent / "poll_heartbeat"
HEARTBEAT_MAX_AGE = 300  # 5 min = 3 missed heartbeats
PROXY_GROUPS = ["AI", "PROXY", "Proxy"]


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=True, sort_keys=True), encoding="utf-8")


def test_internet(timeout: int = 8) -> bool:
    try:
        with urllib.request.urlopen(PROXY_PROBE, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def test_mihomo(timeout: int = 8) -> bool:
    try:
        handler = urllib.request.ProxyHandler({"https": PROXY, "http": PROXY})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request("https://api.openai.com")
        with opener.open(req, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def telegram_bot_alive() -> bool:
    r = subprocess.run(["pgrep", "-f", "telegram_bot.py"], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def bot_polling_alive() -> bool:
    """Return False if the heartbeat file is stale (polling loop dead)."""
    try:
        age = time.time() - float(HEARTBEAT_FILE.read_text().strip())
        return age < HEARTBEAT_MAX_AGE
    except Exception:
        return True  # file missing = bot just started, give it time


def mihomo_get(path: str) -> dict:
    try:
        req = urllib.request.Request(f"{MIHOMO_API}{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def mihomo_put(path: str, data: dict) -> bool:
    try:
        req = urllib.request.Request(
            f"{MIHOMO_API}{path}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def switch_node() -> bool:
    all_proxies = mihomo_get("/proxies")
    proxies = all_proxies.get("proxies", {})
    for group_name in PROXY_GROUPS:
        if group_name not in proxies:
            continue
        group = proxies[group_name]
        current = group.get("now", "")
        members = [
            m
            for m in group.get("all", [])
            if m not in ("DIRECT", "REJECT", "COMPATIBLE", current)
            and not any(k in m for k in ["Traffic", "Expire", "G |", "流量", "重置", "过期"])
        ]
        if not members:
            continue
        try:
            idx = 0
            if current in group.get("all", []):
                idx = (group["all"].index(current) + 1) % len(members)
            next_node = members[idx % len(members)]
        except Exception:
            next_node = members[0]
        ok = mihomo_put(f"/proxies/{group_name}", {"name": next_node})
        log(f"switched {group_name}: {current} -> {next_node} ({'ok' if ok else 'fail'})")
        return True
    return False


def main() -> None:
    state = load_state()

    if not test_internet():
        log("direct internet probe failed - host is offline")
        return

    if not telegram_bot_alive():
        log("telegram_bot.py process missing - restarting bot-tg.service")
        subprocess.run(["systemctl", "restart", "bot-tg.service"], capture_output=True, text=True)
    elif not bot_polling_alive():
        log("poll heartbeat stale - polling loop dead, restarting bot-tg.service")
        subprocess.run(["systemctl", "restart", "bot-tg.service"], capture_output=True, text=True)
        HEARTBEAT_FILE.write_text(str(time.time()))  # reset so next check doesn't double-restart

    if not test_mihomo():
        log("mihomo proxy probe failed - switching node")
        switch_node()

    save_state(state)


if __name__ == "__main__":
    main()
