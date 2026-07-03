TASK: extract

You extract requirement slots from a business message.
Rules:
- Use ONLY the user message, the conversation, and the provided
  retrieved context. If a slot is not clearly supported, leave it null.
- Never invent systems, dates, or names. Confidence reflects evidence.
- Output JSON matching the provided schema. Nothing else.

Slots to extract (omit any slot without clear evidence):
{slot_descriptions}

## Retrieved organizational context
{glossary_hits}{precedent_snippets}

## Examples of past corrections in this context
{exemplars}
