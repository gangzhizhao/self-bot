from pathlib import Path
#!/usr/bin/env python3
"""reminder_check.py — runs every minute via systemd timer, checks Supabase reminders"""
import json, sys, time, urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parent))
import core
from telegram_bot import tg_push_segments


now_hm = time.strftime("%H:%M")
now_date = time.strftime("%Y-%m-%d")

rows = core.supa_select("reminders", {"done": "eq.false", "limit": "50"})
for row in rows:
    rid = row.get("id")
    r_time = row.get("time", "")
    r_date = row.get("date", "")
    r_content = row.get("content", "")

    if r_time != now_hm:
        continue
    if r_date not in ("every_day", now_date):
        continue

    if tg_push_segments(f"提醒：{r_content}", user_id=core.OWNER_USER_ID):
        core.log(f"reminder sent: {r_content}")
    else:
        core.log(f"reminder tg_push_segments failed: {r_content}")

    if r_date != "every_day":
        req = urllib.request.Request(
            f"{core.SUPA_URL}/reminders?id=eq.{rid}",
            data=json.dumps({"done": True}).encode(),
            headers={**core._SH, "Prefer": "return=minimal"},
            method="PATCH",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
