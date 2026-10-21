import json, sys
from pathlib import Path
sys.path.insert(0, '.')
import lib
C, N = Path(sys.argv[1]), Path(sys.argv[2])
d = lib.Data(C, N)
bad = [ (it['set'], it['key']) for it in d.items if lib.policy(it, d.names[it['native']], None, 'BASE-B', {}) != it['product_inject']]
print('BASE-B == product inject_candidates:', len(d.items) - len(bad), 'of', len(d.items), bad[:5])
emb = json.loads(Path(sys.argv[3]).read_text())
mis = []
for it in d.items:
    if it['set'] != 'gold': continue
    c = d.cos('bge-m3', 'T0', 'Q0', it)
    got = lib.policy(it, d.names[it['native']], c, 'BASE-E', {'g': 0.6})
    if got != emb[str(it['key'])]['embed']: mis.append(it['key'])
print('BASE-E(bge-m3,T0,Q0) == J71-5 gold embed lists:', 50 - len(mis), 'of 50', mis)
# silver: reproduce J71-5 tuning-embed gate 0.6 (already-known number)
sil = [it for it in d.items if it['set'] == 'silver']
inj = {it['key']: lib.policy(it, d.names[it['native']], d.cos('bge-m3','T0','Q0',it), 'BASE-E', {'g': 0.6}) for it in sil}
gold = {i: set(r['positives']) for i, r in enumerate(d.silver)}
thai = {i for i, r in enumerate(d.silver) if r['thai']}
print('silver BASE-E', lib.metrics(inj, gold, thai))
inj = {it['key']: lib.policy(it, d.names[it['native']], None, 'BASE-B', {}) for it in sil}
print('silver BASE-B', lib.metrics(inj, gold, thai))
