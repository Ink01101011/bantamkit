import json, random, sys, os, tempfile
sys.path.insert(0, '/Users/kktest/Documents/Claude/Projects/bantamkit/runtime-py/src')
from bantamkit.memory.layers import load_grants
random.seed(int(sys.argv[1]))
base = ['extra_stores:', '  - a', "  - 'a'", '  - "a"', 'k: v', '# c', 'k2: [a, b]', 'e: [a]', 'x: 1  # note']
bed = tempfile.mkdtemp(dir=sys.argv[3])
os.makedirs(f'{bed}/p/.bantamkit/memory'); os.makedirs(f'{bed}/p/.bantamkit/a')
out = []
for _ in range(int(sys.argv[2])):
    lines = random.sample(base, random.randint(1, 4))
    if 'extra_stores:' not in lines: lines.insert(0, 'extra_stores:')
    t = '\n'.join(lines) + '\n'
    for _ in range(random.randint(0, 2)):
        i = random.randrange(len(t))
        t = t[:i] + random.choice(['\t', '\t', ' \t', '\t ']) + t[i:] if random.random() < .6 else t.replace(' ', '\t', 1)
    open(f'{bed}/p/.bantamkit/config.yaml', 'w', encoding='utf-8').write(t)
    try: r = ['ok', [str(g) for g in load_grants(f'{bed}/p/.bantamkit/memory')]]
    except Exception as e: r = ['err', str(e)]
    out.append([t, r])
json.dump({'bed': bed, 'rows': out}, sys.stdout)
