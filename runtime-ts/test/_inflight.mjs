/**
 * An expired-wait appender caught mid-flight (#208 items 2-3), for the rewrite tests.
 *
 * It is a separate PROCESS, because the rewrite under test is synchronous and blocks this
 * one. The caller creates the appender's marker `<log>.<pid>.<hex>.writing` first, as an
 * unlocked `append` does before it opens the log; the child then waits for the rewrite's
 * `.keep` link to name a file the log no longer is (the rename happened), appends `chunks` to
 * that old file one write at a time, and removes the marker, as the appender does once its
 * line is written. The rewrite must carry every byte over.
 */
import { spawn } from 'node:child_process';

const CHILD = `
const fs = require('node:fs');
const path = require('node:path');
const [log, mark, ...chunks] = process.argv.slice(1);
const dir = path.dirname(log);
const deadline = Date.now() + 10000;
const nap = () => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1);
for (;;) {
  if (Date.now() > deadline) break;
  try {
    const keep = fs.readdirSync(dir).find((n) => n.endsWith('.keep'));
    if (keep && fs.statSync(path.join(dir, keep)).ino !== fs.statSync(log).ino) {
      const fd = fs.openSync(path.join(dir, keep), 'a');
      for (const c of chunks) fs.writeSync(fd, Buffer.from(c, 'base64'));
      fs.closeSync(fd);
      break;
    }
  } catch {}
  nap();
}
fs.rmSync(mark, { force: true });
`;

/** Start the appender; await the returned promise after the rewrite returns. */
export function inflight(log, mark, chunks) {
  const child = spawn(process.execPath, ['-e', CHILD, log, mark, ...chunks.map((c) => Buffer.from(c).toString('base64'))], {
    stdio: 'ignore',
  });
  return new Promise((resolve) => child.on('exit', resolve));
}
