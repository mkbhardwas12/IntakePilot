#!/usr/bin/env python3
"""Reject commit metadata that would credit an AI agent as a contributor."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


AGENT_IDENTITY = re.compile(
    r"(?:"
    r"\bclaude(?:\s+(?:code|fable)(?:\s+\d+)?)?\b|"
    r"\bcursor(?:\s+agent)?\b|"
    r"\b(?:github\s+)?copilot(?:\s+agent)?\b|"
    r"\bchatgpt\b|"
    r"\bopenai(?:\s+codex)?\b|"
    r"\bcodex(?:\s+cli)?\b|"
    r"\bgemini(?:\s+(?:cli|code\s+assist))?\b|"
    r"\bdevin\s+ai\b|"
    r"\bwindsurf(?:\s+agent)?\b|"
    r"\bcline\b|"
    r"\baider\b|"
    r"\broo\s+code\b|"
    r"\bamazon\s+q\b|"
    r"\bai[ -]?agent\b|"
    r"[^\s<>]+\[bot\]|"
    r"cursoragent@cursor\.com|"
    r"(?:noreply@)?anthropic\.com"
    r")",
    re.IGNORECASE,
)
COAUTHOR_TRAILER = re.compile(
    r"^[ \t]*co-authored-by[ \t]*:[ \t]*(?P<identity>.+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"


@dataclass(frozen=True)
class Commit:
    commit_hash: str
    author: str
    committer: str
    message: str


def agent_attributions(commit: Commit) -> list[str]:
    findings: list[str] = []
    if AGENT_IDENTITY.search(commit.author):
        findings.append(f"author {commit.author}")
    if AGENT_IDENTITY.search(commit.committer):
        findings.append(f"committer {commit.committer}")
    for match in COAUTHOR_TRAILER.finditer(commit.message):
        identity = match.group("identity")
        if AGENT_IDENTITY.search(identity):
            findings.append(f"co-author {identity}")
    return findings


def commits_from_git(revisions: Iterable[str]) -> list[Commit]:
    fields = FIELD_SEPARATOR.join(
        ("%H", "%an <%ae>", "%cn <%ce>", "%B")
    )
    result = subprocess.run(
        ["git", "log", *revisions, f"--format={RECORD_SEPARATOR}{fields}"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git log failed")
    commits: list[Commit] = []
    for record in result.stdout.split(RECORD_SEPARATOR):
        if not record.strip():
            continue
        parts = record.rstrip("\n").split(FIELD_SEPARATOR, maxsplit=3)
        if len(parts) != 4:
            raise RuntimeError("could not parse git log output")
        commit_hash, author, committer, message = parts
        commits.append(Commit(commit_hash, author, committer, message))
    return commits


def pending_commit(message_file: Path) -> Commit:
    def git_identity(variable: str) -> str:
        result = subprocess.run(
            ["git", "var", variable],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return Commit(
        commit_hash="pending commit",
        author=git_identity("GIT_AUTHOR_IDENT"),
        committer=git_identity("GIT_COMMITTER_IDENT"),
        message=message_file.read_text(encoding="utf-8"),
    )


def check(commits: Iterable[Commit]) -> int:
    failures = [
        (commit.commit_hash, finding)
        for commit in commits
        for finding in agent_attributions(commit)
    ]
    if not failures:
        print("No AI-agent contributor attribution found.")
        return 0

    print("AI-agent contributor attribution is forbidden:", file=sys.stderr)
    for commit_hash, finding in failures:
        print(f"  {commit_hash}: {finding}", file=sys.stderr)
    print(
        "Remove agent author/committer identities and agent Co-authored-by trailers.",
        file=sys.stderr,
    )
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--all", action="store_true", help="check every commit reachable from any ref"
    )
    source.add_argument(
        "--message-file", type=Path, help="check a pending commit message"
    )
    parser.add_argument("revisions", nargs="*", help="git revisions to inspect")
    args = parser.parse_args()
    if args.all and args.revisions:
        parser.error("--all cannot be combined with revisions")
    if args.message_file and args.revisions:
        parser.error("--message-file cannot be combined with revisions")
    return args


def main() -> int:
    args = parse_args()
    if args.message_file:
        commits = [pending_commit(args.message_file)]
    else:
        revisions = ["--all"] if args.all else args.revisions or ["HEAD"]
        commits = commits_from_git(revisions)
    return check(commits)


if __name__ == "__main__":
    raise SystemExit(main())