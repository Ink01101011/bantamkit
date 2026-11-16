// J90-2 (#316 G4): one half of an import cycle (`j90_cycle_b.ts` imports this back), as
// `storage/hotindex.ts` and `memory/store.ts` are. tests/g4.rs imports either half first.
import { twice } from './j90_cycle_b.js';

export const BASE = 10;

export class Counter {
  count = 0;
  bump(): number {
    this.count += 1;
    return this.count;
  }
}

export function down(n: number): number {
  return n <= 0 ? BASE : twice(n - 1) + 1;
}
