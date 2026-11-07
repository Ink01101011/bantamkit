/**
 * The miner's label tokenizer (#289, #299), out of `skillmine` so `memory/component` can match a
 * trigger phrase (#301) without importing the miner: `skillmine` reaches `skillinstall` and
 * `skillpromote`, and that edge from the recall component closes an import cycle whose first
 * module evaluated (`skillfile`) is not yet initialised. `skillmine` re-exports all three names;
 * the reference keeps them in `skillmine.py` and imports lazily.
 */
import { nospace, WORDCHAR } from './memory/retrieval.js';

/** #289: Thai words that only steer a session ("go on", "done", "please"); they never label one. */
export const LABEL_STOPWORDS: readonly string[] = [
  'ครับ', 'ค่ะ', 'แล้ว', 'ต่อ', 'ทำ', 'ให้', 'ที่', 'และ', 'ได้', 'หน่อย', 'ด้วย', 'เลย', 'นี้', 'ไหม', 'อีก', 'ก่อน', 'เป็น',
];
const MARK = /^[\p{Mn}\p{Mc}]$/u;
// Thai and Lao following vowels (SARA A, AA, AM, LAKKHANGYAO; Lao A, AA, AM): category Lo, yet
// they close the syllable before them, so they join the unit before them as a mark does.
const FOLLOWING: ReadonlySet<number> = new Set([0x0e30, 0x0e32, 0x0e33, 0x0e45, 0x0eb0, 0x0eb2, 0x0eb3]);
const joins = (ch: string): boolean => MARK.test(ch) || FOLLOWING.has(ch.codePointAt(0)!);
// Thai and Lao leading vowels: written before the consonant they follow in speech.
const leading = (cp: number): boolean => (cp >= 0x0e40 && cp <= 0x0e44) || (cp >= 0x0ec0 && cp <= 0x0ec4);
// NFKC decomposes SARA AM (U+0E33, U+0EB3) into NIKHAHIT + SARA AA; recompose it.
const labelFold = (text: string): string => text.normalize('NFKC').toLowerCase().replaceAll('\u0e4d\u0e32', '\u0e33').replaceAll('\u0ecd\u0eb2', '\u0eb3');

/**
 * A no-space run as units: a combining mark or a following vowel joins the unit before it, a
 * leading vowel the unit after it.
 */
function labelUnits(run: readonly string[]): string[] {
  const out: string[] = [];
  let pend = '';
  for (const ch of run) {
    if (joins(ch) && out.length > 0 && pend === '') out[out.length - 1] += ch;
    else if (leading(ch.codePointAt(0)!)) pend += ch;
    else {
      out.push(pend + ch);
      pend = '';
    }
  }
  if (pend !== '') out.push(pend);
  return out;
}

// Longest first (in units); a tie keeps `LABEL_STOPWORDS` order (the sort is stable).
const STOP_UNITS: readonly string[][] = LABEL_STOPWORDS.map((w) => labelUnits(Array.from(labelFold(w)))).sort(
  (a, b) => b.length - a.length,
);

/**
 * #299: English function words dropped from a label. Before this, a cluster mined from one
 * template carried `the`, `for`, `in`, `one` as keywords (the document-frequency cut cannot drop
 * a word every member shares), and the `[skill]` layer matched prompts on them. A word of one
 * character and a word of digits only are dropped too (`c`, `5`, `2026`).
 */
export const LABEL_STOPWORDS_EN: ReadonlySet<string> = new Set([
  'a',
  'about',
  'after',
  'all',
  'also',
  'an',
  'and',
  'any',
  'are',
  'as',
  'at',
  'be',
  'been',
  'before',
  'but',
  'by',
  'can',
  'could',
  'did',
  'do',
  'does',
  'each',
  'every',
  'for',
  'from',
  'had',
  'has',
  'have',
  'he',
  'her',
  'here',
  'his',
  'how',
  'i',
  'if',
  'in',
  'into',
  'is',
  'it',
  'its',
  'just',
  'may',
  'me',
  'might',
  'must',
  'my',
  'no',
  'not',
  'of',
  'on',
  'one',
  'only',
  'or',
  'our',
  'out',
  'over',
  'per',
  'she',
  'should',
  'so',
  'than',
  'that',
  'the',
  'their',
  'them',
  'then',
  'there',
  'these',
  'they',
  'this',
  'those',
  'to',
  'up',
  'via',
  'was',
  'we',
  'were',
  'what',
  'when',
  'where',
  'which',
  'who',
  'will',
  'with',
  'would',
  'you',
  'your',
]);

const labelWordKept = (word: string): boolean =>
  Array.from(word).length > 1 && !/^[0-9]+$/.test(word) && !LABEL_STOPWORDS_EN.has(word);

/**
 * The miner's label tokens (#289): `tokenizeV2`'s words and runs, but a no-space run is cut into
 * units (a base character with its marks, its following vowel and its leading vowel), split at `LABEL_STOPWORDS`, and each
 * segment emits its one unit or its unit bigrams. `tokenizeV2` stays as it is: recall is
 * measured on it. ASCII text gives `tokenizeV2`'s list minus the #299 drops above.
 */
export function tokenizeLabel(text: string): string[] {
  const s = labelFold(text);
  const out: string[] = [];
  let word = '';
  let run: string[] = [];
  const flushWord = (): void => {
    if (word !== '' && labelWordKept(word)) out.push(word);
    word = '';
  };
  const flushRun = (): void => {
    if (run.length === 0) return;
    const us = labelUnits(run);
    run = [];
    let seg: string[] = [];
    const emit = (): void => {
      if (seg.length === 1) out.push(seg[0]!);
      else for (let i = 0; i + 1 < seg.length; i++) out.push(seg[i]! + seg[i + 1]!);
      seg = [];
    };
    let i = 0;
    while (i < us.length) {
      const stop = STOP_UNITS.find((w) => i + w.length <= us.length && w.every((u, k) => us[i + k] === u));
      if (stop !== undefined) {
        emit();
        i += stop.length;
      } else {
        seg.push(us[i]!);
        i += 1;
      }
    }
    emit();
  };
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (nospace(cp)) {
      flushWord();
      run.push(ch);
    } else if (WORDCHAR.test(ch)) {
      flushRun();
      word += ch;
    } else {
      flushWord();
      flushRun();
    }
  }
  flushWord();
  flushRun();
  return out;
}
