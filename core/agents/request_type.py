"""Request-type classifier — deterministic keyword scoring, in code.

The type selects a slot-schema fork (core/schemas/<type>.yaml, falling back
to default.yaml) and becomes part of the context bucket, so questions,
exemplars, and calibration all specialize per request type. Deliberately not
an LLM call: classification must be cheap, explainable, and stable.
"""
from __future__ import annotations

import re

# Order matters: earlier types win ties (a "report is broken" ask is a bug
# about a report, not a request for a new one).
TYPE_KEYWORDS: dict[str, list[str]] = {
    "bug_report": ["error", "broken", "fail", "crash", "wrong", "incorrect",
                   "bug", "stopped", "not working", "doesn't work", "defect"],
    "data_request": ["report", "dashboard", "export", "extract", "metric",
                     "kpi", "list of", "numbers", "figures", "data"],
    "new_capability": ["automate", "build", "create", "integrate", "workflow",
                       "portal", "tool", "sync", "new process", "capability"],
}


def classify_request_type(text: str) -> str:
    low = text.lower()
    best_type, best_score = "default", 0
    for req_type, keywords in TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}", low))
        if score > best_score:  # strict >: earlier (higher-priority) type keeps ties
            best_type, best_score = req_type, score
    return best_type
