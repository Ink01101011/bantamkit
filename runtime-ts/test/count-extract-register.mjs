/**
 * `--import` this into a server process to switch on the `docread.extract` counter.
 *
 * Split from the hook itself because `module.register` loads the hook on its own thread: this
 * file runs in the main thread and only registers, `count-extract-hooks.mjs` runs in the
 * loader thread and does the work. See that file for what is counted and why.
 */
import { register } from 'node:module';

register('./count-extract-hooks.mjs', import.meta.url);
