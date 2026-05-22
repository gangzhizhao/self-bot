from pathlib import Path
#!/usr/bin/env python3
"""wakeup.py — cron-triggered, writes a letter when there's something worth saying."""

import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core

MIN_IDLE_HOURS = 24
FIRE_PROB = 0.4
MAX_JITTER_SEC = 600
USER_ID = core.OWNER_USER_ID


def get_idle_hours() -> float:
    log = core.BOT_DIR / "bot.log"
    if not log.exists():
        return 999
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            if "<<" in line or ">>" in line:
                ts = line[1:20]
                t = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
                return (time.time() - t) / 3600
    except Exception:
        pass
    return 999


def main():
    idle = get_idle_hours()
    if idle < MIN_IDLE_HOURS:
        print(f"Idle only {idle:.1f}h < {MIN_IDLE_HOURS}h, skip.")
        return

    if random.random() > FIRE_PROB:
        print(f"Random skip (prob {FIRE_PROB}).")
        return

    jitter = random.randint(0, MAX_JITTER_SEC)
    print(f"Sleep jitter {jitter}s...")
    time.sleep(jitter)

    idle = get_idle_hours()
    if idle < MIN_IDLE_HOURS:
        print(f"After jitter, idle dropped to {idle:.1f}h, abort.")
        return

    mem = core.get_memories(20, user_id=USER_ID)
    self_items = core.load_self_insights(user_id=USER_ID, token_budget=200)
    ref = core.get_reference(3)
    reading_rows = core.supa_select('memories', {'select': 'content,ts', 'user_id': f'eq.{USER_ID}', 'prefix': 'eq.READING', 'order': 'ts.desc', 'limit': '5'})
    reading_items = [r.get('content', '') for r in reading_rows if r.get('content')]

    ctx_parts = []
    if mem:
        ctx_parts.append(f"## Memories\n{mem}")
    if self_items:
        ctx_parts.append("## Self insights\n" + "\n".join(f"- {item}" for item in self_items))
    if ref:
        ctx_parts.append(f"## Reference\n{ref}")
    context = "\n\n".join(ctx_parts)

    system = core.get_system_prompt(chat_id=USER_ID, user_id=USER_ID)
    now = time.strftime("%Y-%m-%d %H:%M")

    prompt = f"""Now: {now}. You've been on your own for {idle:.1f} hours. No messages exchanged.

{context}

你和用户通过邮件往来。你可以选择：
- letter: 你有真正想说的东西，写一封信
- explore: 记录一条 [SELF: ...] 观察，不写信
- none: 什么都不做

只有真的有话说才选 letter，不是为了联系而联系。

如果选 letter，格式：
ACTION: letter
SUBJECT: （信的主题，一句话）
CONTENT:
（信的正文，有开头有结尾有署名，白话文，三到五段）

否则：
ACTION: explore/none
CONTENT: （explore 时写观察内容，none 时留空）"""

    result = core.run_chain(prompt, system)
    lines = result.strip().splitlines()

    action = ""
    subject = ""
    content_lines = []
    in_content = False

    for line in lines:
        if line.upper().startswith("ACTION:"):
            action = line.split(":", 1)[1].strip().lower()
        elif line.upper().startswith("SUBJECT:"):
            subject = line.split(":", 1)[1].strip()
        elif line.upper().startswith("CONTENT:"):
            in_content = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                content_lines.append(rest)
        elif in_content:
            content_lines.append(line)

    content = "\n".join(content_lines).strip()
    core.log(f"wakeup action={action} subject={subject[:40]}")

    if action == "letter" and content:
        subj = subject or "想到你"
        ok = core.send_email(subj, content)
        if ok:
            core.append_history(f"tg_{USER_ID}" if not USER_ID.startswith("tg_") else USER_ID,
                                "assistant", content, user_id=USER_ID)
            core.log(f"wakeup letter sent: {subj}")
        else:
            core.log("wakeup email failed")
    elif action == "explore" and content:
        core.process_markers(f"[SELF: {content}]", user_id=USER_ID)


if __name__ == "__main__":
    main()
