import { cmpCp, twice } from './helpers.js';

export function make(n: number): number {
  return twice(n) + 1;
}

export function order(xs: string[]): string[] {
  return xs.slice().sort((a, b) => cmpCp(a, b));
}

export function env(): string | undefined {
  return process.env.HOME;
}
