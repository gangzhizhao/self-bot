from pathlib import Path
#!/usr/bin/env python3
"""Weekly consolidation for memories and self insights."""

import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core

DAYS = 7
USER_ID = core.OWNER_USER_ID


def fetch_recent_memories(user_id: str, days: int = DAYS) -> list[str]:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))
    rows = core.supa_select(
        "memories",
        {
            "select": "content,prefix,ts",
            "user_id": f"eq.{user_id}",
            "ts": f"gte.{cutoff}",
            "order": "ts.asc",
            "limit": "500",
        },
    )
    return [r.get("content", "").strip() for r in rows if r.get("content")]


def fetch_recent_self(user_id: str, days: int = DAYS) -> list[str]:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days * 86400))
    rows = core.supa_select(
        "self_insights",
        {
            "select": "content,tokens_est,ts,retired_at",
            "user_id": f"eq.{user_id}",
            "retired_at": "is.null",
            "ts": f"gte.{cutoff}",
            "order": "ts.asc",
            "limit": "200",
        },
    )
    return [r.get("content", "").strip() for r in rows if r.get("content")]


def main():
    memories = fetch_recent_memories(USER_ID)
    self_items = fetch_recent_self(USER_ID)
    if not memories and not self_items:
        print("nothing to consolidate")
        return

    sections = []
    if memories:
        sections.append("## Memories\n" + "\n".join(f"- {m}" for m in memories))
    if self_items:
        sections.append("## Existing self insights\n" + "\n".join(f"- {s}" for s in self_items))
    raw = "\n\n".join(sections)

    prompt = f"""Review the last {DAYS} days of memory material.

{raw}

Write:
1. A compact synthesis of recurring themes.
2. A short list of what should remain durable.
3. One concise [SELF: ...] line if there is a high-signal relationship or style insight worth carrying forward.

Keep it short, practical, and readable for future runs."""

    system = "You are consolidating memory state for future context injection. Output concise English."
    text, source = core.run_chain_with_source(prompt, system)
    if not text or text == "(é†å‚›æ¤‚éƒçŠ³ç¡¶é¥ç‚²î˜²)":
        print("consolidate: chain failed")
        return

    cleaned = core.process_markers(text, user_id=USER_ID)
    summary = cleaned.strip()
    if summary:
        core.supa_insert(
            "self_insights",
            {
                "user_id": USER_ID,
                "content": f"[weekly_summary {time.strftime('%Y-%m-%d')}] {summary}",
                "tokens_est": core.estimate_tokens(summary),
            },
        )
    core.log(f"consolidate: wrote weekly summary ({len(summary)} chars) via {source}")
    print("done")


if __name__ == "__main__":
    main()
