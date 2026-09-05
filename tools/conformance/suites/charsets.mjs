/**
 * charsets — the port's copy of CPython's codec registry, against the registry itself.
 *
 * THE PROPERTY: `runtime-ts/src/charsets.ts` is not a second registry kept in step by hand;
 * it is CPython's, written out by `runtime-ts/scripts/charsets-table.py`, and this suite is
 * what makes that a measurement. Two comparisons, because two things drift independently:
 *
 *   1. THE FILE AGAINST THE GENERATOR. The checked-in `charsets.ts` is compared byte for byte
 *      with what the generator writes today, header line excluded — the header names the
 *      interpreter's version, which the note reports instead, so a `3.12.13` venv and a
 *      `3.12.x` CI runner compare the tables and not the banner. An edited script whose
 *      output was never regenerated fails here.
 *   2. THE TABLES AGAINST THE INTERPRETER. For every codec the port carries, all 256 bytes
 *      are decoded by the REFERENCE (`bytes([b]).decode(codec, errors="replace")`, computed
 *      in `ref/charsets_ref.py`, not read back from the generator) and compared to what the
 *      port's table says — the low half is ASCII unless the table carries a `low` (the
 *      EBCDIC pages). The alias map and the module list are compared whole. A CPython that
 *      changed a table, added an alias or dropped a module fails here even if the file and
 *      the generator still agree with each other.
 *   3. THE KEY SETS, so the comparison runs BOTH WAYS. Comparison 2 is driven by the PORT'S
 *      key list, so until review round 4 it could see a table that changed and never one that
 *      VANISHED — a lost codec lost its case and the run stayed green (M7 / I3-F7). Two cases
 *      now compare the loaded artefact's key set against the generator's, so a port that drops
 *      a table fails as surely as an interpreter that drops a module.
 *
 * Nothing here is a ruling: the port is REQUIRED to answer for the registry it was generated
 * from, and a difference is a stale file, never a decision.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const name = 'charsets';
export const summary = 'src/charsets.ts against the live CPython codec registry: the generator\'s output and every single-byte table';

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const REF = join(here, 'ref', 'charsets_ref.py');

const ASCII = Array.from({ length: 128 }, (_, i) => String.fromCharCode(i)).join('');
const HEADER = /^\/\/ Registry: CPython .*\n/m;

/**
 * The KEY SET the generator writes for one of its two tables, read out of the generator's own
 * stdout — which is the only place the reference's answer to "which codecs belong here" exists.
 *
 * WHY THIS FUNCTION EXISTS (review round 4, M7 / I3-F7). Every per-codec case below is driven
 * by `Object.keys(charsets.SINGLE_BYTE_TABLES)` — the PORT'S OWN key list. That direction
 * catches a table whose contents drifted; it cannot catch a table that is GONE, because a
 * codec the port has lost simply generates no case. Measured on the shipped artefact
 * `runtime-ts/dist/charsets.js`, the file the port executes and `package.json` `files:`
 * ships: change one codepoint of `cp437` and the suite goes red (93 cases, 1 failure), but
 * DELETE the whole `cp437` entry and it stays green at 92 cases and 0 failures. The header
 * three lines up claims "a CPython that … dropped a module fails here", and that is true; the
 * converse was not, and the only signal was a case count nobody asserts.
 *
 * The `src/charsets.ts` byte comparison does not close it either: that case compares SOURCE
 * against the generator, and the mutation above is in `dist`. Nothing compared what the port
 * actually loads against what the reference says should be there.
 *
 * `json.dumps(..., indent=2)` writes valid JSON, so the object is parsed rather than scraped:
 * find the assignment, take the object between the first `{` after `=` and the `};` that
 * closes it at column 0.
 */
function generatedKeys(generated, constName) {
  const at = generated.indexOf(`export const ${constName}`);
  if (at < 0) return `<the generator wrote no ${constName}>`;
  const open = generated.indexOf('{', generated.indexOf('=', at));
  const close = generated.indexOf('\n};', open);
  if (open < 0 || close < 0) return `<could not read ${constName} out of the generator's output>`;
  try {
    return Object.keys(JSON.parse(generated.slice(open, close + 2))).sort();
  } catch (e) {
    return `<${constName} did not parse: ${e.message}>`;
  }
}

export async function run(ctx) {
  const charsets = await import(pathToFileURL(join(ctx.runtimeTs, 'dist', 'charsets.js')).href);
  const source = readFileSync(join(ctx.runtimeTs, 'src', 'charsets.ts'), 'utf8');
  const codecs = Object.keys(charsets.SINGLE_BYTE_TABLES).sort();
  const multi = Object.keys(charsets.MULTI_BYTE_SINGLES).sort();
  const python = ctx.runPython(REF, { codecs, multi });

  const cases = [];
  const notes = [];

  const fileVersion = source.match(HEADER)?.[0].match(/CPython (\S+)/)?.[1] ?? null;
  // A GENERATOR THAT DID NOT RUN IS A FAILING CASE, NOT A CRASH. Reading `.replace` off a
  // null took the whole run down on Windows with a `TypeError` that named neither the
  // generator nor the platform, so the suite had never completed there and nothing said so.
  // The reference now reports the outcome and this turns it into one legible failure.
  if (typeof python.generated !== 'string') {
    const g = python.generator ?? {};
    cases.push({
      name: 'scripts/charsets-table.py runs at all',
      kind: 'json',
      expected: { ran: true, returncode: 0 },
      actual: { ran: typeof python.generated === 'string', returncode: g.returncode ?? null },
    });
    notes.push(
      `charsets: the generator did not produce a table. path=${g.path} exists=${g.exists} ` +
        `returncode=${g.returncode} stdout_bytes=${g.stdout_bytes}` +
        (g.stderr ? `\n--- generator stderr ---\n${g.stderr}` : ''),
    );
    return { cases, notes };
  }
  cases.push({
    name: 'src/charsets.ts is what scripts/charsets-table.py writes for the live registry (header line excluded)',
    kind: 'bytes',
    expected: python.generated.replace(HEADER, ''),
    actual: source.replace(HEADER, ''),
  });
  cases.push({
    name: 'src/charsets.ts carries the generator\'s header',
    kind: 'json',
    expected: true,
    actual: HEADER.test(source) && source.startsWith('// GENERATED by scripts/charsets-table.py'),
  });
  cases.push({ name: 'CODEC_MODULES is what pkgutil finds under encodings', kind: 'json', expected: python.modules, actual: [...charsets.CODEC_MODULES].sort() });
  cases.push({ name: 'CODEC_ALIASES is encodings.aliases.aliases', kind: 'json', expected: python.aliases, actual: charsets.CODEC_ALIASES });
  // THE SET, not just the contents. Everything below iterates the port's own keys, so a table
  // the port LOSES generates no case at all; these two compare the key set the loaded artefact
  // carries against the key set the generator writes, so a shrinking table set is a failure
  // and not a smaller number. See `generatedKeys` above for the measurement that motivated it.
  cases.push({
    name: 'SINGLE_BYTE_TABLES holds exactly the codecs the generator writes — a table the port LOST is a failure, not one fewer case',
    kind: 'json',
    expected: generatedKeys(python.generated, 'SINGLE_BYTE_TABLES'),
    actual: codecs,
  });
  cases.push({
    name: 'MULTI_BYTE_SINGLES holds exactly the codecs the generator writes — a table the port LOST is a failure, not one fewer case',
    kind: 'json',
    expected: generatedKeys(python.generated, 'MULTI_BYTE_SINGLES'),
    actual: multi,
  });
  for (const codec of codecs) {
    const table = charsets.SINGLE_BYTE_TABLES[codec];
    cases.push({
      name: `single-byte ${codec}: all 256 bytes decode as CPython decodes them (errors="replace")`,
      kind: 'bytes',
      expected: python.tables[codec] ?? `<no such codec on the reference: ${codec}>`,
      actual: `${table.low ?? ASCII}${table.high}`,
    });
  }
  for (const codec of multi) {
    cases.push({
      name: `multi-byte ${codec}: which of 0x80..0xFF is a character on its own to CPython`,
      kind: 'bytes',
      expected: python.multi_singles[codec] ?? `<no such codec on the reference: ${codec}>`,
      actual: charsets.MULTI_BYTE_SINGLES[codec],
    });
  }
  notes.push(
    `${codecs.length} single-byte codecs, ${multi.length} multi-byte codecs' single bytes, ${Object.keys(charsets.CODEC_ALIASES).length} aliases, ` +
      `${charsets.CODEC_MODULES.size} modules; src/charsets.ts was generated by CPython ${fileVersion}, the reference here is CPython ${python.version}`,
  );
  return { cases, notes };
}
