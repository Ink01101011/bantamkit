"""What the agent touched, and the graph it makes (#200). Paths only, never content.

`runtime-ts/src/touch/index.ts` is the port; `tools/conformance/suites/touch-*.mjs` compare
the two. Add one re-export line per module.
"""

from .bashturn import changed, load_turn, save_turn, snapshot  # noqa: F401
from .context import (  # noqa: F401
    CONTEXT_WEAK_SHARE,
    TOUCH_WINDOW,
    VIA_ENV,
    VIA_MAX,
    TouchContext,
    context_weights,
    via_enabled,
    via_label,
    via_pick,
    window,
)
from .graph import (  # noqa: F401
    GRAPH_VERSION,
    WEAK_SPAN,
    WEAK_TS_MAX,
    TouchGraph,
    build_strong,
    build_weak,
)
from .log import (  # noqa: F401
    TOUCH_LOG_CAP_BYTES,
    TOUCH_LOG_FOLD_TARGET_BYTES,
    TOUCH_OPS,
    TOUCH_TAIL_BYTES,
    TouchLog,
    bound_body,
    current_seq,
    fold_cutoff,
    next_seq,
    touch_reducer,
    use_names,
)
from .recallfile import (  # noqa: F401
    FILE_AMBIGUOUS,
    FILE_NO_FACTS,
    FILE_NOT_IN_REPO,
    FILE_UNKNOWN,
    QUERY_IGNORED,
    RECALL_NEEDS_QUERY_OR_FILE,
    history_line,
    linked_names,
)
from .refs import (  # noqa: F401
    REF_RE,
    FileSet,
    extract_refs,
    fact_refs,
    resolve_ref,
    shortest_suffix,
)
from .repo import (  # noqa: F401
    GIT_PATHEXT_DEFAULT,
    GIT_TIMEOUT_MS,
    Repo,
    find_repo,
    git,
    git_on_path,
    head_print,
    ls_files,
    relpath,
    renames,
)
from .summary import (  # noqa: F401
    COMPACT_FILES,
    SUMMARY_COMMIT_GRACE_S,
    SUMMARY_COMMITS,
    SUMMARY_FILES,
    SUMMARY_MAX,
    SUMMARY_SUBJECT_MAX,
    age_text,
    cap_bytes,
    compact_line,
    last_session_line,
    previous_session,
    shift_ts,
    uncommitted_count,
)
