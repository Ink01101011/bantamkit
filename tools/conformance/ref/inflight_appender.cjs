/**
 * An expired-wait appender caught mid-flight (#208 items 2-3), for `storage-lock`.
 *
 * usage: node inflight_appender.cjs <log> <marker> <b64 chunk>...
 *
 * BOTH sides of the suite start this same script, so the appender is not one of the two
 * implementations under test. The caller has created `<marker>` (as an unlocked `append` does
 * before it opens the log); this waits for the rewrite's `.keep` link to name a file the log no
 * longer is (the rename happened), appends each chunk to that old file in its own write, and
 * removes the marker, as the appender does once its line is written. Gives up after 10 s.
 */
const fs = require('node:fs');
const path = require('node:path');

const [log, mark, ...chunks] = process.argv.slice(2);
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
  } catch {
    /* the rewrite is not there yet */
  }
  nap();
}
fs.rmSync(mark, { force: true });
