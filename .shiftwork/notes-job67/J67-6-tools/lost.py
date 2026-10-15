import sys, pathlib, re
repo = pathlib.Path(sys.argv[1]); S = pathlib.Path(sys.argv[2])
pairs = [('old-root.md', 'README.md'), ('old-npm.md', 'runtime-ts/README.md'), ('old-pypi.md', 'runtime-py/README.md')]
norm = lambda s: re.sub(r'\s+', ' ', s).strip()
for old, new in pairs:
    o = (S/old).read_text(encoding='utf-8'); n = (repo/new).read_text(encoding='utf-8')
    nflat = norm(n)
    # items: paragraphs/bullets/table rows/code lines/headings, split on blank lines and list/table boundaries
    items = []
    for block in re.split(r'\n\s*\n', o):
        for part in re.split(r'\n(?=\s*(?:[-*] |\d+\. |\||#|```))', block):
            if part.strip(): items.append(norm(part))
    same = [i for i in items if i in nflat]
    diff = [i for i in items if i not in nflat]
    print(f'== {new}: {len(items)} old items, {len(same)} verbatim on the new page, {len(diff)} changed')
    for d in diff: print('  CHANGED:', d[:150])
