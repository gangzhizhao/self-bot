#!/usr/bin/env python3
"""inbox_scan.py — runs hourly, replies to letters from the user."""

import hashlib
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core

PROCESSED_FILE = Path(__file__).resolve().parent / "inbox_processed.json"
USER_ID = "<YOUR_TG_USER_ID>"
CHAT_KEY = "<YOUR_TG_USER_ID>"

# Random delay before replying — feels less instant, more like a real letter
MIN_REPLY_DELAY = 1800   # 30 min
MAX_REPLY_DELAY = 5400   # 90 min


def _msg_key(m: dict) -> str:
    mid = m.get("message_id", "").strip()
    if mid:
        return mid
    raw = m.get("from", "") + m.get("subject", "") + m.get("date", "")[:16]
    return hashlib.md5(raw.encode()).hexdigest()


def load_processed() -> dict:
    try:
        data = json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))
        # support old format (list of ids)
        if isinstance(data, list):
            return {k: 0 for k in data}
        return data
    except Exception:
        return {}


def save_processed(data: dict):
    PROCESSED_FILE.write_text(json.dumps(data), encoding="utf-8")


def reply_to_letter(m: dict):
    subj = m.get("subject", "")
    body = m.get("body", "").strip()
    date = m.get("date", "")
    message_id = m.get("message_id", "")
    in_reply_to = m.get("in_reply_to", "")

    # Build context: quoted letter + memories
    mem = core.get_memories(20, user_id=USER_ID)
    self_items = core.load_self_insights(user_id=USER_ID, token_budget=200)

    ctx_parts = []
    if mem:
        ctx_parts.append("## 你记住的事\n" + mem)
    if self_items:
        ctx_parts.append("## 你对自己的观察\n" + "\n".join("- " + s for s in self_items))

    # If this is a reply to a previous letter, note that
    thread_note = ""
    if in_reply_to:
        thread_note = "（这封信是对你之前某封信的回复。结合聊天记录理解上下文。）\n\n"

    ctx = "\n\n".join(ctx_parts)

    system = core.get_system_prompt(chat_id=CHAT_KEY, user_id=USER_ID)

    prompt = "\n".join([
        "你收到了一封信。",
        f"日期：{date}",
        f"主题：{subj}",
        thread_note,
        "信的内容：",
        body[:3000],
        "",
        ctx,
        "",
        "请回信。",
        "如果信里提到了某个地方或者链接，可以先用工具查一下，把查到的东西自然地写进信里。",
        "回信格式：",
        "第一行：Subject: （回信主题）",
        "空一行",
        "然后是信的正文——有开头，有内容，有结尾，有署名。",
        "白话文，朋友写信的语气，三到六段，有自己的观点和感受。",
        "只输出信的内容，不要输出其他说明。",
    ])

    msgs = [{"role": "user", "content": prompt}]
    result = core.call_deepseek(msgs, system, use_tools=True)
    if not result:
        result = core.call_minimax(msgs, system, use_tools=True)
    if not result:
        core.log("inbox_scan: reply generation failed")
        return

    lines = result.strip().splitlines()
    reply_subj = ("Re: " + subj) if not subj.lower().startswith("re:") else subj
    reply_body = result.strip()

    if lines and lines[0].lower().startswith("subject:"):
        reply_subj = lines[0][8:].strip()
        rest = lines[1:]
        while rest and not rest[0].strip():
            rest = rest[1:]
        reply_body = "\n".join(rest).strip()

    # Reply-to the original message for proper threading
    reply_to_id = message_id or in_reply_to or None
    ok = core.send_email(reply_subj, reply_body, in_reply_to=reply_to_id)
    core.log(f"inbox_scan: replied '{reply_subj}': {'ok' if ok else 'fail'}")

    if ok:
        core.append_history(CHAT_KEY, "user",
                            f"[来信] {subj}\n{body[:500]}", user_id=USER_ID)
        core.append_history(CHAT_KEY, "assistant", reply_body, user_id=USER_ID)


def main():
    user_email = core._env("EMAIL_TO", "").lower()
    if not user_email:
        core.log("inbox_scan: EMAIL_TO not set")
        return

    msgs = core.read_recent_emails(days=2, limit=30, mark_read=False)

    user_letters = [
        m for m in msgs
        if user_email in (m.get("from") or "").lower()
    ]

    if not user_letters:
        core.log("inbox_scan: no letters from user")
        return

    processed = load_processed()
    now = time.time()

    new_letters = []
    for m in user_letters:
        key = _msg_key(m)
        if key not in processed:
            new_letters.append((key, m))

    if not new_letters:
        core.log("inbox_scan: no unprocessed letters")
        return

    for key, m in new_letters[:3]:
        # Check if we're within the reply delay window
        queued_at = processed.get(key + "_queued", 0)
        if queued_at == 0:
            # First time seeing this letter — queue it with a random delay
            delay = random.randint(MIN_REPLY_DELAY, MAX_REPLY_DELAY)
            processed[key + "_queued"] = now + delay
            core.log(f"inbox_scan: queued '{m.get('subject', '')}', reply in {delay//60}min")
            save_processed(processed)
            continue

        if now < queued_at:
            mins_left = int((queued_at - now) / 60)
            core.log(f"inbox_scan: '{m.get('subject', '')}' waiting {mins_left}min before reply")
            continue

        # Delay passed — reply now
        core.log(f"inbox_scan: replying to '{m.get('subject', '')}' from {m.get('date', '')[:16]}")
        reply_to_letter(m)
        processed[key] = int(now)
        processed.pop(key + "_queued", None)

    save_processed(processed)


if __name__ == "__main__":
    main()
