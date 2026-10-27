# Memory

The runtime enforces format, dedupe, and budgets. You only decide WHEN and WHAT.

## Recall first

Before a task that resembles past work, call memory_recall with the words a
past-you would have used. Do this before acting, not after.

## When to save

- The user corrects you or states a preference → type "feedback"
- A durable fact about the user → "user", about ongoing work → "project",
  a URL/dashboard/ticket → "reference"
- Tag a lesson with outcome: error|success; close a project fact by saving it again with status: done.

## When NOT to save

- Anything derivable from the repo, git history, or docs
- One-off state that only matters in this conversation

## Writing the description

Write it to match the future recall QUERY, not to summarize the body.
Ask: "what words will future-me search with?" Put related memory names in links.
Fill keywords with the words the user will actually type, in their language — recall matches those too.

## Likely-prompt queries

When you save, also pass `queries`: three prompts in the user's language and three in English that a user would
type when this fact is what they need. Short and varied, technical terms kept in English, never more than five
words copied from the body. When `memory_queries` lists facts without queries, write theirs.

## On "duplicate" replies

If memory_save answers that a similar memory exists, either update it by
saving under that SAME name, or skip — never rename to force a second copy.

## Layers

Recall lines may start with `[project]`, `[extra:<name>]`, or `[profile]` —
where the fact came from. Prefer `[project]` when they conflict; saves always
go to the project store.
