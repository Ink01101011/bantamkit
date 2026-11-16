/**
 * Retention's archive write, the one place it reaches the disk's durability (#204, S4; J69-8).
 *
 * Moved out of `retention.ts` unchanged (#316 G4, J90-3) so that module can be compiled by
 * `tools/ts2py` while this one stays an ADAPTER onto CPython: the reference's `_write_archive` and
 * `_fsync_dir` (`bantamkit.storage.retention`), whose `os.fsync` / `os.replace` are the syscalls
 * Node's binding makes. A test swaps `writeArchive` to make the write fail.
 *
 * The archive's one write, temp then rename, flushed to the disk. The originals are deleted only
 * after the archive is read back, and a read-back is served from the page cache: without `fsync`
 * a power cut after the unlinks could leave neither the archive nor the files it held (J69-8).
 * `syncs` counts the file and directory syncs made.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';

export const retentionFs = {
  syncs: 0,
  writeArchive(target: string, data: Buffer): void {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const tmp = path.join(path.dirname(target), `${path.basename(target)}.${process.pid}.tmp`);
    // Compressed BEFORE the temp is opened (J90-3F): a temp is never left idle while this writer
    // lives, so a later run's stale-temp sweep (`removeStaleTemps`, the lock's window) never
    // meets a live one.
    const gz = zlib.gzipSync(data);
    try {
      const fd = fs.openSync(tmp, 'w');
      try {
        writeAll(fd, gz);
        fs.fsyncSync(fd);
        retentionFs.syncs += 1;
      } finally {
        fs.closeSync(fd);
      }
      fs.renameSync(tmp, target);
      fsyncDir(path.dirname(target));
    } catch (e) {
      fs.rmSync(tmp, { force: true });
      throw e;
    }
  },
};

/**
 * Every byte of `data`, or a throw (J90-3: the write was one `writeSync`, whose short count, under
 * `ulimit -f` say, went unread, so a truncated archive was renamed into place, failed to verify,
 * and stayed there: every later run refused the job as `archive exists and differs`. The
 * reference's `fh.write` writes all or raises; `logsegment.ts`'s `writeAll` is the same loop).
 */
function writeAll(fd: number, data: Buffer): void {
  let done = 0;
  while (done < data.length) {
    const n = fs.writeSync(fd, data.subarray(done));
    // write(2) answers 0 only for an empty buffer; never spin on one that answers 0 anyway
    if (n <= 0) throw Object.assign(new Error('EIO: i/o error, write wrote no bytes'), { code: 'EIO' });
    done += n;
  }
}

/** Make a rename durable. POSIX only: Windows cannot open a directory for fsync. */
function fsyncDir(d: string): void {
  if (process.platform === 'win32') return;
  let fd: number;
  try {
    fd = fs.openSync(d, 'r');
  } catch {
    return;
  }
  try {
    fs.fsyncSync(fd);
    retentionFs.syncs += 1;
  } catch {
    /* best effort */
  } finally {
    fs.closeSync(fd);
  }
}
