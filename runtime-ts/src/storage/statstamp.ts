/**
 * The stat reads the hot index makes on every refresh, each answered as the values it reads
 * (#316 G4, J90-PF). Not compiled by `tools/ts2py`: each function is an ADAPTER row
 * (`tools/ts2py-bantamkit/ts2py.toml`), answered in Python from `os.stat` without building the
 * `BigIntStats` object these build, so a held query's refresh costs the generated Python what
 * the hand-written index paid.
 */
import * as fs from 'node:fs';

/** `${mtimeNs}:${size}:${ino}` of `fs.statSync(p, { bigint: true })`: the head's stamp. */
export function statStamp(p: string): string {
  const st = fs.statSync(p, { bigint: true });
  return `${st.mtimeNs}:${st.size}:${st.ino}`;
}

/** `fs.statSync(p, { bigint: true }).mtimeNs` as its decimal: a directory's stamp. */
export function statMtimeNs(p: string): string {
  return fs.statSync(p, { bigint: true }).mtimeNs.toString();
}

/**
 * `[mtimeNs.toString(), Number(size), isFile()]` of `fs.statSync(p, { bigint: true })`: what a
 * listing row reads of each file it states.
 */
export function statFile(p: string): [string, number, boolean] {
  const st = fs.statSync(p, { bigint: true });
  return [st.mtimeNs.toString(), Number(st.size), st.isFile()];
}
