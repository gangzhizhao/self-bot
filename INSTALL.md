# Install / Disaster Recovery

Run on a fresh Ubuntu 22.04+ machine (Aliyun ECS recommended, 2 vCPU / 2 GB RAM /
40 GB disk minimum).

## 1. System dependencies

```bash
apt update && apt install -y \
  python3 python3-pip python3-venv \
  ffmpeg \
  git curl \
  nodejs npm

# Optional but recommended
apt install -y tailscale
systemctl enable --now tailscaled
tailscale up           # follow auth URL
```

## 2. Clone

```bash
git clone https://github.com/<you>/self-bot.git /root/self-bot
cd /root/self-bot
```

## 3. Python deps

```bash
pip3 install -r requirements.txt

# Chromium for /browse (~150 MB)
python3 -m playwright install --with-deps chromium

# fetch MCP server (used by Claude / Codex subprocess wrappers)
python3 -m venv /opt/mcp-fetch
/opt/mcp-fetch/bin/pip install mcp-server-fetch
```

## 4. Secrets

Restore `bot.env` from your password manager backup (1Password / Bitwarden /
encrypted USB). The file is git-ignored. Required keys:

```
OWNER_USER_ID=wx_<your-ilink-id>@im.wechat   # Supabase user_id for memories
OWNER_WX_TARGET=<your-ilink-id>@im.wechat    # weclaw send target
DEEPSEEK_API_KEY=sk-...
MINIMAX_KEY=sk-api-...
AMAP_KEY=...
SUPABASE_URL=https://....supabase.co/rest/v1
SUPABASE_KEY=sb_secret_...
CF_RELAY_URL=https://...
CF_RELAY_TOKEN=sk-...
OPENAI_API_KEY=sk-...
EMAIL_HOST=smtp.163.com
EMAIL_PORT=465
EMAIL_FROM=...@163.com
EMAIL_PASS=...     # 163 SMTP/IMAP authorization code, not login password
EMAIL_TO=...
```

```bash
nano /root/bot/bot.env
chmod 600 /root/bot/bot.env
```

## 5. Supabase schema

If you're starting fresh, create these tables in your Supabase project:

```sql
create table memories  (id bigserial primary key, content text, created_at timestamptz default now());
create table diary     (id bigserial primary key, content text, created_at timestamptz default now());
create table reference (id bigserial primary key, category text, content text, created_at timestamptz default now());
create table reminders (id bigserial primary key, time text, date text, content text, done bool default false, created_at timestamptz default now());
```

(restoring a previous deployment? supabase keeps your data; just point bot.env at the same project.)

## 6. 代理（Claude / Codex 需要）

Claude 和 Codex 的 API 在部分地区需要代理才能访问。bot 默认走本地 HTTP 代理 127.0.0.1:7890。

任何本地代理客户端都可以（推荐 mihomo）：

```bash
systemctl status mihomo
```

如果你只用 DeepSeek / MiniMax（国内直连），跳过这步。

## 7. systemd services

```bash
cp systemd/bot-wx.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bot-wx.service
systemctl status bot-wx
```

## 8. cron (self-healing + autonomy)

```bash
crontab systemd/crontab.example
crontab -l   # verify
```

This adds:

- `wakeup.py` every 30 min — random-probability autonomous messages
- `reminder_check.py` every minute — fires reminders on schedule
- `watchdog.py` every 2 min — proxy + weclaw health check
- `inbox_scan.py` Monday 09:30 — weekly inbox digest
- `consolidate.py` Sunday 04:00 — weekly memory consolidation

## 9. WeChat bridge

```bash
# install weclaw (Linux x86_64 binary, see https://github.com/weclaw/weclaw)
weclaw login         # scan QR with WeChat
weclaw start         # listens on 127.0.0.1:18011
```

Make sure `/root/.weclaw/config.json` points to `http://127.0.0.1:8080/v1/chat/completions`.

## 10. Verify

```bash
# from WX, send /menu — should list all commands
# from WX, send /health — should return system + chat status
```

## Operational

- Logs: `/root/bot/*.log`
- Emergency procedures: `EMERGENCY.md`
- Backups: every push creates `.bak_YYYYMMDD_HHMMSS/` (git-ignored)
- Restart: `systemctl restart bot-wx`
