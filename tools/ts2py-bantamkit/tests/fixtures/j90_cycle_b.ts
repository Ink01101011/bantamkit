// J90-2 (#316 G4): the other half of the cycle `j90_cycle_a.ts` opens.
import { BASE, Counter, down } from './j90_cycle_a.js';

export const LIMIT = 3;

export function twice(n: number): number {
  const c = new Counter();
  c.bump();
  return down(n - 1) * 2 + c.count + (n > LIMIT ? BASE : 0);
}
