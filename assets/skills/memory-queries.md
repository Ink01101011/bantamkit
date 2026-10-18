# Likely-prompt queries

For each fact, write the prompts a user would type to a coding assistant when this fact is what they need.

- Three in the user's own language and three in English (`queries` holds all six, the user's language first).
- Short: 5 to 25 words. Vary them: one direct question, one task request, one terse follow-up.
- Keep technical terms in English where the user would: commands, file names, product names, error codes.
- Use only what the fact says. Do not invent facts, do not just restate the fact's name, and never copy more than
  five words of the body verbatim.

Store them with `memory_queries` (`{"facts": [{"name": ..., "layer": ..., "queries": [...]}]}`), or pass
`queries` to `memory_save` when you save the fact.
