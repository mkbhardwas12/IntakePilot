"""Prompts ship as versioned files (spec 6.2); this module loads and fills them."""
from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


def load(name: str, **fills: str) -> str:
    text = (PROMPT_DIR / f"{name}.md").read_text()
    for key, value in fills.items():
        text = text.replace("{" + key + "}", value)
    return text
