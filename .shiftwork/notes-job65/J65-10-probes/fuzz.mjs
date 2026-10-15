import { readFileSync } from 'node:fs';
const { firstTokenTab } = await import(new URL('../../../runtime-ts/dist/memory/layers.js', import.meta.url).href);
const rows = JSON.parse(readFileSync(0, 'utf8'));
let agree = 0, tabMismatch = [], falseRefuse = [], otherButTab = 0;
for (const [d, v] of rows) {
  const t = firstTokenTab(d);
  if (Array.isArray(v)) { if (t && t[0] === v[0] && t[1] === v[1]) agree++; else tabMismatch.push([d, v, t]); }
  else if (v === 'ok') { if (t === null) agree++; else falseRefuse.push([d, t]); }
  else { if (t) otherButTab++; else agree++; }
}
console.log(JSON.stringify({ n: rows.length, agree, tabMismatch: tabMismatch.length, falseRefuse: falseRefuse.length, otherButTab }));
console.log(JSON.stringify(tabMismatch.slice(0, 8)));
console.log(JSON.stringify(falseRefuse.slice(0, 8)));
