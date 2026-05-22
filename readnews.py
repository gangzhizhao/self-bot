from pathlib import Path
#!/usr/bin/env python3
"""readnews.py — daily reading habit, token-efficient two-pass approach.

Pass 1: fetch RSS feeds, parse titles+links locally (no LLM, cheap)
Pass 2: LLM picks 1-2 interesting titles, fetch only those full articles
Pass 3: LLM writes brief notes, stored as READING memories

Runs daily at 08:00 via cron.
"""

import ssl
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core

USER_ID = "<YOUR_TG_USER_ID>"
FAILURES_FILE = str(Path(__file__).resolve().parent / "rss_failures.json")
FAILURE_THRESHOLD = 5

SOURCES = [
    # 科技 / AI
    ("Hacker News",       "https://hnrss.org/frontpage"),
    ("Solidot",           "https://www.solidot.org/index.rss"),
    ("36kr",              "https://rsshub.app/36kr/news/technology"),
    ("少数派",             "https://sspai.com/feed"),
    ("虎嗅",              "https://www.huxiu.com/rss/0.xml"),
    ("爱范儿",             "https://www.ifanr.com/feed"),
    ("品玩",              "https://www.pingwest.com/feed"),
    ("The Verge",         "https://www.theverge.com/rss/index.xml"),
    ("MIT Tech Review",   "https://www.technologyreview.com/feed/"),
    ("Wired",             "https://www.wired.com/feed/rss"),
    # 商业 / 创业
    ("FastCompany",       "https://www.fastcompany.com/latest/rss"),
    ("白鲸出海",           "https://rsshub.app/baijingapp/home"),
    ("Benedict Evans",    "https://www.ben-evans.com/benedictevans/rss.xml"),
    # 文化 / 电影 / 书
    ("豆瓣新片",          "https://www.douban.com/feed/review/movie"),
    ("豆瓣书评",          "https://www.douban.com/feed/review/book"),
    ("知乎日报",          "https://rsshub.app/zhihu/daily"),
    ("时光网",            "https://rsshub.app/mtime/news"),
    ("Kottke",            "https://feeds.kottke.org/main"),
    ("Marginalian",       "https://www.themarginalian.org/feed/"),
    ("Colossal",          "https://www.thisiscolossal.com/feed/"),
    # 科学 / 心理
    ("果壳",              "https://www.guokr.com/rss/"),
    ("科学美国人",         "https://rsshub.app/scientificamerican/china"),
    ("国家地理中文",       "https://rsshub.app/natgeo/zh"),
    ("Quanta Magazine",   "https://www.quantamagazine.org/feed/"),
    # 社会 / 观察
    ("微博热搜",          "https://rsshub.app/weibo/search/hot"),
    ("BBC中文",           "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"),
    ("Reuters",           "https://feeds.reuters.com/reuters/topNews"),
    ("Axios",             "https://api.axios.com/feed/"),
    # 设计 / 创意
    ("Dezeen",            "https://feeds.feedburner.com/dezeen"),
    ("It's Nice That",    "https://www.itsnicethat.com/rss"),
    # 旅行 / 城市
    ("Lonely Planet",     "https://www.lonelyplanet.com/feed"),
    ("穷游",              "https://rsshub.app/qyer/article"),
    # 小众 / 有趣
    ("V2EX",              "https://www.v2ex.com/index.xml"),
    ("Ribbonfarm",        "https://www.ribbonfarm.com/feed/"),
    ("Aeon",              "https://aeon.co/feed.rss"),
    ("Nautilus",          "https://nautil.us/feed/"),
    ("Weird Universe",    "https://weirduniverse.net/atom.xml"),
    # 播客 / 观点
    ("FT中文",            "https://rsshub.app/ft/chinese/technology"),
    ("好奇心日报",         "https://rsshub.app/qdaily/index"),
    # 新闻深度
    ("澎湃新闻",           "https://rsshub.app/thepaper/featured"),
    ("The Guardian",      "https://www.theguardian.com/world/rss"),
    ("Al Jazeera",        "https://www.aljazeera.com/xml/rss/all.xml"),
    ("404 Media",         "https://www.404media.co/feed/"),
    ("Rest of World",     "https://restofworld.org/feed/"),
    ("Semafor",           "https://www.semafor.com/feed"),
    # 商业 / 策略
    ("Not Boring",        "https://www.notboring.co/feed"),
    ("Nikkei Asia",       "https://asia.nikkei.com/rss/feed/news"),
    # 文学 / 书
    ("Paris Review",      "https://www.theparisreview.org/feed/rss/"),
    ("Literary Hub",      "https://lithub.com/feed"),
    # 小众高质量
    ("BLDGBLOG",          "https://bldgblog.com/feed/"),
    ("80,000 Hours",      "https://80000hours.org/feed/"),
    ("Futurism",          "https://futurism.com/feed"),
    # 中文深度
    ("晚点LatePost",       "https://rsshub.app/latepost"),
    ("三联生活周刊",       "https://www.lifeweek.com.cn/rss"),
    ("极客公园",           "https://www.geekpark.net/rss"),
    ("机器之心",           "https://rsshub.app/jiqizhixin/article"),
    ("阮一峰",             "https://www.ruanyifeng.com/blog/atom.xml"),
    ("触乐",              "https://www.chuapp.com/feed"),
    ("单读",              "https://rsshub.app/dooook/"),
    # 中文深度补充
    ("界面新闻",           "https://www.jiemian.com/rss.xml"),
    ("南风窗",             "https://rsshub.app/nfcmag/"),
    ("字母榜",             "https://rsshub.app/zimuibang/home"),
    ("海外掘金",           "https://rsshub.app/haiwaidejin/"),
    ("财新",              "https://rsshub.app/caixin/article/china"),
    # 即刻
    ("即刻·科技互联网",    "https://rsshub.app/jike/topic/553870e8e4b0cacaf3b98585"),
    ("即刻·产品",         "https://rsshub.app/jike/topic/553870e8e4b0cacaf3b98586"),
    ("即刻·创业",         "https://rsshub.app/jike/topic/553870e8e4b0cacaf3b98587"),
    # 长文 / 深度
    ("The Atlantic",      "https://feeds.feedburner.com/TheAtlantic"),
    ("The New Yorker",    "https://www.newyorker.com/feed/everything"),
    ("Longreads",         "https://longreads.com/feed/"),
    ("Psyche",            "https://psyche.co/feed"),
    ("Works in Progress", "https://worksinprogress.co/feed.rss"),
    ("Wait But Why",      "https://waitbutwhy.com/feed"),
    # 苹果 / 独立科技
    ("Daring Fireball",   "https://daringfireball.net/feeds/main"),
    # 中文垂直
    ("一席",              "https://rsshub.app/yixi/"),
    ("刺猬公社",          "https://www.ciweigongshe.net/feed/"),
    ("游研社",            "https://www.youxituoluo.com/feed"),
    ("差评",              "https://chaping.cc/feed"),
    # 创意 / 视觉
    ("Brutalist Websites","https://brutalistwebsites.com/rss.xml"),
    ("Core77",            "https://www.core77.com/rss"),
    # 小众英文
    ("Sidebar.io",        "https://sidebar.io/feed.xml"),
    ("Dense Discovery",   "https://www.densediscovery.com/feed.xml"),
    ("Offscreen Dispatch","https://offscreenmag.com/dispatch/feed"),
]

MAX_TITLES_PER_SOURCE = 5
MAX_ARTICLE_CHARS = 2500


def fetch_rss_titles(url: str) -> list[dict]:
    """Fetch an RSS feed and return list of {title, link}. No LLM involved."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []

        # RSS 2.0
        for item in root.findall(".//item")[:MAX_TITLES_PER_SOURCE]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link:
                items.append({"title": title, "link": link})

        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:MAX_TITLES_PER_SOURCE]:
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = (link_el.get("href") if link_el is not None else "") or ""
                if title and link:
                    items.append({"title": title, "link": link})

        return items
    except Exception as e:
        core.log(f"readnews fetch_rss {url}: {e}")
        return []



def load_failures() -> dict:
    import json as _json
    try:
        with open(FAILURES_FILE, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def save_failures(data: dict):
    import json as _json
    with open(FAILURES_FILE, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    prefs = core.list_pref_memories(user_id=USER_ID, limit=10)
    pref_text = "\n".join(prefs) if prefs else "科技、AI、文化、小众有趣的事"

    # Pass 1: collect all titles (pure local, zero tokens)
    all_titles: list[str] = []
    link_map: dict[str, str] = {}

    failures = load_failures()
    flagged = []
    for source_name, url in SOURCES:
        items = fetch_rss_titles(url)
        if items:
            failures[source_name] = 0
        else:
            failures[source_name] = failures.get(source_name, 0) + 1
            if failures[source_name] >= FAILURE_THRESHOLD:
                flagged.append(f"{source_name} ({failures[source_name]}x)")
        for item in items:
            label = f"[{source_name}] {item['title']}"
            all_titles.append(label)
            link_map[label] = item["link"]
        core.log(f"readnews: {source_name} → {len(items)} titles")
    save_failures(failures)
    if flagged:
        core.log(f"readnews DEAD SOURCES: {', '.join(flagged)}")

    if not all_titles:
        core.log("readnews: no titles fetched")
        return

    title_block = "\n".join(f"{i+1}. {t}" for i, t in enumerate(all_titles))

    # Pass 2: LLM picks 1-2 titles (only titles, very short context)
    recent_rows = core.supa_select("memories", {"select": "content", "user_id": f"eq.{USER_ID}", "prefix": "eq.READING", "order": "ts.desc", "limit": "10"})
    recent_reading = "\n".join(r.get("content", "") for r in recent_rows if r.get("content"))
    system = core.get_system_prompt(chat_id=USER_ID, user_id=USER_ID)
    pick_prompt = "\n".join([
        f"今天是 {time.strftime('%Y-%m-%d')}。以下是今天各来源的标题列表：",
        "",
        title_block,
        "",
        "用户兴趣偏好：",
        pref_text,
        "",
        "从上面选出 1-2 条你觉得最值得深读的，用序号回答，逗号分隔。",
        "只输出序号，例如：3, 7",
        "没有值得看的就输出：SKIP",
        "",
        "最近已经读过的（避免重复类似话题）：",
        recent_reading or "（暂无）",
    ])

    msgs = [{"role": "user", "content": pick_prompt}]
    pick_result = core.call_deepseek(msgs, system, use_tools=False)
    if not pick_result:
        pick_result = core.call_minimax(msgs, system, use_tools=False)

    if not pick_result or pick_result.strip().upper() == "SKIP":
        core.log("readnews: LLM skipped, nothing interesting")
        return

    # Parse selected indices
    import re
    selected_indices = [int(x.strip()) - 1 for x in re.findall(r'\d+', pick_result)]
    selected = [all_titles[i] for i in selected_indices if 0 <= i < len(all_titles)]

    if not selected:
        core.log("readnews: no valid selection")
        return

    core.log(f"readnews: selected {selected}")

    # Pass 3: fetch articles and generate brief notes
    article_contexts = []
    for label in selected:
        url = link_map.get(label, "")
        if not url:
            continue
        text = core.fetch_url_text(url, max_chars=MAX_ARTICLE_CHARS)
        if text:
            article_contexts.append(f"### {label}\n{text[:MAX_ARTICLE_CHARS]}")

    if not article_contexts:
        core.log("readnews: articles empty after fetch")
        return

    note_prompt = "\n".join([
        "你读了以下文章：",
        "",
        "\n\n".join(article_contexts),
        "",
        "用 [READING: ...] 格式，每篇写一条笔记——一两句话，说清楚这件事是什么、为什么有意思。",
        "不要凑数，没感觉就不写。",
        "只输出 [READING: ...] 标记，不要其他内容。",
    ])

    msgs2 = [{"role": "user", "content": note_prompt}]
    note_result = core.call_deepseek(msgs2, system, use_tools=False)
    if not note_result:
        core.log("readnews: note generation failed")
        return

    items_saved = re.findall(r'\[READING:\s*(.+?)\]', note_result, re.DOTALL)
    for item in items_saved:
        item = item.strip()
        if item:
            core.supa_bg("memories", {
                "user_id": USER_ID,
                "content": item,
                "prefix": "READING",
            })
            core.log(f"readnews saved: {item[:80]}")

    core.log(f"readnews done: {len(items_saved)} notes saved")
    cleanup_old_readings()


def cleanup_old_readings():
    """Delete READING memories older than 45 days."""
    import urllib.request, json, ssl as _ssl
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 45 * 86400))
    supa_url = core._env("SUPABASE_URL", "")
    supa_key = core._env("SUPABASE_KEY", "")
    if not supa_url or not supa_key:
        return
    url = f"{supa_url}/memories?user_id=eq.{USER_ID}&prefix=eq.READING&ts=lt.{cutoff}"
    headers = {
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request(url, headers=headers, method="DELETE")
        with urllib.request.urlopen(req, timeout=10, context=_ssl.create_default_context()) as r:
            r.read()
        core.log(f"readnews cleanup: deleted READING older than 45d")
    except Exception as e:
        core.log(f"readnews cleanup error: {e}")


if __name__ == "__main__":
    main()
