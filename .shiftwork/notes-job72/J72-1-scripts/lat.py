import json, sys, glob, statistics as st
from pathlib import Path
for f in sorted(glob.glob(sys.argv[1] + '/*.lat.json')):
    L = json.load(open(f))
    for v in ['Q0','Q1','Q2','Q3','Q4']:
        ms = sorted(x['ms'] for x in L if x['v'] == v)
        print(f"{Path(f).name[:-9]:26s} {v} n={len(ms)} p50={st.median(ms):6.1f} p90={ms[int(.9*len(ms))]:6.1f} max={ms[-1]:6.1f} >150ms={sum(m>150 for m in ms)} >100={sum(m>100 for m in ms)}")
