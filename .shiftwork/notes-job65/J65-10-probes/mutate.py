# usage: mutate.py FILE OLD NEW SUITE -> applies, runs suite, restores (exact-string), prints summary
import subprocess, sys, os
f, old, new, suite = sys.argv[1:5]
src = open(f, encoding='utf-8').read()
assert src.count(old) == 1, ('anchor count', src.count(old))
open(f, 'w', encoding='utf-8').write(src.replace(old, new))
try:
    env = dict(os.environ, TMPDIR='' + os.environ.get('CLEAN_TMPDIR', '/tmp') + '')
    out = subprocess.run(['node', 'tools/conformance/run.mjs', '--suite', suite], capture_output=True, text=True, encoding='utf-8', env=env).stdout
finally:
    cur = open(f, encoding='utf-8').read()
    open(f, "w", encoding="utf-8").write(src)
print([l for l in out.splitlines() if l.startswith(('PASS', 'FAIL'))])
