#!/bin/bash
# J66-7 (#118 remainder) probe. Rerun from the repo root:  bash .shiftwork/notes-job66/J66-7-probe.sh
# Seeds ~/.cursor/mcp.json and ~/.claude/settings.json (4-space indent, then a tab) holding Thai,
# an emoji and five escape spellings, runs `--install cursor` and `--install-hooks --yes` on both
# runtimes in a throwaway HOME each, asserts the redirect from each report, and prints the head
# of each written file plus whether the two sides' files are equal with the ruled command masked.
set -u
R=$(pwd); T=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/j66-7-probe.XXXXXX")" && pwd -P)
for UNIT in '    ' $'\t'; do
  for side in py node; do
    H="$T/$side"; rm -rf "$H"; mkdir -p "$H/.cursor" "$H/.claude"
    for f in "$H/.cursor/mcp.json" "$H/.claude/settings.json"; do
      "$R/.venv/bin/python" -I - "$f" "$UNIT" <<'PY'
import sys
seed = ('{\n»"mcpServers": {\n»»"other": {\n»»»"command": "x",\n'
        '»»»"env": {"K": "ไทย 🎉", "E": "\\u0e01", "L": "\\ud800", "B": "\\\\u0e01", '
        '"D": "\\u007f", "S": "\\u2028"}\n»»}\n»},\n»"note": "สวัสดี"\n}\n')
with open(sys.argv[1], 'w', encoding='utf-8') as fh:
    fh.write(seed.replace('»', sys.argv[2]))
PY
    done
  done
  printf '== indent unit %q\n' "$UNIT"
  HOME=$T/py USERPROFILE=$T/py "$R/.venv/bin/bantamkit-mcp" --install cursor >"$T/py.out" 2>&1; echo "py --install exit $?"
  HOME=$T/node USERPROFILE=$T/node node "$R/runtime-ts/dist/cli.js" --install cursor >"$T/node.out" 2>&1; echo "node --install exit $?"
  HOME=$T/py USERPROFILE=$T/py "$R/.venv/bin/bantamkit-mcp" --install-hooks --yes >>"$T/py.out" 2>&1; echo "py --install-hooks exit $?"
  HOME=$T/node USERPROFILE=$T/node node "$R/runtime-ts/dist/cli.js" --install-hooks --yes >>"$T/node.out" 2>&1; echo "node --install-hooks exit $?"
  grep -q "$T/py/" "$T/py.out" && grep -q "$T/node/" "$T/node.out" && echo "redirect asserted from both reports" || { echo "REDIRECT NOT ASSERTED"; exit 1; }
  "$R/.venv/bin/python" -I - "$T" <<'PY'
import re, sys
t = sys.argv[1]
def mask(text):
    text = re.sub(r'^([ \t]+)"bantamkit": \{\n[\s\S]*?\n\1\}', r'\1"bantamkit": <ENTRY>', text, flags=re.M)
    return re.sub(r'"command": "[^"\n]*--hook"', '"command": <HOOK>', text)
for f in ('.cursor/mcp.json', '.claude/settings.json'):
    a, b = (open(f'{t}/{s}/{f}', encoding='utf-8').read() for s in ('py', 'node'))
    print(f, '| equal with the ruled command masked:', mask(a) == mask(b),
          '| Thai literal on both:', all('"K": "ไทย 🎉"' in x and '"E": "ก"' in x for x in (a, b)))
    print('   ' + repr(a[:160]))
PY
done
rm -rf "$T"
