#!/usr/bin/env python3
"""Context assembly for bot v2 Phase 1."""

from __future__ import annotations

import time
from pathlib import Path


class ContextBuilder:
    def __init__(self, core_module):
        self.core = core_module
        self.prompt_dir = Path(core_module.PROMPT_DIR)

    def build_system_prompt(self, user_id: str, chat_id: str) -> str:
        parts: list[str] = []
        parts.append(self._tier0_now())
        parts.extend(self._tier0_prompts())

        tier1 = self._tier1_base(user_id=user_id, chat_id=chat_id)
        if tier1:
            parts.append(tier1)

        tier2 = self._tier2_conditional(user_id=user_id, chat_id=chat_id)
        if tier2:
            parts.append(tier2)

        self_block = self._self_block(user_id=user_id)
        if self_block:
            parts.append(self_block)

        return "\n\n---\n\n".join(part for part in parts if part.strip())

    def build_history_messages(self, user_id: str, chat_id: str, user_msg: str) -> list[dict]:
        messages = self.core.load_history(chat_id=chat_id, user_id=user_id)
        out = [{"role": row.get("role", "user"), "content": row.get("content", "")} for row in messages]
        out.append({"role": "user", "content": user_msg})
        return out

    def _tier0_now(self) -> str:
        now_str = time.strftime("%Y-%m-%d %H:%M %A")
        return f"## Now\n{now_str} (Asia/Shanghai)"

    def _tier0_prompts(self) -> list[str]:
        out: list[str] = []
        for fname in ("persona.md", "capabilities.md", "ops.md"):
            p = self.prompt_dir / fname
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                out.append(text)
        return out

    def _tier1_base(self, user_id: str, chat_id: str) -> str:
        lines: list[str] = []
        pref_rows = self.core.list_pref_memories(user_id=user_id, limit=5)
        if pref_rows:
            lines.append("## User Preferences")
            lines.extend(f"- {row}" for row in pref_rows)

        gap = self.core.describe_last_gap(chat_id=chat_id, user_id=user_id)
        if gap:
            if not lines:
                lines.append("## Session Context")
            lines.append(f"- Last conversation gap: {gap}")

        activity = self.core.get_now_activity(chat_id)
        if activity:
            act, since = activity
            mins = max(0, int((time.time() - since) / 60)) if since else 0
            if not lines:
                lines.append("## Session Context")
            lines.append(f"- Current activity: {act} ({mins} min)")

        return "\n".join(lines)

    def _tier2_conditional(self, user_id: str, chat_id: str) -> str:
        lines: list[str] = []

        annuals = self.core.get_annual_alerts(user_id=user_id)
        if annuals:
            lines.append("## Annual Reminders")
            for days_ahead, content in annuals:
                if days_ahead == 0:
                    prefix = "Today"
                elif days_ahead == 1:
                    prefix = "Tomorrow"
                else:
                    prefix = f"In {days_ahead} days"
                lines.append(f"- {prefix}: {content}")

        if self.core.is_first_of_day(chat_id):
            loop_open = self.core.pick_open_loop(user_id=user_id)
            if loop_open:
                if not lines:
                    lines.append("## Gentle Open Loop")
                lines.append(f"- Open loop: {loop_open}")

        loc = self.core.get_user_location_memo(user_id=user_id)
        if loc and hasattr(self.core, "_ambient_weather_for"):
            weather = self.core._ambient_weather_for(loc)
            if weather:
                if not lines:
                    lines.append("## Ambient")
                lines.append(f"- Weather: {weather}")

        return "\n".join(lines)

    def _self_block(self, user_id: str) -> str:
        items = self.core.load_self_insights(user_id=user_id, token_budget=180)
        if not items:
            return ""
        return "## Self Insights\n" + "\n".join(f"- {item}" for item in items)
