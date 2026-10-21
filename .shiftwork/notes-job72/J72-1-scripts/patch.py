import sys, pathlib
root, what = pathlib.Path(sys.argv[1]), sys.argv[2]
if what in ("lazynet", "both"):
    p = root / "runtime-ts/src/memory/embed.ts"; s = p.read_text()
    s = s.replace("import * as http from 'node:http';\nimport * as https from 'node:https';\n", "", 1)
    old = "function post(parts: HostParts, body: Buffer, timeoutMs: number): Promise<{ status: number; body: Buffer }> {\n  return new Promise((resolveP, rejectP) => {\n    const lib = parts.scheme === 'https' ? https : http;\n"
    new = "async function post(parts: HostParts, body: Buffer, timeoutMs: number): Promise<{ status: number; body: Buffer }> {\n  const lib = parts.scheme === 'https' ? await import('node:https') : await import('node:http');\n  return new Promise((resolveP, rejectP) => {\n"
    assert old in s; s = s.replace(old, new, 1); p.write_text(s)
if what in ("noawait", "both"):
    p = root / "runtime-ts/src/hookadapter.ts"; s = p.read_text()
    old = "  const scorer = await m.prepare(prompt);\n"
    assert old in s
    s = s.replace(old, "  const scorer = offScorer(m.embed) ?? (await m.prepare(prompt));\n", 1)
    s = "import { offScorer } from './memory/embed.js';\n" + s
    p.write_text(s)
