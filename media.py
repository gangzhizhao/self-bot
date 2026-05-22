#!/usr/bin/env python3
"""Media, web, mail, and background research helpers extracted from core.py."""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import subprocess
import time
import urllib.request
from html import unescape

from memory import log
from models import MINIMAX_BASE, MINIMAX_KEY, TOOL_TIMEOUT, _http, call_ds_research, call_tool_chain
from tools import parse_email_segments, process_markers, sanitize


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


PROXY = _env("PROXY_URL", "http://127.0.0.1:7890")
MINIMAX_TTS_MODEL = "speech-02-turbo"
MINIMAX_VLM_MODEL = "abab6.5s-chat"
MINIMAX_IMG_MODEL = "image-01"
TTS_VOICE_ZH = "Chinese (Mandarin)_Gentleman"
TTS_VOICE_EN = "moss_audio_cedfd4d2-736d-11f0-99be-fe40dd2a5fe8"
TTS_VOICE_JA = "Japanese_IntellectualSenior"

EMAIL_HOST = _env("EMAIL_HOST", "smtp.163.com")
EMAIL_PORT = int(_env("EMAIL_PORT", "465"))
EMAIL_FROM = _env("EMAIL_FROM")
EMAIL_PASS = _env("EMAIL_PASS")
EMAIL_TO = _env("EMAIL_TO")

CF_RELAY_URL = _env("CF_RELAY_URL", "")
CF_RELAY_TOKEN = _env("CF_RELAY_TOKEN")
CF_VLM_MODEL = "claude-haiku-4-5-20251001"


def _chunk_bubble(text: str) -> list[str]:
    """Split a long string into chunks <= 480 chars."""
    max_chars = 480
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while len(text) > max_chars:
        cut = -1
        for delim in ("\u3002", "\uff01", "\uff1f", "\uff01", "\uff1f", ". ", " "):
            pos = text.rfind(delim, 0, max_chars)
            if pos > 0:
                cut = pos + len(delim)
                break
        if cut <= 0:
            cut = max_chars
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return [c for c in chunks if c]


def _tts_lang(text: str) -> str:
    ja = sum(1 for ch in text if '぀' <= ch <= 'ヿ')
    if ja > len(text) * 0.1:
        return "ja"
    cjk = sum(1 for ch in text if ord(ch) > 127)
    return "zh" if cjk > len(text) * 0.15 else "en"


def generate_tts(text: str) -> bytes | None:
    lang = _tts_lang(text)
    voice = {"zh": TTS_VOICE_ZH, "en": TTS_VOICE_EN, "ja": TTS_VOICE_JA}.get(lang, TTS_VOICE_EN)
    try:
        data = _http(
            f"{MINIMAX_BASE}/v1/t2a_v2",
            {
                "model": MINIMAX_TTS_MODEL,
                "text": text,
                "voice_setting": {"voice_id": voice, "speed": 1.0, "vol": 1.0, "pitch": 0},
                "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
            },
            {"Authorization": f"Bearer {MINIMAX_KEY}", "Content-Type": "application/json"},
        )
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            log(f"tts: empty audio in response, data={str(data.get('data', {}))[:120]}")
            return None
        return bytes.fromhex(audio_hex)
    except Exception as e:
        log(f"tts: {e}")
        return None


def call_vlm_minimax(image_bytes: bytes, user_text: str = "") -> str:
    b64 = base64.b64encode(image_bytes).decode()
    question = user_text.strip() or "Describe the image."
    try:
        data = _http(
            f"{MINIMAX_BASE}/v1/text/chatcompletion_v2",
            {
                "model": MINIMAX_VLM_MODEL,
                "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}, {"type": "text", "text": question}]}],
                "max_tokens": 800,
            },
            {"Authorization": f"Bearer {MINIMAX_KEY}", "Content-Type": "application/json"},
            timeout=30,
        )
        if data.get("choices"):
            content = (data["choices"][0]["message"].get("content") or "").strip()
            if content:
                return sanitize(content)
    except Exception as e:
        log(f"vlm minimax: {e}")
    return ""


def call_vlm_cf(image_bytes: bytes, user_text: str = "") -> str:
    b64 = base64.b64encode(image_bytes).decode()
    question = user_text.strip() or "Describe the image."
    try:
        req = urllib.request.Request(
            f"{CF_RELAY_URL}/v1/messages",
            data=json.dumps(
                {
                    "model": CF_VLM_MODEL,
                    "max_tokens": 800,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": question},
                                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                            ],
                        }
                    ],
                }
            ).encode(),
            headers={"Authorization": f"Bearer {CF_RELAY_TOKEN}", "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        if data.get("content"):
            txt = "".join(c.get("text", "") for c in data["content"] if c.get("type") == "text").strip()
            if txt:
                return sanitize(txt)
    except Exception as e:
        log(f"vlm cf: {e}")
    return ""


def call_vlm(image_bytes: bytes, user_text: str = "", provider: str = "minimax") -> str:
    provider = (provider or "minimax").lower().strip()
    if provider == "cf":
        return call_vlm_cf(image_bytes, user_text)
    return call_vlm_minimax(image_bytes, user_text)


def generate_image(prompt: str, aspect_ratio: str = "1:1") -> str | None:
    try:
        data = _http(
            f"{MINIMAX_BASE}/v1/image_generation",
            {"model": MINIMAX_IMG_MODEL, "prompt": prompt, "n": 1, "aspect_ratio": aspect_ratio, "prompt_optimizer": True},
            {"Authorization": f"Bearer {MINIMAX_KEY}", "Content-Type": "application/json"},
            timeout=60,
        )
        urls = (data.get("data") or {}).get("image_urls") or []
        return urls[0] if urls else None
    except Exception as e:
        log(f"image-gen: {e}")
        return None


def fetch_url_bytes(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        log(f"fetch bytes: {e}")
        return None


def fetch_url_text(url: str, max_chars: int = 12000, timeout: int = 30) -> str:
    raw_html = ""
    try:
        from curl_cffi import requests as cc_requests

        r = cc_requests.get(url, impersonate="chrome120", proxies={"http": PROXY, "https": PROXY}, timeout=timeout)
        if r.status_code < 400 and r.text:
            raw_html = r.text
    except Exception as e:
        log(f"fetch curl_cffi: {e}")

    if not raw_html:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
            with opener.open(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read(8 * 1024 * 1024)
            enc = "utf-8"
            m = re.search(r"charset=([\w-]+)", ctype, re.I)
            if m:
                enc = m.group(1)
            try:
                raw_html = data.decode(enc, errors="replace")
            except Exception:
                raw_html = data.decode("utf-8", errors="replace")
        except Exception as e:
            log(f"fetch urllib: {e}")

    if not raw_html:
        return ""

    try:
        import trafilatura

        text = trafilatura.extract(raw_html, output_format="markdown", include_links=False, include_tables=True, favor_recall=True)
        if text and text.strip():
            return text.strip()[:max_chars]
    except Exception as e:
        log(f"trafilatura: {e}")

    text = raw_html
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", " ", text, flags=re.I)
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*(p|div|li|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f]+", " ", text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text).strip()
    return text[:max_chars]


def browse_url(url: str, max_chars: int = 12000, timeout: int = 60) -> str:
    try:
        result = subprocess.run(["python3", str(Path(__file__).resolve().parent / "browse.py"), url, str(max_chars)], capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip()
        log(f"browse rc={result.returncode}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log(f"browse timeout {url}")
    except Exception as e:
        log(f"browse: {e}")
    return ""


def web_search_review(name: str, max_chars: int = 800) -> str | None:
    query = urllib.request.quote(f"{name} review")
    return fetch_url_text(f"https://www.bing.com/search?q={query}&ensearch=0&FORM=BESBTB", max_chars=max_chars, timeout=12)


def read_recent_emails(days: int = 7, limit: int = 20, mark_read: bool = False) -> list[dict]:
    import email as _email
    import imaplib
    from email.header import decode_header

    if "ID" not in imaplib.Commands:
        imaplib.Commands["ID"] = ("AUTH",)

    def _dec(value):
        if not value:
            return ""
        parts = decode_header(value)
        out = []
        for part, charset in parts:
            if isinstance(part, bytes):
                try:
                    out.append(part.decode(charset or "utf-8", errors="replace"))
                except Exception:
                    out.append(part.decode("utf-8", errors="replace"))
            else:
                out.append(part)
        return "".join(out)

    try:
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL("imap.163.com", 993, ssl_context=ctx)
        mail.login(EMAIL_FROM, EMAIL_PASS)
        mail._simple_command("ID", '("name" "soy" "version" "1.0" "vendor" "soy" "contact" "")')
        mail.select("INBOX")
        since = time.strftime("%d-%b-%Y", time.localtime(time.time() - days * 86400))
        typ, data = mail.search(None, f'(SINCE "{since}")')
        if typ != "OK":
            mail.close()
            mail.logout()
            return []
        ids = data[0].split()
        out = []
        for uid in ids[-limit:]:
            typ, msg_data = mail.fetch(uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = _email.message_from_bytes(msg_data[0][1])
            sender = _dec(msg.get("From", ""))
            subject = _dec(msg.get("Subject", ""))
            date = msg.get("Date", "")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            message_id = msg.get("Message-ID", "").strip()
            in_reply_to = msg.get("In-Reply-To", "").strip()
            out.append({"from": sender[:80], "subject": subject[:120], "date": date, "body": body[:1500], "message_id": message_id, "in_reply_to": in_reply_to})
            if mark_read:
                try:
                    mail.store(uid, "+FLAGS", "\\Seen")
                except Exception:
                    pass
        mail.close()
        mail.logout()
        return out
    except Exception as e:
        log(f"imap: {e}")
        return []


def send_email(subject: str, body: str, to: str | None = None, in_reply_to: str | None = None) -> bool:
    import smtplib
    from email.message import EmailMessage

    if not EMAIL_FROM or not EMAIL_PASS:
        log("send_email: EMAIL_FROM / EMAIL_PASS not set")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = EMAIL_FROM
    msg["To"] = to or EMAIL_TO
    msg.set_content(body or "")
    try:
        with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.send_message(msg)
        log(f"email sent: {subject[:60]}")
        return True
    except Exception as e:
        log(f"email fail: {e}")
        return False



def _research_worker(task_id: str, task: str, email: bool | str, target: str, user_id: str):
    import core as _core

    started = time.time()
    try:
        result, src = call_ds_research(task)
        if not result:
            _core.log(f"research '{task_id}': ds/qw failed, trying cf")
            result, src = call_tool_chain(task, timeout=TOOL_TIMEOUT)
        if not result:
            _core.log(f"research '{task_id}' failed (timeout or empty)")
            _core.wx_push(target, f"\u26a0\ufe0f \u8c03\u7814\u5931\u8d25\uff1a{task[:50]}\n\uff08claude relay/codex \u90fd\u6ca1\u8fd4\u56de\uff0c\u53ef\u80fd\u8981\u62c9\u957f timeout \u6216\u6362\u8def\u5f84\uff09")
            return
        cleaned = process_markers(result, user_id=user_id)
        cleaned, emails = parse_email_segments(cleaned)
        for subj, body in emails[:2]:
            send_email(subj, body, None)
        cleaned = re.sub(
            r"\[(?:DRAW|FETCH|BROWSE|YT|POI|TOOL|INBOX|RESEARCH|RECALL|voice)[^\]]*\]",
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        elapsed = int(time.time() - started)
        prefix = f"\U0001f4cb \u8c03\u7814\u5b8c\u6210\uff08{elapsed}s, via {src}\uff09\uff1a{task[:40]}\n\n"
        full = prefix + cleaned
        if email:
            subject = email if isinstance(email, str) and email is not True else f"\u8c03\u7814\u7ed3\u679c\uff1a{task[:50]}"
            ok = send_email(subject, full)
            if ok:
                _core.wx_push(target, f"\U0001f4e7 \u5df2\u53d1\u90ae\u4ef6\uff1a{subject}\n\n\u6458\u8981\uff1a{cleaned[:240]}\u2026")
            else:
                sent = _core.wx_push_bubbles(target, full)
                if sent == 0:
                    _core.log(f"research '{task_id}': wx AND email both failed - result lost")
        else:
            sent = _core.wx_push_bubbles(target, full)
            if sent == 0:
                _core.log(f"research '{task_id}': wx push all failed, falling back to email")
                subject = f"\u8c03\u7814\u7ed3\u679c\uff08wx\u63a8\u9001\u5931\u8d25\uff09\uff1a{task[:50]}"
                ok = send_email(subject, full)
                if not ok:
                    _core.log(f"research '{task_id}': email fallback also failed - result lost")
    except Exception as e:
        _core.log(f"research worker '{task_id}': {e}")
        _core.wx_push(target, f"\u26a0\ufe0f \u8c03\u7814\u51fa\u9519\uff1a{task[:40]}\n{str(e)[:100]}")
