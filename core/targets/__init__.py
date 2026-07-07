"""Target factory — the ticket destination is config, not code.

`provider.target` in intakepilot.yaml (or INTAKEPILOT_TARGET) selects where
routed tickets go; the `targets:` section configures the chosen backend.
Every target implements the same one-method protocol (create_item).
"""
from __future__ import annotations

from core.config import Config


def make_target(cfg: Config):
    name = cfg.target_provider
    conf = cfg.targets.get(name, {})
    if name == "local":
        from core.targets.local import LocalTarget
        return LocalTarget(cfg.demo_repo)
    if name == "github":
        from core.targets.github import GitHubTarget
        return GitHubTarget(conf)
    if name == "jira":
        from core.targets.jira import JiraTarget
        return JiraTarget(conf)
    raise ValueError(f"unknown target provider: {name}")
