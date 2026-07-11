"""GitHub target — stub (Milestone 6). Creates a labeled issue via the REST API
when GITHUB_TOKEN and a repo are configured; webhook status sync is spec'd but
not yet implemented (see docs/SPEC-REVIEW.md on webhook security)."""
from __future__ import annotations

import os

import httpx

from core.models import RequirementObject, Ticket
from core.providers.http_retry import request_with_retries


class GitHubTarget:
    name = "github"

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.repo = config.get("repo", "")  # "org/repo"
        self.token = os.environ.get(config.get("token_env", "GITHUB_TOKEN"), "")

    async def create_item(self, obj: RequirementObject, title: str, body: str,
                          queue: str) -> Ticket:
        if not (self.repo and self.token):
            raise RuntimeError("GitHub target requires repo config and GITHUB_TOKEN")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await request_with_retries(
                client, "POST",
                f"https://api.github.com/repos/{self.repo}/issues",
                headers={"Authorization": f"Bearer {self.token}",
                         "Accept": "application/vnd.github+json"},
                json={"title": title, "body": body,
                      "labels": [f"intake/{queue}", "intakepilot"]})
            resp.raise_for_status()
            data = resp.json()
        return Ticket(target="github", ref=str(data["number"]),
                      path=data["html_url"], title=title)

    async def register_webhook(self, url: str) -> None:
        raise NotImplementedError("Milestone 6: webhook status sync")

    async def parse_status_event(self, payload: dict) -> dict:
        raise NotImplementedError("Milestone 6: webhook status sync")
