/**
 * The native fact-file read the hot index and the native layer share (#199, #204): a port of
 * the reference's `divergence.parse_fact` for Claude Code's auto-memory shape (`metadata:` holding
 * `type`, and the indented `links:` / `tags:` lists Claude Code writes).
 *
 * Moved out of `hotindex.ts` unchanged (#316 G4, J90-2) so that module can be compiled by
 * `tools/ts2py` while this one stays the `parseNative` ADAPTER onto `divergence.parse_fact`: the
 * #228 row of `docs/porting.md` rules that the reference's hot index keeps reading a native file
 * with PyYAML, which the codec below does not port.
 */
import { BantamError } from '../errors.js';
import { parseFrontmatter, pySplit, pyStrip } from '../memory/factfile.js';
import { PyOSError, PyUnicodeDecodeError, pyReadText } from '../memory/pyfs.js';

/**
 * `key:\n  - a\n  - b` is the same list to PyYAML as `key:\n- a\n- b`, and the codec reads only
 * the second: an INDENTED block sequence directly under an empty `key:` is moved to column 0.
 * Only the items of that run move, so a block scalar holding `  - x` is left alone.
 */
function outdentSequences(lines: string[]): string[] {
  const out: string[] = [];
  let inRun = false;
  let runIndent = '';
  for (const line of lines) {
    const item = /^([ \t]+)- /.exec(line) ?? /^([ \t]+)-$/.exec(line);
    const prev = out.length ? out[out.length - 1]! : '';
    if (item && (inRun ? item[1] === runIndent : /^[A-Za-z_][A-Za-z0-9_-]*:[ \t]*$/.test(prev))) {
      inRun = true;
      runIndent = item[1]!;
      out.push(line.slice(runIndent.length));
      continue;
    }
    inRun = false;
    out.push(line);
  }
  return out;
}

/**
 * The native frontmatter: PyYAML reads `metadata:` as a nested mapping and the store's codec
 * reads only a flat one, so the indented block under `metadata:` is cut out and read on its
 * own, dedented. Anything deeper is outside the codec and raises.
 */
function parseNativeFront(front: string): Record<string, unknown> {
  const lines = outdentSequences(front.split('\n'));
  const top: string[] = [];
  let metadata: Record<string, unknown> | undefined;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    if (/^metadata:[ \t]*(?:#.*)?$/.test(line)) {
      const block: string[] = [];
      let j = i + 1;
      while (j < lines.length && (/^[ \t]/.test(lines[j]!) || lines[j] === '')) {
        block.push(lines[j]!);
        j += 1;
      }
      while (block.length > 0 && block[block.length - 1] === '') block.pop();
      const indent = block.find((l) => l !== '')?.match(/^[ \t]*/)?.[0].length ?? 0;
      metadata =
        block.length === 0
          ? undefined
          : (parseFrontmatter(`${outdentSequences(block.map((l) => l.slice(indent))).join('\n')}\n`) as Record<
              string,
              unknown
            >);
      i = j - 1;
      continue;
    }
    top.push(line);
  }
  const meta = parseFrontmatter(top.join('\n')) as Record<string, unknown>;
  if (metadata !== undefined) meta['metadata'] = metadata;
  else if (front.match(/^metadata:/m)) meta['metadata'] = null;
  return meta;
}

/**
 * `divergence.parse_fact` for the native shape: name, description, type and body; `meta`, the
 * frontmatter read, and `front`, its text (the second of `pySplit(text, '---\n', 2)`'s three parts;
 * #316 G4, J90-PF: the hot index tests it where it read the file again).
 */
export function parseNative(p: string): {
  name: string;
  description: string;
  type: string;
  body: string;
  meta: Record<string, unknown>;
  front: string;
} {
  let text: string;
  try {
    text = pyReadText(p);
  } catch (e) {
    if (e instanceof PyOSError || e instanceof PyUnicodeDecodeError) {
      throw new BantamError(`unreadable fact file ${p}: ${e.message}`);
    }
    throw e;
  }
  const parts = pySplit(text, '---\n', 2);
  if (parts.length !== 3) throw new BantamError(`malformed fact file ${p}: no frontmatter fences`);
  const [head, front, body] = parts as [string, string, string];
  if (pyStrip(head)) {
    throw new BantamError(`malformed fact file ${p}: frontmatter is not at the top of the file`);
  }
  let meta: Record<string, unknown>;
  try {
    meta = parseNativeFront(front);
  } catch (e) {
    throw new BantamError(`malformed fact file ${p}: ${e instanceof Error ? e.message : String(e)}`);
  }
  // PyYAML reads a frontmatter of nothing but blanks and comments as `None`.
  if (Object.keys(meta).length === 0) {
    throw new BantamError(`malformed fact file ${p}: frontmatter is not a mapping`);
  }
  const name = meta['name'];
  if (typeof name !== 'string' || !pyStrip(name)) {
    throw new BantamError(`malformed fact file ${p}: no usable 'name'`);
  }
  const md = meta['metadata'];
  const metadata = md !== null && typeof md === 'object' && !Array.isArray(md) ? (md as Record<string, unknown>) : {};
  let type: string;
  if (typeof meta['type'] === 'string') type = meta['type'];
  else if (typeof metadata['type'] === 'string') type = metadata['type'];
  else {
    throw new BantamError(
      `malformed fact file ${p}: no 'type' at the top level and none under ` +
        `'metadata:' — this file matches neither store's shape`,
    );
  }
  const description = meta['description'];
  return {
    name: pyStrip(name),
    description: typeof description === 'string' ? description : '',
    type,
    body: pyStrip(body),
    meta,
    front,
  };
}
