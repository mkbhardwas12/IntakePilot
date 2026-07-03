"""Local target — writes routed "tickets" as markdown files into
examples/demo-repo/ so the 5-minute demo works fully offline."""
from __future__ import annotations

import re
from pathlib import Path

from core.models import RequirementObject, Ticket


class LocalTarget:
    name = "local"

    def __init__(self, repo_path: str = "examples/demo-repo"):
        self.repo = Path(repo_path)

    async def create_item(self, obj: RequirementObject, title: str, body: str,
                          queue: str) -> Ticket:
        self.repo.mkdir(parents=True, exist_ok=True)
        filename = f"{obj.req_id}.md"
        path = self.repo / filename
        front = (f"---\nreq_id: {obj.req_id}\nqueue: {queue}\n"
                 f"label: intake/{re.sub(r'[^a-z0-9-]', '-', queue.lower())}\n---\n\n")
        path.write_text(front + body)
        return Ticket(target="local", ref=filename, path=str(path), title=title)

    async def register_webhook(self, url: str) -> None:  # no-op locally
        return None

    async def parse_status_event(self, payload: dict) -> dict:
        return {"req_id": payload.get("req_id"), "status": payload.get("status")}
