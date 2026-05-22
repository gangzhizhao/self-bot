# 🚨 应急手册

服务器：阿里云 ECS，Ubuntu 22.04，IP `<YOUR_SERVER_IP>`
代码目录：`/root/bot/`

## 1. 怎么进来

### 通过 Tailscale (推荐 - mihomo 死了也能进)
```bash
# 手机/电脑装 Tailscale 客户端，登同账号，然后：
ssh root@<YOUR_TAILSCALE_IP>
# 或用 magic dns:
ssh root@<YOUR_TAILSCALE_HOSTNAME>
```

### 通过公网 IP (如果本地有梯子能访问阿里云)
```bash
ssh root@<YOUR_SERVER_IP>
```

服务器上当前活的服务：
```
bot-wx.service    WeChat OpenAI 兼容服务（127.0.0.1:8080）
mihomo.service    代理（127.0.0.1:7890，Claude / Codex 走它）
weclaw            微信桥（127.0.0.1:18011，独立进程）
cron.service      定时任务（自愈 watchdog 由它驱动）
tailscaled        Tailscale 守护
```

## 2. 常见故障对照

### 「bot-wx 没反应」
```bash
systemctl status bot-wx.service       # 看死活
journalctl -u bot-wx.service -n 50    # 看错误日志
systemctl restart bot-wx.service      # 重启
```

### 「微信收不到消息 / weclaw 死了」
```bash
ss -tlnp | grep 18011                 # weclaw 还在监听吗
ps -ef | grep weclaw                  # 进程还在吗
# 重新登录（要扫码）：
weclaw start
```

### 「mihomo 挂了 / 节点全死」
```bash
systemctl status mihomo.service       # 死了？
systemctl restart mihomo.service      # 救活
# 节点全跑路：
curl -s http://127.0.0.1:9090/proxies # 看节点状态
# 改订阅：
ls /etc/mihomo/ ; nano /etc/mihomo/config.yaml
systemctl restart mihomo.service
```

### 「Claude / Codex 连不上 / Anthropic 401」
```bash
# 试一下代理通不通
curl -x http://127.0.0.1:7890 https://api.anthropic.com -m 8 -I
# 通的话再看 bot 日志里具体什么错
tail -n 100 /root/bot/bot.log
```

### 「磁盘满」
```bash
df -h /
du -sh /root/bot/* /root/.cache/* /var/log/* | sort -h | tail
# 大概率是 chromium 缓存 / 老的 .bak_*
ls -lh /root/bot/.bak_*               # 老备份能删
```

### 「内存爆了 / OOM」
```bash
free -h
ps aux --sort=-%mem | head -10
# 多半是 chromium 没 kill
pkill -f browse.py
systemctl restart bot-wx.service
```

### 「想看 watchdog 自己有没有干活」
```bash
tail -n 50 /root/bot/watchdog.log     # 它的工作日志
cat /var/spool/cron/crontabs/root     # 确认 cron 注册
systemctl status cron                 # 确认 cron 在跑
# 手动触发一次：
python3 /root/bot/watchdog.py         # 立刻跑一次
```

### 「代码改坏了想回滚」
每次推代码都备份在 `/root/bot/.bak_<时间戳>/`：
```bash
ls /root/bot/.bak_*                   # 找最近一个
ls /root/bot_phase1_backup_20260509_122145/  # 删 TG 前的整套备份
# 比如想还原 core.py：
cp /root/bot_phase1_backup_20260509_122145/core.py /root/bot/core.py
systemctl restart bot-wx.service
```

## 3. 一条命令"全部踢一遍"
真的不知道哪里出问题，所有东西重启一次：
```bash
systemctl restart mihomo.service && \
sleep 3 && \
systemctl restart bot-wx.service && \
sleep 2 && \
systemctl is-active mihomo bot-wx
```

## 4. 关键文件位置

| 路径 | 作用 |
|------|------|
| `/root/bot/core.py` | AI 链路 / VLM / 邮件 / fetch / amap 主逻辑 |
| `/root/bot/wechat.py` | WX OpenAI 兼容 server |
| `/root/bot/watchdog.py` | 自愈守护，cron 每 2 分钟跑 |
| `/root/bot/browse.py` | chromium 子进程，[BROWSE:] 标记调它 |
| `/root/bot/wakeup.py` | 主动消息 cron，每 30 分钟 |
| `/root/bot/reminder_check.py` | 提醒触发，每分钟 |
| `/root/bot/prompts/persona.md` | 主 system prompt |
| `/root/bot/prompts/capabilities.md` | AI 能力清单（自动注入） |
| `/root/bot/prompts/ops.md` | 标记/分句规则 |
| `/root/bot/self.md` | AI 写给自己的备忘录（自由追加） |
| `/root/bot/bot.log` | 主日志 |
| `/root/bot/watchdog.log` | watchdog 日志 |
| `/root/bot/mcp.json` | claude 子进程的 MCP 配置 |
| `/opt/mcp-fetch/` | fetch MCP server 的 venv |
| `/etc/systemd/system/bot-wx.service` | systemd 单元 |
| `/var/spool/cron/crontabs/root` | cron 表 |

## 5. 我的密码 / Token / Key 都在哪?

- 全部在 `/root/bot/bot.env`（systemd EnvironmentFile 加载）
- DeepSeek / MiniMax / AMap / Supabase / CF Relay / OpenAI / 163 邮箱 / OWNER_USER_ID / OWNER_WX_TARGET 都在那一个文件
- 改 key 之后必须 `systemctl restart bot-wx.service`

## 6. 紧急关停 / 复位

```bash
# 完全停掉 bot 不回应任何消息
systemctl stop bot-wx.service

# 完全恢复
systemctl start bot-wx.service

# 禁用开机启动（重启服务器后不会自启）
systemctl disable bot-wx.service

# 复位为开机自启
systemctl enable bot-wx.service
```

## 7. 一些会让人误以为坏了但其实正常的现象

- **/browse 慢**：chromium 启动 + 渲染 + 抽取，单次 30-50 秒
- **bot.log 里有 SSL UNEXPECTED_EOF**：偶发，是 mihomo 抖动，下次请求自动重试
- **watchdog.log 里有 "switched X → Y"**：watchdog 在工作的迹象，是好事
