import json, sys
from pathlib import Path
sys.path.insert(0, '.')
import search_rules as S
rows = [json.loads(x) for x in open(sys.argv[1], encoding="utf-8")]
c = [r for r in rows if r['kind'] != 'BASE-B']
def show(tag, r):
    if r is None: print(f"{tag:28s} none"); return
    print(f"{tag:28s} {r['kind']:6s} {json.dumps(r['p']):28s} {str(r['model']):22s} {r['T']} {r['Q']}  p={r['precision_at_inject']:.4f} r3={r['recall_at_3']:.4f} th={r['thai_recall_at_3']:.4f} inj={r['injected']}")
show('BASE-B', rows[0])
for k in ['BASE-E','1a','1b','1c','1d','2a','2b','2c','2d']:
    w, cl = S.best([r for r in c if r['kind'] == k]); show(f'kind {k} (cl {cl})', w)
for f in ['F1','F2']:
    w, cl = S.best([r for r in c if S.fam(r) == f]); show(f'family {f} (cl {cl})', w)
for ax, vals in [('model', S.lib.MODELS), ('T', S.lib.TEXTS), ('Q', S.lib.QUERIES)]:
    for v in vals:
        w, cl = S.best([r for r in c if r[ax] == v]); show(f'{ax}={v} (cl {cl})', w)
w, cl = S.best([r for r in c if r['model']=='bge-m3' and r['T']=='T0' and r['Q']=='Q0']); show('shipped inputs', w)
w, cl = S.best(c); show(f'WINNER (cl {cl})', w)
# top 15 overall by objective
feas = sorted([r for r in c if S.okbase(r) and r['recall_at_3'] >= S.R_B-1e-12], key=lambda r: (-r['precision_at_inject'], -r['recall_at_3'], r['injected'], S.simple(r)))
print('--- top 15 feasible')
for r in feas[:15]: show('', r)
