#!/usr/bin/env python3
"""Model-call helpers extracted from core.py."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

from memory import log, normalize_user_id
from tools import TOOLS_NO_RESEARCH, _tool_call_loop, _TOOL_TLS, sanitize


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


DEEPSEEK_KEY = _env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE = _env("DEEPSEEK_BASE", "https://api.deepseek.com")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")

MINIMAX_KEY = _env("MINIMAX_KEY")
MINIMAX_BASE = _env("MINIMAX_BASE", "https://api.minimax.chat")
MINIMAX_TEXT_MODEL = "MiniMax-M2.7"

DASHSCOPE_KEY = _env("DASHSCOPE_API_KEY")
DASHSCOPE_BASE = _env("DASHSCOPE_BASE", "https://dashscope.aliyuncs.com/compatible-mode")
DASHSCOPE_MODEL = _env("DASHSCOPE_MODEL", "qwen-plus")

CLAUDE_SUBPROC_TIMEOUT = int(_env("CLAUDE_SUBPROC_TIMEOUT", "180"))
TOOL_TIMEOUT = int(_env("TOOL_TIMEOUT", "240"))


def _http(url, data, headers, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _tls_user_id() -> str:
    return getattr(_TOOL_TLS, "user_id", "") or normalize_user_id()


def _tls_chat_id() -> str:
    return getattr(_TOOL_TLS, "chat_id", "") or _tls_user_id()


def _plain_call_with_continuation(api_url, api_key, model, system_msg, msgs, max_tokens=4096, timeout=60):
    """Plain (no-tools) call that auto-continues when finish_reason='length'."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    full_text = ""
    cur_msgs = [{"role": "system", "content": system_msg}] + list(msgs)
    for _ in range(3):
        try:
            data = _http(api_url, {"model": model, "messages": cur_msgs, "max_tokens": max_tokens}, headers, timeout=timeout)
        except Exception as e:
            log(f"_plain_call {model}: {e}")
            break
        choices = data.get("choices") or []
        if not choices:
            break
        choice = choices[0]
        msg = choice.get("message") or {}
        content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
        full_text += content
        if choice.get("finish_reason") != "length":
            break
        cur_msgs = cur_msgs + [{"role": "assistant", "content": content}, {"role": "user", "content": "请继续。"}]
    return full_text or None


def _to_messages(prompt) -> list[dict]:
    if isinstance(prompt, list):
        return prompt
    return [{"role": "user", "content": str(prompt)}]


_RESEARCH_SYSTEM = (
    "你是专注的搜索员，只用中文回答。"
    "使用 fetch_url 抓取网页，整合信息后输出文档列表。"
)


def call_deepseek(prompt, system: str, use_tools: bool = True) -> str | None:
    if not DEEPSEEK_KEY:
        return None
    try:
        msgs = _to_messages(prompt)
        if use_tools:
            text = _tool_call_loop(
                f"{DEEPSEEK_BASE}/chat/completions",
                DEEPSEEK_KEY,
                DEEPSEEK_MODEL,
                system,
                msgs,
            )
            if text:
                return sanitize(text)
        content = _plain_call_with_continuation(f"{DEEPSEEK_BASE}/chat/completions", DEEPSEEK_KEY, DEEPSEEK_MODEL, system, msgs)
        return sanitize(content) if content else None
    except Exception as e:
        log(f"deepseek: {e}")
        return None


def call_minimax(prompt, system: str, use_tools: bool = True) -> str | None:
    if not MINIMAX_KEY:
        return None
    try:
        msgs = _to_messages(prompt)
        if use_tools:
            text = _tool_call_loop(
                f"{MINIMAX_BASE}/v1/text/chatcompletion_v2",
                MINIMAX_KEY,
                MINIMAX_TEXT_MODEL,
                system,
                msgs,
            )
            if text:
                return sanitize(text)
        content = _plain_call_with_continuation(f"{MINIMAX_BASE}/v1/text/chatcompletion_v2", MINIMAX_KEY, MINIMAX_TEXT_MODEL, system, msgs)
        return sanitize(content) if content else None
    except Exception as e:
        log(f"minimax: {e}")
        return None


def call_qwen(prompt, system: str, use_tools: bool = True) -> str | None:
    """DashScope Qwen via OpenAI-compatible endpoint."""
    if not DASHSCOPE_KEY:
        return None
    try:
        msgs = _to_messages(prompt)
        if use_tools:
            text = _tool_call_loop(
                f"{DASHSCOPE_BASE}/v1/chat/completions",
                DASHSCOPE_KEY,
                DASHSCOPE_MODEL,
                system,
                msgs,
            )
            if text:
                return sanitize(text)
        content = _plain_call_with_continuation(f"{DASHSCOPE_BASE}/v1/chat/completions", DASHSCOPE_KEY, DASHSCOPE_MODEL, system, msgs)
        return sanitize(content) if content else None
    except Exception as e:
        log(f"qwen: {e}")
        return None


def call_ds_research(task: str) -> tuple[str | None, str]:
    """Use DeepSeek or Qwen with fetch_url (no research tool) for background tasks."""
    msgs = _to_messages(task)
    if DEEPSEEK_KEY:
        text = _tool_call_loop(
            f"{DEEPSEEK_BASE}/chat/completions",
            DEEPSEEK_KEY,
            DEEPSEEK_MODEL,
            _RESEARCH_SYSTEM,
            msgs,
            max_iters=6,
            tools=TOOLS_NO_RESEARCH,
        )
        if text:
            return sanitize(text), "ds"
    if DASHSCOPE_KEY:
        text = _tool_call_loop(
            f"{DASHSCOPE_BASE}/v1/chat/completions",
            DASHSCOPE_KEY,
            DASHSCOPE_MODEL,
            _RESEARCH_SYSTEM,
            msgs,
            max_iters=6,
            tools=TOOLS_NO_RESEARCH,
        )
        if text:
            return sanitize(text), "qw"
    return None, "none"


def _claude_script(script: str, prompt: str, timeout: int | None = None) -> str | None:
    if timeout is None:
        timeout = CLAUDE_SUBPROC_TIMEOUT
    try:
        r = subprocess.run(
            [script, "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        text = sanitize(r.stdout.strip())
        return text if text and text != "(empty)" else None
    except Exception as e:
        log(f"{script}: {e}")
        return None


def call_claude(prompt: str, timeout: int | None = None) -> str | None:
    return _claude_script(str(Path(__file__).resolve().parent / "claude.sh"), prompt, timeout=timeout)



def call_tool_chain(prompt: str, timeout: int | None = None) -> tuple[str | None, str]:
    result, src2 = call_ds_research(prompt)
    if result:
        return result, src2
    return None, "none"


def run_chain_with_source(prompt, system: str, prefer_minimax=False, user_id: str | None = None, chat_id: str | None = None) -> tuple[str, str]:
    if user_id:
        _TOOL_TLS.user_id = user_id
    if chat_id:
        _TOOL_TLS.chat_id = chat_id
    api_order = [("ds", call_deepseek), ("mm", call_minimax)]
    if prefer_minimax:
        api_order = [("mm", call_minimax), ("ds", call_deepseek)]
    for label, fn in api_order:
        result = fn(prompt, system)
        if result:
            return result, label
    result = call_qwen(prompt, system)
    if result:
        return result, "qw"
    return "(empty)", "none"


def run_chain(prompt, system: str, prefer_minimax=False) -> str:
    text, _ = run_chain_with_source(prompt, system, prefer_minimax)
    return text


__all__ = [
    "CLAUDE_SUBPROC_TIMEOUT",
    "DASHSCOPE_BASE",
    "DASHSCOPE_KEY",
    "DASHSCOPE_MODEL",
    "DEEPSEEK_BASE",
    "DEEPSEEK_KEY",
    "DEEPSEEK_MODEL",
    "MINIMAX_BASE",
    "MINIMAX_KEY",
    "MINIMAX_TEXT_MODEL",
    "TOOL_TIMEOUT",
    "_http",
    "_plain_call_with_continuation",
    "_tls_chat_id",
    "_tls_user_id",
    "_to_messages",
    "call_claude",
    "call_deepseek",
    "call_ds_research",
    "call_minimax",
    "call_qwen",
    "call_tool_chain",
    "run_chain",
    "run_chain_with_source",
]
