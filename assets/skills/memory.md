# Memory

The runtime enforces format, dedupe, and budgets. You only decide WHEN and WHAT.

## Recall first

Before a task that resembles past work, call memory_recall with the words a
past-you would have used. Do this before acting, not after.

## When to save

- The user corrects you or states a preference → type "feedback"
- A durable fact about the user → "user", about ongoing work → "project",
  a URL/dashboard/ticket → "reference"

## When NOT to save

- Anything derivable from the repo, git history, or docs
- One-off state that only matters in this conversation

## Writing the description

Write it to match the future recall QUERY, not to summarize the body.
Ask: "what words will future-me search with?" Put related memory names in links.

## On "duplicate" replies

If memory_save answers that a similar memory exists, either update it by
saving under that SAME name, or skip — never rename to force a second copy.

## Layers

Recall results may be prefixed with their origin: `[project]` (this folder's
store), `[extra:<name>]` (a read-only store this project was explicitly
granted), or `[profile]` (your user-wide store). When facts conflict, prefer
`[project]` — it is the closest to the work. Saves always go to the project
store; the other layers are read-only.
