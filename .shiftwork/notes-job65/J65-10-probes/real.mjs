import { readFileSync, writeFileSync } from 'node:fs';
const { loadGrants } = await import(new URL('../../../runtime-ts/dist/memory/layers.js', import.meta.url).href);
const { bed, rows } = JSON.parse(readFileSync(0, 'utf8'));
const c = { same: 0, bothRefuseDiffSentence: 0, verdictDiffers: [], tabSentenceDiff: [] , tabRows: 0};
for (const [t, py] of rows) {
  writeFileSync(`${bed}/p/.bantamkit/config.yaml`, t);
  let nd; try { nd = ['ok', loadGrants(`${bed}/p/.bantamkit/memory`)]; } catch (e) { nd = ['err', e.message]; }
  const hasTab = t.includes("\t");
  if (hasTab) c.tabRows++;
  if (JSON.stringify(nd) === JSON.stringify(py)) c.same++;
  else if (nd[0] !== py[0]) c.verdictDiffers.push([t, py, nd]);
  else { c.bothRefuseDiffSentence++; if (/a tab cannot/.test(py[1]) || /a tab cannot/.test(nd[1])) c.tabSentenceDiff.push([t, py[1], nd[1]]); }
}
console.log(JSON.stringify({ n: rows.length, tabRows: c.tabRows, same: c.same, bothRefuseDiffSentence: c.bothRefuseDiffSentence, verdictDiffers: c.verdictDiffers.length, tabSentenceDiff: c.tabSentenceDiff.length }));
console.log(JSON.stringify(c.verdictDiffers.slice(0, 5)));
console.log(JSON.stringify(c.tabSentenceDiff.slice(0, 5)));
const vt = c.verdictDiffers.filter(([t]) => t.includes('\t'));
console.log('verdictDiffers with a tab:', vt.length, JSON.stringify(vt.slice(0,3).map(([t,p,n])=>[t,p[0],n[0]])));
