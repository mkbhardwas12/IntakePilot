"""Jira Cloud target (Milestone 6) — the same one-class protocol as every
other target. Creates an issue via REST v3 with the requirement rendered as
Atlassian Document Format, the queue and requirement id carried as labels
(Jira labels forbid spaces; slashes are unreliable, so `intake-<queue>` and
the lowercase requirement id are used — the webhook parses both back).

Config (intakepilot.yaml `targets: jira:` or env):
    base_url   e.g. https://yourorg.atlassian.net   (JIRA_BASE_URL)
    project    e.g. INTAKE                          (JIRA_PROJECT_KEY)
    issue_type default "Task"                       (JIRA_ISSUE_TYPE)
    email/token via JIRA_EMAIL + JIRA_API_TOKEN     (basic auth, api token)
"""
from __future__ import annotations

import os
import re

import httpx

from core.models import RequirementObject, Ticket

_CODE_FENCE = re.compile(r"^```")


def _adf_text(text: str) -> dict:
    return {"type": "text", "text": text or " "}


def markdown_to_adf(body: str) -> dict:
    """Minimal, deterministic markdown -> ADF for our own ticket renderer's
    output: headings, bullet runs, fenced code, paragraphs."""
    content: list[dict] = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _CODE_FENCE.match(line):
            buf = []
            i += 1
            while i < len(lines) and not _CODE_FENCE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            content.append({"type": "codeBlock",
                            "content": [_adf_text("\n".join(buf))]})
            i += 1
            continue
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 6)
            content.append({"type": "heading", "attrs": {"level": level},
                            "content": [_adf_text(line.lstrip("#").strip())]})
            i += 1
            continue
        if line.startswith(("- ", "* ")):
            items = []
            while i < len(lines) and lines[i].startswith(("- ", "* ")):
                items.append({"type": "listItem", "content": [
                    {"type": "paragraph",
                     "content": [_adf_text(lines[i][2:].strip())]}]})
                i += 1
            content.append({"type": "bulletList", "content": items})
            continue
        if line.strip():
            content.append({"type": "paragraph", "content": [_adf_text(line)]})
        i += 1
    return {"type": "doc", "version": 1,
            "content": content or [{"type": "paragraph",
                                    "content": [_adf_text(" ")]}]}


def queue_label(queue: str) -> str:
    return "intake-" + re.sub(r"[^a-z0-9-]", "-", queue.lower())


def req_label(req_id: str) -> str:
    return req_id.lower()          # e.g. ipr-2026-000004


class JiraTarget:
    name = "jira"

    def __init__(self, config: dict | None = None, transport=None):
        config = config or {}
        self.base_url = (config.get("base_url")
                         or os.environ.get("JIRA_BASE_URL", "")).rstrip("/")
        self.project = (config.get("project")
                        or os.environ.get("JIRA_PROJECT_KEY", ""))
        self.issue_type = (config.get("issue_type")
                           or os.environ.get("JIRA_ISSUE_TYPE", "Task"))
        self.email = os.environ.get(config.get("email_env", "JIRA_EMAIL"), "")
        self.token = os.environ.get(config.get("token_env", "JIRA_API_TOKEN"), "")
        self._transport = transport      # tests inject httpx.MockTransport

    async def create_item(self, obj: RequirementObject, title: str, body: str,
                          queue: str) -> Ticket:
        if not (self.base_url and self.project and self.email and self.token):
            raise RuntimeError(
                "Jira target requires JIRA_BASE_URL, JIRA_PROJECT_KEY, "
                "JIRA_EMAIL and JIRA_API_TOKEN")
        payload = {"fields": {
            "project": {"key": self.project},
            "issuetype": {"name": self.issue_type},
            "summary": title[:255],
            "description": markdown_to_adf(body),
            "labels": ["intakepilot", queue_label(queue), req_label(obj.req_id)],
        }}
        async with httpx.AsyncClient(timeout=30, auth=(self.email, self.token),
                                     transport=self._transport) as client:
            resp = await client.post(f"{self.base_url}/rest/api/3/issue",
                                     json=payload)
            resp.raise_for_status()
            data = resp.json()
        key = data["key"]
        return Ticket(target="jira", ref=key,
                      path=f"{self.base_url}/browse/{key}", title=title)
