// Link + anchor checker for the three READMEs. Usage: node links.mjs <repo> [--external]
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { marked } from 'marked';
import GithubSlugger from 'github-slugger';
const repo = process.argv[2];
const external = process.argv.includes('--external');
const BLOB = 'https://github.com/Ink01101011/bantamkit/blob/main/';
const TREE = 'https://github.com/Ink01101011/bantamkit/tree/main/';
const anchorCache = new Map();
const unesc = (s) => String(s).replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
function plain(tokens) { return (tokens || []).map((t) => t.tokens ? plain(t.tokens) : unesc(t.text ?? t.raw)).join(''); }
function anchorsOf(file) {
  if (anchorCache.has(file)) return anchorCache.get(file);
  const md = readFileSync(file, 'utf8');
  const slugger = new GithubSlugger();
  const ids = new Set();
  const walk = (toks) => { for (const t of toks) {
    if (t.type === 'heading') ids.add(slugger.slug(plain(t.tokens)));
    if (t.type === 'html' || t.type === 'paragraph') for (const m of (t.raw).matchAll(/<a\s+id="([^"]+)"/g)) ids.add(m[1]);
    if (t.tokens && t.type !== 'heading') walk(t.tokens);
    if (t.items) walk(t.items);
  } };
  walk(marked.lexer(md));
  anchorCache.set(file, ids); return ids;
}
function linksOf(file) {
  const md = readFileSync(file, 'utf8'); const out = [];
  const walk = (toks) => { for (const t of toks) {
    if (t.type === 'link' || t.type === 'image') out.push({ href: t.href, kind: t.type });
    if (t.type === 'html' || t.type === 'paragraph' || t.type === 'text') for (const m of (t.raw).matchAll(/<a\s+href="([^"]+)"/g)) out.push({ href: m[1], kind: 'html' });
    if (t.tokens) walk(t.tokens); if (t.items) walk(t.items);
    if (t.type === 'table') { for (const c of t.header) walk(c.tokens); for (const r of t.rows) for (const c of r) walk(c.tokens); }
  } };
  walk(marked.lexer(md)); return out;
}
const pages = ['README.md', 'runtime-ts/README.md', 'runtime-py/README.md'];
const ext = new Set(); let total = 0, failed = 0; const report = [];
for (const page of pages) {
  const abs = join(repo, page); const links = linksOf(abs); let n = 0, bad = 0, inpage = 0, rel = 0, absl = 0;
  for (const { href, kind } of links) {
    n++; total++;
    let target = null, frag = null, why = null;
    if (href.startsWith('#')) { inpage++; target = abs; frag = decodeURIComponent(href.slice(1)); }
    else if (href.startsWith(BLOB) || href.startsWith(TREE)) { absl++; const rest = href.slice(BLOB.length); const [p, f] = rest.split('#'); target = join(repo, p); frag = f ? decodeURIComponent(f) : null; ext.add(href.split('#')[0]); }
    else if (/^https?:/.test(href)) { absl++; ext.add(href); continue; }
    else { rel++; if (page !== 'README.md') { why = 'relative link on a registry page'; } const [p, f] = href.split('#'); target = resolve(dirname(abs), p); frag = f ? decodeURIComponent(f) : null; }
    if (!why && !existsSync(target)) why = 'missing file ' + target.replace(repo + '/', '');
    if (!why && frag !== null) { if (!target.endsWith('.md')) why = 'fragment on non-md'; else if (!anchorsOf(target).has(frag)) why = 'missing anchor #' + frag + ' in ' + target.replace(repo + '/', ''); }
    if (why) { bad++; failed++; report.push(`${page}: ${href} -> ${why}`); }
  }
  console.log(`${page}: ${n} links (${inpage} in-page, ${rel} relative, ${absl} absolute), ${bad} failed`);
}
for (const r of report) console.log('FAIL ' + r);
writeFileSync(new URL('./external.txt', import.meta.url), [...ext].sort().join('\n') + '\n');
console.log(`TOTAL ${total} links, ${failed} failed; ${ext.size} unique external URLs written to external.txt`);
