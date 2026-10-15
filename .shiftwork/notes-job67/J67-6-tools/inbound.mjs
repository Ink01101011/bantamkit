// Every `README.md#frag` reference in tracked files (code, tests, docs) that points at one of the three pages.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join, dirname, resolve, relative } from 'node:path';
import { marked } from 'marked';
import GithubSlugger from 'github-slugger';
const repo = process.argv[2]; const listFrom = process.argv[3] ?? repo;
const unesc = (s) => String(s).replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
const plain = (ts) => (ts || []).map((t) => t.tokens ? plain(t.tokens) : unesc(t.text ?? t.raw)).join('');
function anchors(file) { const sl = new GithubSlugger(); const ids = new Set(); const md = readFileSync(file, 'utf8');
  const walk = (toks) => { for (const t of toks) { if (t.type === 'heading') ids.add(sl.slug(plain(t.tokens))); if (t.type === 'html' || t.type === 'paragraph') for (const m of t.raw.matchAll(/<a\s+id="([^"]+)"/g)) ids.add(m[1]); if (t.tokens && t.type !== 'heading') walk(t.tokens); if (t.items) walk(t.items); } };
  walk(marked.lexer(md)); return ids; }
const pages = { 'README.md': anchors(join(repo, 'README.md')), 'runtime-ts/README.md': anchors(join(repo, 'runtime-ts/README.md')), 'runtime-py/README.md': anchors(join(repo, 'runtime-py/README.md')) };
const files = execFileSync('git', ['-C', listFrom, 'ls-files'], { encoding: 'utf8' }).split('\n').filter((f) => f && !f.startsWith('docs/eval-data/') && !f.startsWith('.shiftwork/'));
let n = 0, bad = 0;
for (const f of files) {
  let text; try { text = readFileSync(join(repo, f), 'utf8'); } catch { continue; }
  for (const m of text.matchAll(/((?:\.\.\/)*(?:runtime-ts\/|runtime-py\/)?README\.md)#([A-Za-z0-9_-]+)/g)) {
    let target = m[1];
    if (f.endsWith('.md')) target = relative(repo, resolve(dirname(join(repo, f)), m[1]));
    else if (!m[1].includes('/')) target = f.startsWith('runtime-ts/') ? 'runtime-ts/README.md' : f.startsWith('runtime-py/') ? 'runtime-py/README.md' : 'README.md';
    if (!(target in pages) && (m[1] in pages)) target = m[1];
    if (f === 'tools/conformance/suites/cli.mjs' && m[1] === 'README.md') target = 'runtime-ts/README.md'; // prose about the npm page: only it ever had this heading
    if (!(target in pages)) continue;
    n++;
    const ok = pages[target].has(m[2]);
    if (!ok) bad++;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${f} -> ${target}#${m[2]}`);
  }
}
console.log(`INBOUND ${n} references, ${bad} unresolved`);
