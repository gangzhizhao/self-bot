#!/usr/bin/env python3
"""Claude CLI subprocess wrapper.

Reads API config from bot.env / environment variables:
  ANTHROPIC_BASE_URL   — relay or direct API endpoint
                         (defaults to https://api.anthropic.com)
  ANTHROPIC_AUTH_TOKEN — API key or relay token
  PROXY_URL            — optional local HTTP proxy (e.g. http://127.0.0.1:7890)
  CLAUDE_USER          — system user to sudo into (default: claudebot)
  BOT_DIR              — bot root directory (default: directory of this script)
  MCP_CONFIG           — path to MCP config json
"""
import sys, os, subprocess
from pathlib import Path

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
CLAUDE_USER = os.environ.get("CLAUDE_USER", "claudebot")

def build_system():
    parts = []
    for f in ["persona.md", "capabilities.md", "ops.md"]:
        p = BOT_DIR / "prompts" / f
        if p.exists():
            t = p.read_text(encoding="utf-8").strip()
            if t:
                parts.append(t)
    return "

---

".join(parts)

def _load_bot_env():
    p = BOT_DIR / "bot.env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_bot_env()

env = dict(os.environ)
env["ANTHROPIC_BASE_URL"] = os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("CF_RELAY_URL", "https://api.anthropic.com")
env["ANTHROPIC_AUTH_TOKEN"] = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("CF_RELAY_TOKEN", "")
env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

proxy = os.environ.get("PROXY_URL", "")
if proxy:
    env["HTTP_PROXY"] = env["HTTPS_PROXY"] = env["ALL_PROXY"] = proxy

mcp_config = os.environ.get("MCP_CONFIG", f"/home/{CLAUDE_USER}/mcp.json")

r = subprocess.run(
    ["sudo", "-u", CLAUDE_USER, "-H",
     "--preserve-env=HTTPS_PROXY,HTTP_PROXY,ALL_PROXY,ANTHROPIC_BASE_URL,ANTHROPIC_AUTH_TOKEN,CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
     "/usr/bin/claude",
     "--dangerously-skip-permissions",
     "--mcp-config", mcp_config,
     "--system-prompt", build_system()] + sys.argv[1:],
    capture_output=True, text=True, env=env)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
