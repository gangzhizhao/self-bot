#!/usr/bin/env python3
"""Lightweight cost logging for bot v2 Phase 1."""

from __future__ import annotations


PRICE = {
    "deepseek-chat": (0.14, 0.28),
    "MiniMax-M2.7": (0.20, 0.60),
    "minimax-m2.7": (0.20, 0.60),
    "claude-cf": (3.00, 15.00),
    "codex": (0.00, 0.00),
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = len(text) - ascii_chars
    return non_ascii + max(1, ascii_chars // 4)


class CostTracker:
    def __init__(self, core_module):
        self.core = core_module

    def log_text_call(self, user_id: str, model: str, tool_type: str, prompt_text: str, output_text: str):
        input_tok = estimate_tokens(prompt_text)
        output_tok = estimate_tokens(output_text)
        self.log_usage(
            user_id=user_id,
            model=model,
            tool_type=tool_type,
            input_tok=input_tok,
            output_tok=output_tok,
        )

    def log_usage(self, user_id: str, model: str, tool_type: str, input_tok: int, output_tok: int):
        pin, pout = PRICE.get(model, (0.0, 0.0))
        cost_usd = (input_tok * pin + output_tok * pout) / 1_000_000
        row = {
            "user_id": user_id,
            "model": model,
            "tool_type": tool_type,
            "input_tok": input_tok,
            "output_tok": output_tok,
            "cost_usd": round(cost_usd, 6),
        }
        self.core.supa_bg("costs", row)
