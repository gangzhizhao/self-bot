#!/usr/bin/env python3
"""Single-path v2 core backend."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = BOT_DIR / "prompts"
LOG_FILE = BOT_DIR / "bot.log"
MEDIA_DIR = BOT_DIR / "media"
HIST_DIR = BOT_DIR / "history"
AUTH_FILE = BOT_DIR / "auth.json"
NOW_FILE = BOT_DIR / "now.json"
LASTDAY_FILE = BOT_DIR / "lastday.json"

MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _load_bot_env():
    env_file = BOT_DIR / "bot.env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_bot_env()

import context as context_module
import cost_tracker as cost_tracker_module

from geo import (
    _amap_get,
    _cache_get,
    _cache_put,
    amap_poi_around,
    amap_poi_keyword,
    run_poi_query,
)
from media import (
    _chunk_bubble,
    _research_worker,
    _tts_lang,
    browse_url,
    call_vlm,
    call_vlm_cf,
    call_vlm_minimax,
    fetch_url_bytes,
    fetch_url_text,
    generate_image,
    generate_tts,
    read_recent_emails,
    send_email,
    web_search_review,
)
from memory import (
    _ambient_weather_for,
    add_reminder,
    append_history,
    describe_last_gap,
    get_annual_alerts,
    get_memories,
    get_now_activity,
    get_reference,
    get_user_location_memo,
    is_first_of_day,
    list_pref_memories,
    load_history,
    load_self_insights,
    pick_open_loop,
    recall_memories,
    save_history,
    set_now_activity,
    supa_bg,
    supa_insert,
    supa_select,
)
from models import (
    CLAUDE_SUBPROC_TIMEOUT,
    DASHSCOPE_BASE,
    DASHSCOPE_KEY,
    DASHSCOPE_MODEL,
    DEEPSEEK_BASE,
    DEEPSEEK_KEY,
    DEEPSEEK_MODEL,
    MINIMAX_BASE,
    MINIMAX_KEY,
    MINIMAX_TEXT_MODEL,
    TOOL_TIMEOUT,
    _http,
    _plain_call_with_continuation,
    _tls_chat_id,
    _tls_user_id,
    _to_messages,
    call_claude,
    call_deepseek,
    call_ds_research,
    call_minimax,
    call_qwen,
    call_tool_chain,
    run_chain,
    run_chain_with_source,
)
import tools as tools_module
from tools import *


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


OWNER_USER_ID = _env("OWNER_USER_ID")

LAST_SOURCE: dict = {}

_CTX = context_module.ContextBuilder(core_module=__import__(__name__))
_COST = cost_tracker_module.CostTracker(core_module=__import__(__name__))


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def normalize_user_id(user_id=None, chat_id=None) -> str:
    if user_id is not None:
        return str(user_id)
    if chat_id is not None:
        return str(chat_id)
    return "default"


def estimate_tokens(text: str) -> int:
    return cost_tracker_module.estimate_tokens(text)


def get_system_prompt(chat_id=None, user_id=None) -> str:
    uid = normalize_user_id(user_id=user_id, chat_id=chat_id)
    cid = str(chat_id if chat_id is not None else uid)
    return _CTX.build_system_prompt(user_id=uid, chat_id=cid)


def build_messages(chat_id, user_msg: str, user_id=None) -> list[dict]:
    uid = normalize_user_id(user_id=user_id, chat_id=chat_id)
    cid = str(chat_id if chat_id is not None else uid)
    return _CTX.build_history_messages(user_id=uid, chat_id=cid, user_msg=user_msg)


def build_prompt(chat_id, user_msg: str, user_id=None) -> str:
    msgs = build_messages(chat_id, user_msg, user_id=user_id)
    lines = []
    for msg in msgs[:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")
    lines.append(f"User: {msgs[-1]['content']}")
    return "\n".join(lines)


def get_reply(chat_id, user_msg: str, prefer_minimax=False) -> str:
    text, _ = get_reply_with_source(chat_id, user_msg, prefer_minimax)
    return text


def get_reply_with_source(chat_id, user_msg: str, prefer_minimax=False) -> tuple[str, str]:
    user_id = normalize_user_id(chat_id=chat_id)
    system = get_system_prompt(chat_id, user_id=user_id)
    messages = build_messages(chat_id, user_msg, user_id=user_id)
    text, source = run_chain_with_source(messages, system, prefer_minimax, user_id=user_id, chat_id=str(chat_id))
    LAST_SOURCE[chat_id] = source
    _COST.log_text_call(user_id, source if source != "mm" else MINIMAX_TEXT_MODEL, "chat", json.dumps(messages, ensure_ascii=False), text)
    return text, source


# ---------------------------------------------------------------------------
# Outbound push helpers
# ---------------------------------------------------------------------------

WECLAW_API = _env("WECLAW_URL", "http://127.0.0.1:18011/api/send")

# WeChat silently drops messages much beyond ~600 UTF-8 chars; stay well under.
MAX_WX_BUBBLE_CHARS = 480

# Lines that are pure decoration render as blank/empty bubbles in WeChat.
_WX_SEPARATOR_RE = re.compile(r"^[-_=*#~`|><.]+$")
_WX_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]")


def wx_push(target: str, text: str) -> bool:
    """Send a single message bubble to weclaw. Returns True on success."""
    if not target or not text:
        return False
    try:
        req = urllib.request.Request(
            WECLAW_API,
            data=json.dumps({"to": target, "text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log(f"wx_push: {e}")
        return False


def wx_push_bubbles(target: str, text: str, delay: float = 0.5) -> int:
    """Split text into bubbles and send sequentially. Returns count successfully sent.

    Filters separator-only lines (they render as empty bubbles in WeChat) and
    chunks any line that exceeds MAX_WX_BUBBLE_CHARS so weclaw never rejects it.
    """
    if not target or not text:
        return 0
    text = auto_split_sentences(text)
    bubbles: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _WX_SEPARATOR_RE.fullmatch(line):
            continue
        if not _WX_WORD_RE.search(line):
            continue
        bubbles.extend(_chunk_bubble(line))
    sent = 0
    for b in bubbles:
        if wx_push(target, b):
            sent += 1
        time.sleep(delay)
    return sent


# ---------------------------------------------------------------------------
# Background research
# ---------------------------------------------------------------------------

RESEARCH_TASKS_LOCK = threading.Lock()
RESEARCH_TASKS: dict[str, dict] = {}


def spawn_research(task: str, email: bool | str, target: str, user_id: str) -> str:
    """Kick off background research and return a task id."""
    task_id = f"r{int(time.time() * 1000) % 10_000_000:07d}"
    with RESEARCH_TASKS_LOCK:
        RESEARCH_TASKS[task_id] = {
            "task": task,
            "started": time.time(),
            "user_id": user_id,
            "email": bool(email),
        }
    threading.Thread(
        target=_research_worker,
        args=(task_id, task, email, target, user_id),
        daemon=True,
    ).start()
    log(f"research spawned id={task_id} email={email} task={task[:60]}")
    return task_id


def list_research_tasks() -> list[dict]:
    with RESEARCH_TASKS_LOCK:
        snapshot = list(RESEARCH_TASKS.items())
    now = time.time()
    return [
        {"id": tid, "task": info["task"], "elapsed": int(now - info["started"]), "email": info["email"]}
        for tid, info in snapshot
    ]
