#!/usr/bin/env python3
"""Tool parsing and tool-call helpers extracted from core.py."""

from __future__ import annotations

import json
import re
import threading
import urllib.request

from memory import estimate_tokens, fetch_url_text, log, normalize_user_id, recall_memories, supa_bg

def run_poi_query(query: dict) -> list[dict]:
    import core as _core
    return _core.run_poi_query(query)


def send_email(subject: str, body: str, to: str | None = None) -> bool:
    import core as _core
    return _core.send_email(subject, body, to)


def spawn_research(task: str, email: bool | str, target: str, user_id: str) -> str:
    import core as _core
    return _core.spawn_research(task=task, email=email, target=target, user_id=user_id)


__all__ = [
    'process_markers',
    'parse_draw_segments',
    'parse_fetch_segments',
    'parse_browse_segments',

    'parse_email_segments',
    'parse_inbox_segments',
    'parse_tool_segments',
    'parse_research_segments',
    'parse_recall_segments',
    'parse_poi_segments',
    'parse_voice_segments',
    'sanitize',
    'auto_split_sentences',
    '_http',
    '_TOOL_TLS',
    '_tls_user_id',
    '_tls_chat_id',
    'TOOLS_OAI',
    'TOOLS_NO_RESEARCH',
    '_exec_tool',
    '_tool_call_loop',
]

def process_markers(text: str, user_id=None) -> str:
    uid = normalize_user_id(user_id=user_id)

    def _memo(content):
        content = content.strip()
        if not content:
            return ""
        prefix = None
        stored = content
        m = re.match(r"\[([A-Z0-9_]+)\]\s*(.*)", content)
        if m:
            prefix = m.group(1)
            stored = m.group(2).strip()
        supa_bg("memories", {"user_id": uid, "content": stored, "prefix": prefix})
        return ""

    def _self(content):
        content = content.strip()
        if not content:
            return ""
        supa_bg("self_insights", {"user_id": uid, "content": content, "tokens_est": estimate_tokens(content)})
        return ""

    text = re.sub(r"\[MEMO:\s*([^\]]{1,500})\]", lambda m: _memo(m.group(1)), text)
    text = re.sub(r"\[DIARY:\s*([^\]]{1,500})\]", lambda m: _memo(m.group(1)), text)
    text = re.sub(r"\[SELF:\s*([^\]]{1,500})\]", lambda m: _self(m.group(1)), text)
    return text.strip()

def parse_draw_segments(text: str) -> tuple[str, list[str]]:
    pattern = re.compile(r"\[DRAW:\s*(.*?)\]", re.DOTALL | re.IGNORECASE)
    prompts = [m.group(1).strip() for m in pattern.finditer(text)]
    return pattern.sub("", text).strip(), prompts

def parse_fetch_segments(text: str) -> tuple[str, list[str]]:
    pattern = re.compile(r"\[FETCH:\s*(\S+?)\s*\]", re.IGNORECASE)
    urls = [m.group(1).strip() for m in pattern.finditer(text)]
    return pattern.sub("", text).strip(), urls

def parse_browse_segments(text: str) -> tuple[str, list[str]]:
    pattern = re.compile(r"\[BROWSE:\s*(\S+?)\s*\]", re.IGNORECASE)
    urls = [m.group(1).strip() for m in pattern.finditer(text)]
    return pattern.sub("", text).strip(), urls


_EMAIL_BLOCK_RE = re.compile(
    r"\[EMAIL_START\]\s*"
    r"(?:Subject|主题|标题)\s*[:：]\s*(?P<subj>.+?)\s*\n"
    r"(?:Body|正文|内容)\s*[:：]\s*(?P<body>[\s\S]+?)\s*"
    r"\[EMAIL_END\]",
    re.IGNORECASE,
)

_EMAIL_LEGACY_RE = re.compile(
    r"\[EMAIL:\s*(.+?)\s*\|\|\s*([\s\S]+?)(?:\]|\Z)", re.DOTALL | re.IGNORECASE
)

def parse_email_segments(text: str) -> tuple[str, list[tuple[str, str]]]:
    items: list[tuple[str, str]] = []
    for match in _EMAIL_BLOCK_RE.finditer(text):
        items.append((match.group("subj").strip(), match.group("body").strip()))
    cleaned = _EMAIL_BLOCK_RE.sub("", text).strip()
    for match in _EMAIL_LEGACY_RE.finditer(cleaned):
        items.append((match.group(1).strip(), match.group(2).strip()))
    cleaned = _EMAIL_LEGACY_RE.sub("", cleaned).strip()
    return cleaned, items

def parse_inbox_segments(text: str) -> tuple[str, int]:
    pattern = re.compile(r"\[INBOX(?:\s+(\d+))?\]", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if not matches:
        return text, 0
    days = max((int(m.group(1)) if m.group(1) else 7) for m in matches)
    return pattern.sub("", text).strip(), days

def parse_tool_segments(text: str) -> tuple[str, list[str]]:
    pattern = re.compile(r"\[TOOL:\s*(.+?)\]", re.DOTALL | re.IGNORECASE)
    prompts = [m.group(1).strip() for m in pattern.finditer(text)]
    return pattern.sub("", text).strip(), prompts

def parse_research_segments(text: str) -> tuple[str, list[dict]]:
    """Parse [RESEARCH: task | email_when_done] markers.

    Examples:
        [RESEARCH: 广州周末两小时高铁可达地点]
        [RESEARCH: GPT-5 发布时间 | email]
        [RESEARCH: ... | email=Subject Override]

    Returns cleaned text and list of {"task": str, "email": bool|str}.
    """
    pattern = re.compile(r"\[RESEARCH:\s*(.+?)\]", re.DOTALL | re.IGNORECASE)
    items: list[dict] = []
    for m in pattern.finditer(text):
        body = m.group(1).strip()
        email_flag: bool | str = False
        if "|" in body:
            task, _, opts = body.partition("|")
            task = task.strip()
            opts = opts.strip()
            if opts.lower().startswith("email"):
                if "=" in opts:
                    email_flag = opts.split("=", 1)[1].strip() or True
                else:
                    email_flag = True
        else:
            task = body
        if task:
            items.append({"task": task, "email": email_flag})
    return pattern.sub("", text).strip(), items

def parse_recall_segments(text: str) -> tuple[str, list[str]]:
    pattern = re.compile(r"\[RECALL:\s*(.+?)\]", re.DOTALL | re.IGNORECASE)
    queries = [m.group(1).strip() for m in pattern.finditer(text)]
    return pattern.sub("", text).strip(), queries

def parse_poi_segments(text: str) -> tuple[str, list[dict]]:
    pattern = re.compile(r"\[POI:\s*(.+?)\]", re.DOTALL | re.IGNORECASE)
    queries = []
    for m in pattern.finditer(text):
        body = m.group(1).strip()
        params = {}
        for kv in body.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k.strip()] = v.strip()
        if params:
            queries.append(params)
    return pattern.sub("", text).strip(), queries

def parse_voice_segments(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"\[voice:\s*(.*?)\]", re.DOTALL | re.IGNORECASE)
    segments = []
    last = 0
    for match in pattern.finditer(text):
        if match.start() > last:
            segments.append(("text", text[last:match.start()].strip()))
        segments.append(("voice", match.group(1).strip()))
        last = match.end()
    if last < len(text):
        segments.append(("text", text[last:].strip()))
    return [(kind, content) for kind, content in segments if content]

_XML_TRACE_PATTERNS = [
    r"<\s*antml:function_calls\s*>[\s\S]*?<\s*/\s*antml:function_calls\s*>",
    r"<\s*function_calls\s*>[\s\S]*?<\s*/\s*function_calls\s*>",
    r"<\s*antml:invoke\b[^>]*>[\s\S]*?<\s*/\s*antml:invoke\s*>",
    r"<\s*invoke\b[^>]*>[\s\S]*?<\s*/\s*invoke\s*>",
    r"<\s*antml:parameter\b[^>]*>[\s\S]*?<\s*/\s*antml:parameter\s*>",
    r"<\s*parameter\b[^>]*>[\s\S]*?<\s*/\s*parameter\s*>",
    r"<\s*tool_use\s*>[\s\S]*?<\s*/\s*tool_use\s*>",
    r"<\s*tool_call\s*>[\s\S]*?<\s*/\s*tool_call\s*>",
    r"<\s*tool_calls\s*>[\s\S]*?<\s*/\s*tool_calls\s*>",
    r"<\s*tool_result\s*>[\s\S]*?<\s*/\s*tool_result\s*>",
    r"<\s*thinking\s*>[\s\S]*?<\s*/\s*thinking\s*>",
    r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>",
]

_XML_TRACE_RE = re.compile("|".join(f"(?:{p})" for p in _XML_TRACE_PATTERNS), re.IGNORECASE)

_XML_STRAY_RE = re.compile(
    r"<\s*/?\s*(?:antml:)?(?:function_calls|invoke|parameter|tool_use|tool_call|tool_calls|tool_result|thinking|think)"
    r"(?:\s+[^>]*)?\s*/?\s*>",
    re.IGNORECASE,
)

_PROTECT_MARKERS = re.compile(
    r"\[EMAIL_START\][\s\S]*?\[EMAIL_END\]"
    r"|\[(?:RESEARCH|TOOL|FETCH|BROWSE|POI|RECALL|INBOX|DRAW|MEMO|SELF|DIARY)\b[^\]]*\]",
    re.IGNORECASE,
)

def sanitize(text: str) -> str:
    t = text or ""

    # 1. Strip XML/tool-call traces first (these never belong in the visible reply)
    t = _XML_TRACE_RE.sub("", t)
    t = _XML_STRAY_RE.sub("", t)

    # 2. Protect functional markers so the markdown-cleanup pass below does not
    #    accidentally eat an [EMAIL_START]…[EMAIL_END] block that the model
    #    wrapped in a fenced code block.
    placeholders: list[str] = []

    def _stash(match: re.Match) -> str:
        placeholders.append(match.group(0))
        return f"\x00MARK{len(placeholders) - 1}\x00"

    t = _PROTECT_MARKERS.sub(_stash, t)

    # 3. Markdown cleanup — fenced code blocks, headers, inline code
    t = re.sub(r"```.*?```", "", t, flags=re.DOTALL)
    t = re.sub(r"(?m)^#{1,6}\s+", "", t)
    t = re.sub(r"`([^`\n]+)`", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)

    # 4. Restore markers
    for i, blk in enumerate(placeholders):
        t = t.replace(f"\x00MARK{i}\x00", blk)

    return t.strip() or "(empty)"

def auto_split_sentences(text: str, min_sentences: int = 2) -> str:
    if "\n" in text:
        return text
    enders = re.findall(r"[。！？.!?]", text)
    if len(enders) < min_sentences:
        return text
    parts = re.split(r"([。！？.!?])", text)
    out = []
    buf = ""
    for i, part in enumerate(parts):
        buf += part
        if part in "。！？.!?":
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return "\n".join(out)

def _http(url, data, headers, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

_TOOL_TLS = threading.local()

def _tls_user_id() -> str:
    return getattr(_TOOL_TLS, "user_id", "") or normalize_user_id()

def _tls_chat_id() -> str:
    return getattr(_TOOL_TLS, "chat_id", "") or _tls_user_id()

TOOLS_OAI = [
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and return the readable text content of an HTTP(S) URL. Use for getting webpage content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL starting with http:// or https://"},
                    "max_chars": {"type": "integer", "description": "Max characters to return", "default": 8000},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_poi",
            "description": "Look up places (restaurants, attractions, services) via AMap. Either by city or by lat/lon proximity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search keyword, e.g. '咖啡馆'"},
                    "city": {"type": "string", "description": "Optional city name, e.g. '广州'"},
                    "around": {"type": "string", "description": "Optional 'lat,lon' pair, e.g. '23.09,113.32'"},
                    "radius": {"type": "integer", "description": "Optional radius in meters when around is set", "default": 2000},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email to the user's registered address. Use when the user asks 'email me' or '发邮件'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Markdown or plain text"},
                },
                "required": ["subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Search the user's stored memories for content matching a query. Returns matching MEMO records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research",
            "description": (
                "Spawn a background research task that runs a tool-using sub-agent (web search + multi-step reasoning). "
                "Returns immediately with a confirmation; results are pushed to the user separately via wx + email. "
                "Use for open-ended 'research / 调研' asks where multiple lookups are needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What to research"},
                    "email": {"type": "boolean", "description": "Whether to also email the result", "default": True},
                },
                "required": ["task"],
            },
        },
    },
]

TOOLS_NO_RESEARCH = [t for t in TOOLS_OAI if t["function"]["name"] != "research"]

def _exec_tool(name: str, args: dict) -> str:
    """Dispatch a single tool call. Always returns a string the model can read."""
    try:
        if name == "fetch_url":
            url = (args.get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                return f"error: url must start with http:// or https://, got {url[:80]}"
            n = int(args.get("max_chars") or 8000)
            page = fetch_url_text(url, max_chars=n) or ""
            return page or "(fetched empty)"
        if name == "search_poi":
            q = {"keyword": args.get("keyword") or ""}
            if args.get("city"):
                q["city"] = args["city"]
            if args.get("around"):
                q["around"] = args["around"]
            if args.get("radius"):
                q["radius"] = str(args["radius"])
            results = run_poi_query(q)
            return json.dumps(results, ensure_ascii=False)[:6000]
        if name == "send_email":
            subj = (args.get("subject") or "(no subject)").strip()
            body = (args.get("body") or "").strip()
            ok = send_email(subj, body, None)
            return "ok" if ok else "fail"
        if name == "recall_memory":
            q = (args.get("query") or "").strip()
            n = int(args.get("limit") or 8)
            uid = _tls_user_id()
            return recall_memories(q, n, uid) or "(no matches)"
        if name == "research":
            task = (args.get("task") or "").strip()
            if not task:
                return "error: empty task"
            should_email = bool(args.get("email", True))
            target = OWNER_WX_TARGET
            uid = _tls_user_id()
            if not target:
                return "error: no wx target"
            spawn_research(task=task, email=should_email, target=target, user_id=uid)
            return f"started: {task[:60]}"
        return f"error: unknown tool {name}"
    except Exception as e:
        log(f"_exec_tool {name}: {e}")
        return f"error: {e}"

def _tool_call_loop(api_url: str, api_key: str, model: str, system: str,
                    messages: list[dict], max_iters: int = 6, tools: list | None = None) -> str | None:
    """Generic OpenAI-compatible tool-call loop. Used by DeepSeek / Qwen / MiniMax."""
    base: list[dict] = [{"role": "system", "content": system}] + messages
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    accumulated = ""
    for _ in range(max_iters):
        try:
            data = _http(
                api_url,
                {"model": model, "messages": base, "tools": (tools or TOOLS_OAI), "tool_choice": "auto", "max_tokens": 4096},
                headers,
                timeout=60,
            )
        except Exception as e:
            log(f"tool-loop {model}: {e}")
            return None
        choices = data.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
            full = accumulated + content
            if choice.get("finish_reason") == "length" and content:
                accumulated = full
                base.append({"role": "assistant", "content": content})
                base.append({"role": "user", "content": "请继续。"})
                continue
            return full or None

        # Append the assistant turn that emitted the tool calls, then run each.
        base.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
        })
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            result = _exec_tool(name, args)
            base.append({
                "role": "tool",
                "tool_call_id": tc.get("id") or "",
                "name": name,
                "content": result[:6000],
            })
    log(f"tool-loop {model}: max iters reached")
    return None
