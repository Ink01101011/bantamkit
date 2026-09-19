---
name: npm-publish-0-26-0-blocked-on-login
description: bantamkit release state — 0.31.0 is fully out on npm, PyPI, tag and GitHub
  release; plus the three release steps this session could not run itself and the
  working remedy
type: project
created: '2026-09-05'
last_recalled: '2026-09-19'
links: []
---

0.31.0 FULLY RELEASED 2026-09-11: npm bantamkit-mcp 0.31.0 (shasum 03367654d5c0f64e1d35ac4818f737ea90d30281, matching npm pack --dry-run before publish), PyPI bantamkit 0.31.0, tag v0.31.0 -> 5e2508b, GitHub release, PR 93 merged. Gates at the released tree: pytest 2829, ruff clean, npm 908 tests/906 pass, conformance 7517 cases / 156 ruled-different / 0 failures.

WHAT THE SESSION COULD NOT RUN, and the reasons differ — do not conflate them:
- `git tag` and `gh release` are DENY-RULED in the user's own settings; the tool layer refuses even read-only `gh release view`. Verbal authorization in chat does NOT lift this. Never edit ~/.claude/settings.json to route around it, and never use `gh release create` to create a tag that `git tag` was denied.
- `npm publish` is NOT permission-denied. It fails on AUTH twice over: logged out gives E401/E404-PUT, and after `npm login` (browser flow, works headless) it still gives EOTP because 2FA requires an authenticator code only the user can read.

THE REMEDY THAT WORKED: write one script doing tag -> gh release -> npm login/publish, have the user run it with `! bash <script>`. Put release notes in a SEPARATE file and use `gh release create --notes-file` — an apostrophe in the notes breaks a `$(cat <<'X' ...)` heredoc, and `bash -n` catches it before handing the script over. Publish finishes with `npm publish --access public --otp=<code>`; never write an example 6-digit code, write a placeholder.

Build: `cd runtime-py && <repo>/.venv/bin/python -m build && ~/.local/bin/twine upload dist/*` — the ~/.pypirc token works, and runtime-py has NO .venv of its own, use the repo root's. PyPI's /pypi/<name>/json "latest" is CACHED and lags; check /pypi/<name>/<version>/json.</body>
<links>["merge-authorized-standing-tag-withheld", "otp-prompts-cannot-be-answered-in-the-bang-channel", "every-change-ships-to-npm-not-just-to-main"]</links>
</invoke>
