"""Deterministic mock LLM provider — the zero-dependency demo path.

Heuristic keyword extraction so the entire product runs and demos with no
model installed. Dispatches on the `TASK:` tag that prompt templates embed
in the system message; parses the machine-readable sections the templates
delimit. Deterministic by construction, which also makes tests exact.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from core.providers.llm.base import LLMResult, Msg

SYSTEM_NAMES = [
    "SAP", "S4P", "Salesforce", "Workday", "Jira", "ServiceNow", "Oracle",
    "NetSuite", "Tableau", "Power BI", "PowerBI", "Snowflake", "SharePoint",
    "Excel", "Slack", "Confluence", "Zendesk", "HubSpot", "QuickBooks",
]

URGENCY_PATTERNS = [
    (r"\b(urgent|asap|immediately|right away|today)\b", "this week"),
    (r"\b(this week|end of week|eow)\b", "this week"),
    (r"\b(this month|end of month|eom)\b", "this month"),
    (r"\b(this quarter|end of quarter|eoq|q[1-4])\b", "this quarter"),
    (r"\b(no rush|whenever|no deadline|not urgent)\b", "no hard deadline"),
]

SENSITIVE_PATTERNS = r"\b(pii|personal data|confidential|customer data|salary|payroll|hr data|medical|health record)\b"


def _extract_slots(message: str) -> dict:
    text = message.strip()
    low = text.lower()
    slots: dict[str, dict] = {}

    # business_outcome — the "X takes N <unit> to <verb>" manual-work pattern
    m = re.search(
        r"(?:our|the|my)?\s*([\w\s\-]+?)\s+takes\s+(?:about\s+|around\s+)?([\d.]+\s*\w+)\s+to\s+(\w+)",
        low)
    manual = bool(re.search(r"\b(by hand|manual|manually|hand-compiled|copy.?past)\b", low))
    if m:
        subject, duration, verb = m.group(1).strip(), m.group(2).strip(), m.group(3)
        how = " by hand" if manual else ""
        slots["business_outcome"] = {
            "value": f"Automate the {subject} — currently {duration} to {verb}{how}",
            "confidence": 0.85}
    elif manual:
        slots["business_outcome"] = {
            "value": f"Automate a manual process: {text.rstrip('.')}",
            "confidence": 0.7}
    elif re.search(r"\b(need|want|would like|automate|build|create|fix|improve)\b", low) and len(text) > 24:
        slots["business_outcome"] = {"value": text.rstrip("."), "confidence": 0.6}

    for pattern, value in URGENCY_PATTERNS:
        if re.search(pattern, low):
            slots["urgency"] = {"value": value, "confidence": 0.8}
            break

    m = re.search(r"so that (.+?)(?:\.|$)", low)
    if m:
        slots["success_criteria"] = {"value": m.group(1).strip(), "confidence": 0.75}
    else:
        m = re.search(r"\bunder\s+([\d.]+\s*(?:minutes?|hours?|days?))\b", low)
        if m:
            slots["success_criteria"] = {
                "value": f"completes in under {m.group(1)}", "confidence": 0.7}

    systems = [s for s in SYSTEM_NAMES if re.search(rf"\b{re.escape(s.lower())}\b", low)]
    if systems:
        slots["affected_systems"] = {"value": sorted(set(systems)), "confidence": 0.8}

    m = re.search(r"\b(?:out of scope|excluding|but not|except)\s*[:\-]?\s*(.+?)(?:\.|$)", low)
    if m:
        slots["scope_boundaries"] = {"value": m.group(1).strip(), "confidence": 0.7}

    if re.search(SENSITIVE_PATTERNS, low):
        slots["data_sensitivity"] = {"value": "confidential", "confidence": 0.75}

    return {"slots": slots}


def _compose_questions(prompt: str) -> dict:
    """Read the JSON gap block the question template embeds; one question per gap."""
    m = re.search(r"## Gaps\n```json\n(.*?)\n```", prompt, re.S)
    gaps = json.loads(m.group(1)) if m else []
    questions = []
    for gap in gaps:
        hint = gap.get("ask_hint") or f"can you tell me about {gap['key'].replace('_', ' ')}?"
        questions.append({
            "slot_key": gap["key"],
            "text": hint[0].upper() + hint[1:] if hint else hint,
            "because": gap.get("because", "required to route this correctly"),
            "options": gap.get("options"),
        })
    return {"questions": questions}


class MockLLM:
    name = "mock"

    def __init__(self, config: dict | None = None):
        self.dim = int((config or {}).get("dim", 768))

    async def complete(self, messages: list[Msg], *, json_schema: dict | None = None,
                       temperature: float = 0.1, max_tokens: int = 2048) -> LLMResult:
        system = next((m.content for m in messages if m.role == "system"), "")
        full = "\n".join(m.content for m in messages)
        task_m = re.search(r"TASK:\s*(\w+)", system)
        task = task_m.group(1) if task_m else "extract"

        if task == "extract":
            um = re.search(r"## User message\n(.*?)(?:\n## |\Z)", full, re.S)
            message = um.group(1).strip() if um else ""
            data = _extract_slots(message)
        elif task == "question":
            data = _compose_questions(full)
        elif task.startswith("gate"):
            data = {"passed": True, "reason": None, "suggestion": None}
        else:
            data = {}
        return LLMResult(text=json.dumps(data), usage={"provider": "mock"})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for g in grams:
            h = int(hashlib.md5(g.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 16) % 2 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
