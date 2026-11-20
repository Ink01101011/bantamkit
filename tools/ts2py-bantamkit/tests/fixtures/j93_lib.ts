// J91-3 (#341): the other module of the J91-3 probe (tests/j93.rs). Its exported functions return
// values whose facts another module reads (`ModuleExports::rets`): a list of `str`s built by sealed
// closures (tokenizeV2's shape), a `g` match, a Set of `str`s; and the counter-examples, each of
// which must prove nothing in the importer: a list a closure that escapes can still read, a function
// whose untyped body may return something else, a name the host rebinds (`exclusive`), and one
// that returns a list another call can reach. It imports `opaque` back from the probe (a cycle).

import { pyNfkcLower } from './pysem.js';
import { opaque } from './j93_probe.ts';

/** Words of `text`, split at spaces, built by a sealed closure into a sealed local. */
export function words(text: string): string[] {
  const s = pyNfkcLower(text);
  const out: string[] = [];
  let at = -1;
  const flush = (end: number): void => {
    if (at >= 0) {
      out.push(s.slice(at, end));
      at = -1;
    }
  };
  for (let i = 0; i < s.length; i += 1) {
    if (s[i] === ' ') flush(i);
    else if (at < 0) at = i;
  }
  flush(s.length);
  return out;
}

/** The runs of `[a-z0-9]`: a `g` match, or a fresh empty list. */
export function matched(text: string): string[] {
  return text.match(/[a-z0-9]+/g) ?? [];
}

/** The runs of `[a-z0-9]` as a Set made from a `g` match, plus `extra` added one by one. */
export function runSet(text: string, extra: string[]): Set<string> {
  const out = new Set(text.match(/[a-z0-9]+/g) ?? []);
  for (const e of extra) out.add(String(e));
  return out;
}

/**
 * `[text]` into a list, with a reader of it handed out through `holder` (so the closure escapes):
 * the caller may push anything into the list and the reader still reads it, so the list is not
 * the caller's alone and the reader proves nothing of its elements.
 */
export function captured(text: string, holder: Array<() => string>): string[] {
  const out: string[] = [];
  out.push(String(text));
  const read = (): string => {
    const m = new Map<any, string>();
    m.set(1, 'one');
    m.set('a', 'A');
    let r = '';
    for (const t of out) r += `${String(m.get(t))};`;
    return r;
  };
  holder.push(read);
  return out;
}

/**
 * `captured`, with the reader called through a second closure that escapes instead: the reader is
 * called directly, but from a nested function, so it can still run once this body has returned.
 */
export function callLater(text: string, holder: Array<() => string>): string[] {
  const out: string[] = [];
  out.push(String(text));
  const read = (): string => {
    const m = new Map<any, string>();
    m.set(1, 'one');
    m.set('a', 'A');
    let r = '';
    for (const t of out) r += `${String(m.get(t))};`;
    return r;
  };
  const later = (): string => read();
  holder.push(later);
  return out;
}

/** The first unit of `x`: a `str` in the typed body, `x.slice(0, 1)` of anything in the other. */
export function firstOf(x: string): string[] {
  const out: string[] = [];
  out.push(x.slice(0, 1));
  return out;
}

/** A name the host rebinds (`[[rebound]] exclusive`): what its body returns proves nothing. */
export function exclusive(text: string): string[] {
  const out: string[] = [];
  out.push(String(text));
  return out;
}

const SHARED: string[] = [];

/** A list every call shares (a module constant): never the caller's alone. */
export function shared(text: string): string[] {
  SHARED.push(String(text));
  return SHARED;
}

/** `words(text)` or `null`: what `?? fallback` reads. */
export function maybeWords(text: string): string[] | null {
  return text.length > 1 ? words(text) : null;
}

/** `opaque` from the probe (the import cycle), so this module reads it too. */
export function launder(x: any): any {
  return opaque(x);
}
