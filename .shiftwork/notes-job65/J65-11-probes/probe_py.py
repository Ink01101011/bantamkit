import json, sys, datetime, yaml
def j(v):
    if isinstance(v, dict): return {k: j(x) for k, x in v.items()}
    if isinstance(v, list): return [j(x) for x in v]
    if isinstance(v, (datetime.date, datetime.datetime)): return f"<python {type(v).__name__} {v.isoformat()}>"
    if isinstance(v, bool): return f"<python bool {v}>"
    if isinstance(v, (int, float)): return f"<python {type(v).__name__} {v}>"
    return v
out = []
for f in json.load(sys.stdin):
    try: out.append({"ok": j(yaml.safe_load(f))})
    except Exception as e: out.append({"err": type(e).__name__ + ": " + str(e).splitlines()[0]})
json.dump(out, sys.stdout)
