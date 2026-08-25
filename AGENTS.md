# Repository Agent Instructions

## Commit attribution

- Never identify an AI assistant, coding agent, model, bot, or AI vendor as a Git author, committer, or co-author.
- Never add a `Co-authored-by` trailer for an AI tool or agent.
- Preserve the repository's human-configured Git identity; do not replace or supplement it with an agent identity.
- Before committing, run `python3 scripts/check_agent_attribution.py --message-file <commit-message-file>` or rely on the configured `commit-msg` hook.
