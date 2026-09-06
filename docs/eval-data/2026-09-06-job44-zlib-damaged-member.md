# U14 — roadmap row 8 (s): the damaged-member cause clause, measured

Unit U14 of job44 (`fix/job44-register-drain`). Investigation only: no runtime code changed.
Ran 2026-09-06 on macOS 26.5.2 (Darwin 25.5.0), arm64. Node v25.2.1, CPython 3.12.13.

## Verdict

Two answers, because the register entry names a *mechanism* and asks a *question*, and they
come apart:

| | |
|---|---|
| The mechanism entry (s) names — CPython's `zlib_error` taking its **null-`zst.msg`** branch | **UNREACHABLE** from a zip member. Proof below; 0 occurrences in 8,037 constructed inputs, and a branch argument that says why the count is not luck. |
| The question entry (s) exists to answer — *does the port reproduce the reference's damaged-member cause clause for every cause zlib names?* | **POSITIVE-DIFFER.** It does not, on this machine, for **803 of 6,306** inputs where both sides raise (12.7 %). Cause is not the null-`msg` branch: the two runtimes link **different zlib builds**, and Apple's system `libz` emits a message string that exists in no upstream zlib. Fixture and both sentences below. |

So the entry does **not** close as unreachable. It closes as a *measured divergence with a
different cause than the one predicted*, and — see "Why no conformance case" — one that cannot
be pinned by a case, because its expected value is a function of the host's `libz`.

## 1. The CPython branch analysis

`Modules/zlibmodule.c` (3.12 branch, fetched — see commands):

```c
static void
zlib_error(zlibstate *state, z_stream zst, int err, const char *msg)
{
    const char *zmsg = Z_NULL;
    if (err == Z_VERSION_ERROR)            zmsg = "library version mismatch";
    if (zmsg == Z_NULL)                    zmsg = zst.msg;
    if (zmsg == Z_NULL) {
        switch (err) {
        case Z_BUF_ERROR:    zmsg = "incomplete or truncated stream"; break;
        case Z_STREAM_ERROR: zmsg = "inconsistent stream state";      break;
        case Z_DATA_ERROR:   zmsg = "invalid input data";             break;
        }
    }
    if (zmsg == Z_NULL) PyErr_Format(state->ZlibError, "Error %d %s", err, msg);
    else                PyErr_Format(state->ZlibError, "Error %d %s: %.200s", err, msg, zmsg);
}
```

Note the null-`msg` sentence is `Error %d %s` — **no colon and no cause clause at all**
(`Error -4 while decompressing data`). The three fixed strings are the *fallbacks*, reached
only when `zst.msg` is NULL.

`zipfile` decompresses a deflated member with `zlib.decompressobj(-15)`
(`Lib/zipfile/__init__.py`, `_get_decompressor`), driving `zlib_Decompress_decompress_impl`
and `zlib_Decompress_flush_impl` (`zlibmodule.c:947` and `:1521` are their `zlib_error` call
sites). Both have the same shape:

```c
switch (err) {
case Z_OK:  case Z_BUF_ERROR:  case Z_STREAM_END:  break;   /* never raises */
default: ... goto save;
}
...
} else if (err != Z_OK && err != Z_BUF_ERROR) {
    zlib_error(state, self->zst, err, "while decompressing data");
```

Now walk every value `inflate()` can return, against zlib's own source
(`madler/zlib` v1.2.12 `inflate.c` + `inffast.c`, fetched):

| `inflate()` returns | `strm->msg` | reachable from a zip member? |
|---|---|---|
| `Z_OK`, `Z_STREAM_END` | — | not an error |
| `Z_BUF_ERROR` (-5) | **NULL** | Yes, constantly (a truncated member) — but **`Decompress.decompress` and `.flush` both list it beside `Z_OK` and never raise on it.** So `"incomplete or truncated stream"` is dead for this path. It is reachable only from the module-level one-shot `zlib.decompress()`, which `zipfile` does not call. |
| `Z_DATA_ERROR` (-3) | **never NULL** | Only via `case BAD: ret = Z_DATA_ERROR`. Every one of the **25** `state->mode = BAD` assignments (21 in `inflate.c`, 4 in `inffast.c`) sets `strm->msg` on the line immediately above it — verified by `grep -B2`, all 25. So `"invalid input data"` is **dead code** for the inflate path. |
| `Z_NEED_DICT` (2) | NULL | Only from `case DICT` with `havedict == 0`, reached only from `case DICTID`, reached only from `case HEAD` when `state->wrap != 0`. `inflateReset2` sets `wrap = 0` for negative `windowBits`, and `case HEAD` with `wrap == 0` jumps straight to `TYPEDO`. `zipfile` passes `-15`. **Unreachable.** |
| `Z_MEM_ERROR` (-4) | NULL | `case MEM`, the `updatewindow` failure at `inf_leave`, and window allocation. Requires an allocation failure. Not constructible from member bytes — it is a property of the machine, not the input. |
| `Z_STREAM_ERROR` (-2) | NULL | The entry guard (`strm`/`state`/`next_out` NULL, or `next_in` NULL with `avail_in != 0`), or `case SYNC` / `default`. CPython always supplies valid buffers, and `SYNC` mode is only set by `inflateSync`, which `decompressobj` never calls. **Unreachable.** |
| `Z_VERSION_ERROR` (-6) | NULL | `inflate()` never returns it; only `inflateInit2`, whose failure raises `"while preparing to decompress data"` — a different sentence, and it means the interpreter is linked against a header/library pair that does not match. |

**Conclusion of part 1.** For a deflated zip member, every raising path leaves `zst.msg`
non-NULL. The narrowed claim in `docs/porting.md` is correct that the branch exists; it is
correct to have marked it UNMEASURED; and the branch is now shown to be **unreachable** through
`zipfile`. Empirically: **0** null-`msg` sentences (`Error %d while decompressing data` with no
`: `) in 8,037 constructed inputs, under either of the two `libz` builds tested.

## 2. What the construction attempt found instead

Building the corpus turned up a divergence the entry does not predict.

`str(zlib.error)`'s cause clause is **`strm->msg`, a pointer into the linked zlib's own string
table.** The two runtimes do not link the same zlib:

* `runtime-py`: CPython uses the platform `libz`. On this machine both
  `/usr/bin/python3` (3.9.6) and the mise CPython 3.12.13 report `ZLIB_RUNTIME_VERSION 1.2.12`
  and both are Apple's system `libz`.
* `runtime-ts`: Node bundles its own — `process.versions.zlib` is `1.3.1-470d3a2` (the
  Chromium zlib fork).

**Apple's `libz` carries a message string that exists in no upstream zlib release:**
`invalid literal/length/distance code`. It is absent from the whole `madler/zlib` v1.2.12 and
v1.3.1 source trees (`contrib/` included), whose message sets are otherwise **identical to each
other** — 18 strings, `diff` clean.

Where it comes from is measurable without Apple's source. Apple has merged the two
`inflate_fast` BAD branches — `"invalid literal/length code"` and `"invalid distance code"` —
into one string, and has left the `inflate.c` slow-path copies of those two strings alone.
Proof: replay the 803 divergent inputs against Apple's `libz` with `avail_out = 257`, one below
the 258 bytes `inflate()` requires before it will enter `inflate_fast` — and all 803 come back
as the upstream strings, 473 `invalid distance code` + 330 `invalid literal/length code`,
exactly matching stock zlib and exactly matching Node.

Mapping over the corpus (Apple `libz` -> stock madler 1.3.1, same input, same chunking):

```
  'invalid distance too far back'          -> 'invalid distance too far back'          1994
  'invalid block type'                     -> 'invalid block type'                     1002
  'invalid stored block lengths'           -> 'invalid stored block lengths'            972
  'invalid code lengths set'               -> 'invalid code lengths set'                851
  'invalid distance code'                  -> 'invalid distance code'                   568
  'invalid literal/length/distance code'   -> 'invalid distance code'                   473   <-- DIFFERS
  'invalid literal/length/distance code'   -> 'invalid literal/length code'             330   <-- DIFFERS
  'too many length or distance symbols'    -> 'too many length or distance symbols'     104
  'invalid literal/length code'            -> 'invalid literal/length code'               9
  'invalid literal/lengths set'            -> 'invalid literal/lengths set'               1
  'invalid code -- missing end-of-block'   -> 'invalid code -- missing end-of-block'      1
  'invalid bit length repeat'              -> 'invalid bit length repeat'                 1
```

**Ten of the twelve messages the corpus reaches are identical. One Apple string covers two
upstream ones, and that one accounts for every disagreement.**

Why the suite is green today: the checked-in fixture `corrupt-deflate.docx` is
`CORRUPT_DEFLATE = b"\x07\x00\x00\x00\x00"`, a reserved block type. That error is raised in the
slow path, its string is `"invalid block type"`, and Apple and upstream spell it the same. The
one fixture the suite has is one of the ten that cannot fail. (Compare
`tests-that-pick-the-input-that-cannot-fail`.)

## 3. The positive result, end to end, in both runtimes' own words

Fixture: a `.docx` whose `word/document.xml` is written STORED and then relabelled compression
method 8, so the member's "compressed" bytes are exactly

```
03 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
   ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff      (41 bytes)
```

`0x03` = BFINAL 1, BTYPE 01 (fixed Huffman), then 40 bytes of `0xff`. Member CRC `0xe8f846ca`
(the stored bytes' own, so nothing depends on the CRC check); whole file 906 bytes. This is the
same construction the checked-in `corrupt_deflate` fixture uses — only the payload differs. The
member is written with `writestr(info, RAW)` where `RAW` is **`bytes`**; passing a `str` puts
the payload through UTF-8 and `0xff` becomes `c3 bf`, which lands on a different zlib branch
(`invalid distance too far back`, identical on both sides — a trap I fell into first).

Run through the two real readers, the sentences are:

**`runtime-py` (`bantamkit.docread.extract`):**

```
zlib-msg-divergence.docx is a zip but its word/document.xml is damaged (Error -3 while decompressing data: invalid literal/length/distance code), so this reader cannot read it
```

**`runtime-ts` (`runtime-ts/dist/docread.js` `extract`):**

```
zlib-msg-divergence.docx is a zip but its word/document.xml is damaged (Error -3 while decompressing data: invalid distance code), so this reader cannot read it
```

The `Error -3 while decompressing data:` scaffold that `isDamagedMember` rebuilds by hand is
**correct** — the return code and the shape both match. What differs is the one thing the port
cannot rebuild: the cause phrase, which is a string constant inside whichever `libz` the
reference happens to be linked against.

## 4. Why no fixture and no conformance case were added

Both would be dishonest, and invariant 8 forbids writing "X is checked by Y" without running Y.

The divergence is **a property of the host, not of either runtime's code.** Replay the same
6,306 co-raising inputs with CPython's zlib swapped for a stock madler 1.3.1 built from source
on this machine, and the disagreement count is **0 of 6,306**. On a Linux or Windows CI runner,
where CPython links a stock zlib, the two sides agree on this fixture; on macOS they differ.

That makes both possible cases wrong:

* A `ruling:` case pinning the two different sentences is **red on Linux and Windows**, where
  they are the same sentence — and a stale ruling is exactly what the runner reddens.
* A non-ruled parity case pinning agreement is **red on macOS**.

It is also `avail_out`-dependent (§2), so even on macOS it would move if either reader changed
its buffering.

So this belongs where `docs/porting.md` already puts things the differential cannot settle:
"Gaps the differential cannot see, named rather than hidden". A row is added there by this unit.
No fixture is checked in — the builder is four lines and is in §5 below, which is cheaper to
rerun than a committed file whose expected output is host-dependent is to maintain.

Recommendation to the reviewer, **not** applied here (U1/U2 own both `docread` files): none.
There is no fix. The port cannot know Apple's string table, and rewording the reference's own
sentence to drop the cause clause would throw away information on every platform to paper over
one. The right treatment is disclosure, which is what the `porting.md` row does.

## 5. Rerunnable probes

Everything below was run from the repo root on 2026-09-06. Scratch dir:

```sh
S="$(mktemp -d)"        # the run used the session scratchpad; any dir works
```

**(a) The sources the branch analysis reads.**

```sh
curl -sSL -o "$S/zlibmodule.c"  https://raw.githubusercontent.com/python/cpython/3.12/Modules/zlibmodule.c
curl -sSL -o "$S/inflate.c"     https://raw.githubusercontent.com/madler/zlib/v1.2.12/inflate.c
curl -sSL -o "$S/inffast.c"     https://raw.githubusercontent.com/madler/zlib/v1.2.12/inffast.c
curl -sSL -o "$S/zipfile.py"    https://raw.githubusercontent.com/python/cpython/3.12/Lib/zipfile/__init__.py

sed -n '/^zlib_error/,/^}/p' "$S/zlibmodule.c"          # the function quoted in §1
grep -B2 'state->mode = BAD' "$S/inflate.c" "$S/inffast.c" | grep -c 'strm->msg ='   # -> 25
cat "$S/inflate.c" "$S/inffast.c" | grep -c 'state->mode = BAD'                       # -> 25
sed -n '/^int ZEXPORT inflateReset2/,/^}/p' "$S/inflate.c" | grep -A3 'windowBits < 0'  # wrap = 0
grep -n 'decompressobj(-15)' "$S/zipfile.py"
```

**(b) The upstream message set is stable across zlib versions, and lacks Apple's string.**

```sh
for V in 1.2.12 1.3.1; do
  for F in inflate inffast; do
    curl -sSL "https://raw.githubusercontent.com/madler/zlib/v$V/$F.c"
  done | grep -oE 'strm->msg = *\(char \*\)"[^"]*"' | grep -oE '"[^"]*"' | sort -u > "$S/msgs-$V.txt"
done
diff "$S/msgs-1.2.12.txt" "$S/msgs-1.3.1.txt" && echo IDENTICAL     # 18 strings, identical
grep -c 'literal/length/distance' "$S/msgs-1.3.1.txt"               # -> 0 (exit 1)
```

**(c) The reference's libz, asked directly.** `probe.c`:

```c
#include <stdio.h>
#include <string.h>
#include <zlib.h>
int main(void) {
    unsigned char in[41]; unsigned char out[65536];
    in[0] = 0x03; memset(in + 1, 0xff, 40);
    z_stream s; memset(&s, 0, sizeof s);
    if (inflateInit2(&s, -15) != Z_OK) return 2;
    s.next_in = in; s.avail_in = sizeof in;
    s.next_out = out; s.avail_out = sizeof out;
    int r = inflate(&s, Z_SYNC_FLUSH);
    printf("ZLIB_VERSION(compile)=%s runtime=%s\n", ZLIB_VERSION, zlibVersion());
    printf("inflate ret=%d msg=%s\n", r, s.msg ? s.msg : "(NULL)");
    inflateEnd(&s); return 0;
}
```

```sh
cc -o "$S/probe" "$S/probe.c" -lz && "$S/probe"
#   ZLIB_VERSION(compile)=1.2.12 runtime=1.2.12
#   inflate ret=-3 msg=invalid literal/length/distance code

curl -sSL -o "$S/z.tgz" https://github.com/madler/zlib/archive/refs/tags/v1.3.1.tar.gz
tar xzf "$S/z.tgz" -C "$S"; D="$S/zlib-1.3.1"
cc -O2 -w -I "$D" -o "$S/probe-stock" "$S/probe.c" \
   "$D"/adler32.c "$D"/crc32.c "$D"/inflate.c "$D"/inftrees.c "$D"/inffast.c "$D"/zutil.c
"$S/probe-stock"
#   ZLIB_VERSION(compile)=1.3.1 runtime=1.3.1
#   inflate ret=-3 msg=invalid distance code
```

Same bytes, same call, two different sentences — before any of this repo's code is involved.

**(d) The end-to-end fixture and both readers.** From the repo root:

```sh
PYTHONPATH=runtime-py/src .venv/bin/python - "$S" <<'PY'
import sys, zipfile
from pathlib import Path
sys.path.insert(0, "runtime-py/tests")
import docread_fixtures as F
RAW = b"\x03" + b"\xff" * 40
out = Path(sys.argv[1]) / "zlib-msg-divergence.docx"
with zipfile.ZipFile(out, "w") as z:
    for name, text in (("[Content_Types].xml", F.CONTENT_TYPES), ("_rels/.rels", F.ROOT_RELS)):
        i = zipfile.ZipInfo(name, date_time=F._EPOCH); i.compress_type = zipfile.ZIP_STORED
        i.create_system = F._CREATE_SYSTEM_UNIX; z.writestr(i, text.encode("utf-8"))
    i = zipfile.ZipInfo("word/document.xml", date_time=F._EPOCH)
    i.compress_type = zipfile.ZIP_STORED; i.create_system = F._CREATE_SYSTEM_UNIX
    z.writestr(i, RAW)                     # BYTES. a str would be re-encoded as utf-8.
F.set_compress_method(out, b"word/document.xml", 8)
from bantamkit import docread
try: docread.extract(out); print("PY: no error")
except Exception as e: print("PY  :", e)
PY

node -e "
const {extract}=require('./runtime-ts/dist/docread.js');
try{ extract(process.argv[1]); console.log('NODE: no error'); }
catch(e){ console.log('NODE:', e.message); }
" "$S/zlib-msg-divergence.docx"
```

Prints the two sentences quoted in §3. (`runtime-ts/dist` must be built:
`cd runtime-ts && npm run build`.)

**(e) The 8,037-input differential.** Three scripts, kept in the scratch dir of this run and
reproduced here in full so the numbers can be regenerated:

`gen2.py` builds each candidate into a one-member zip whose member is STORED and relabelled
method 8, reads it with `zipfile.ZipFile.read` — the exact call `docread.py::_read` makes — and
records `str(exc)`. Corpus: 6 hand-aimed streams, 4,000 single/multi-byte mutations of a valid
deflate stream (`random.Random(20260906)`), 4,000 pure-random streams of 1..120 bytes, and
truncations of a valid stream at every 11th offset. 8,037 cases.

`node-side2.mjs` replays `runtime-ts/src/docread.ts::inflateRaw` **verbatim** (including the
`Z_BUF_ERROR` -> `Z_SYNC_FLUSH` retry) over the same hex, and builds the same sentence the port
would interpolate.

`replay.c` replays `zipfile`'s decompressor loop in C (raw, 4,096-byte input chunks) and prints
the sentence `zlib_error` would build for whichever `libz` it is linked against — the harness
that lets stock zlib stand in for CPython's.

Headline numbers, all from that run:

```
harness validity:  replay.c under Apple libz vs real CPython zipfile   0 mismatches / 8037
both sides raise:                                                      6306 / 8037
  differing, real runtime-py vs real runtime-ts (macOS)                 803  (12.7 %)
  differing, stock madler 1.3.1 substituted for CPython's zlib            0
null-msg sentences ("Error %d while decompressing data", no colon)        0  under either libz
```

`replay.c` with `s.avail_out = 257` instead of `sizeof out`, over just those 803 inputs, returns
473 `invalid distance code` + 330 `invalid literal/length code` — the `inflate_fast` proof
in §2.

## 6. What this means for roadmap row 8 (s)

Row (s) should be **re-worded, not closed**. As registered it predicts the wrong mechanism and,
read literally, it is unreachable. What is actually true and now measured:

1. The null-`zst.msg` branch of `zlib_error` cannot be reached through `zipfile`'s
   `decompressobj(-15)`. `"invalid input data"` is dead code there; `"incomplete or truncated
   stream"` is filtered out by `Decompress.decompress`'s own `Z_BUF_ERROR` case;
   `"inconsistent stream state"` needs an invalid `z_stream`; `Z_NEED_DICT` needs `wrap != 0`.
2. The port's rebuilt sentence still differs from the reference's, on macOS, for 12.7 % of
   corrupt members — because the cause phrase belongs to the linked `libz`, and the two
   runtimes do not link the same one.
3. It cannot be pinned by a conformance case, because the expected value is host-dependent.
   Disclosed in `docs/porting.md` under "Gaps the differential cannot see".
