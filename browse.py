#!/usr/bin/env python3
"""browse.py — fetch a URL with a real browser (Playwright + Chromium-headless),
return clean markdown. Designed to be invoked as a subprocess so chromium dies
when this process exits.

Usage: python3 browse.py <url> [max_chars]
Stdout: markdown / plain text.
"""
import asyncio, os, sys


async def fetch(url: str, max_chars: int = 12000) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",  # smaller RAM footprint
            ],
            proxy={"server": "http://127.0.0.1:7890"},
        )
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            try:
                await ctx.close()
            except Exception: pass
        finally:
            try: await browser.close()
            except Exception: pass

    # Reduce HTML to text via trafilatura if present, else regex.
    try:
        import trafilatura
        text = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            favor_recall=True,
        ) or ""
    except Exception:
        import re
        from html import unescape
        t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
        t = re.sub(r"<[^>]+>", " ", t)
        text = unescape(re.sub(r"\s+", " ", t)).strip()

    if not text:
        text = "(extracted nothing)"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…(truncated at {max_chars} chars)"
    return text


def main():
    if len(sys.argv) < 2:
        print("usage: browse.py <url> [max_chars]", file=sys.stderr)
        sys.exit(2)
    url = sys.argv[1]
    max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
    try:
        out = asyncio.run(fetch(url, max_chars))
    except Exception as e:
        print(f"[browse error] {e}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(out)


if __name__ == "__main__":
    main()
