import json, random, sys, yaml, yaml.scanner
random.seed(int(sys.argv[1]))
alpha = [' ', ' ', '\t', 'a', 'b', ':', ': ', '- ', '#', ' #', "'", '"', '[', ']', ', ', '\n', '\n', '\n  ', 'k: ', '\\']
docs = []
for _ in range(int(sys.argv[2])):
    docs.append(''.join(random.choice(alpha) for _ in range(random.randint(1, 14))))
out = []
for d in docs:
    try:
        yaml.safe_load(d); v = 'ok'
    except yaml.scanner.ScannerError as e:
        v = [e.problem_mark.line+1, e.problem_mark.column+1] if e.problem == "found character '\\t' that cannot start any token" else 'other'
    except yaml.YAMLError:
        v = 'other'
    out.append([d, v])
json.dump(out, sys.stdout)
