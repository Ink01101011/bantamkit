/**
 * What the agent touched, and the graph it makes (#200). Paths only, never content. Port of
 * `runtime-py/src/bantamkit/touch/__init__.py`; `tools/conformance/suites/touch-*.mjs`
 * compare the two. Add one re-export line per module.
 */
export { TOUCH_LOG_CAP_BYTES, TOUCH_LOG_FOLD_TARGET_BYTES, TOUCH_OPS, TOUCH_TAIL_BYTES, TouchLog, USE_HEADER, boundBody, currentSeq, foldCutoff, nextSeq, touchReducer, useNames } from './log.js';
export { GIT_PATHEXT_DEFAULT, GIT_TIMEOUT_MS, findRepo, git, gitOnPath, relPath, type Repo } from './repo.js';
export { FileSet, REF_RE, extractRefs, factRefs, resolveRef, shortestSuffix } from './refs.js';
export { headPrint, lsFiles, renames } from './repo.js';
export { changed, loadTurn, saveTurn, snapshot, type Entry, type Snapshot } from './bashturn.js';
export { GRAPH_VERSION, WEAK_SPAN, WEAK_TS_MAX, TouchGraph, buildStrong, buildWeak } from './graph.js';
export { CONTEXT_WEAK_SHARE, TOUCH_WINDOW, VIA_ENV, VIA_MAX, contextWeights, viaEnabled, viaLabel, viaPick, window, type ContextGraph, type TouchContext } from './context.js';
export { COMPACT_FILES, SUMMARY_COMMITS, SUMMARY_COMMIT_GRACE_S, SUMMARY_FILES, SUMMARY_MAX, SUMMARY_SUBJECT_MAX, ageText, capBytes, compactLine, lastSessionLine, previousSession, shiftTs, uncommittedCount } from './summary.js';
export { FILE_AMBIGUOUS, FILE_NOT_IN_REPO, FILE_NO_FACTS, FILE_UNKNOWN, QUERY_IGNORED, RECALL_NEEDS_QUERY_OR_FILE, historyLine, linkedNames } from './recallfile.js';
