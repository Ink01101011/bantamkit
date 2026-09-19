---
name: feedback-read-the-warnings-summary
description: grep a CI log for warnings not just FAILED lines - on Windows a dead
  subprocess reader thread hides the real exception in the warnings summary
type: feedback
created: '2026-08-22'
last_recalled: '2026-09-11'
links: []
---

I searched a 34,000-line Windows CI log twice — for `FAILED` lines, then for
specific error strings — and reported that the root cause "is not reachable by
reading CPython". It was reachable, and it was **in the log I already had**:

    PytestUnhandledThreadExceptionWarning: Exception in thread Thread-21 (_readerthread)
      File "...\Lib\subprocess.py", line 1599, in _readerthread
        buffer.append(fh.read())
    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97 in position 13

24 occurrences. `grep -c PytestUnhandledThreadExceptionWarning` would have found it
in one command. I then spent a whole round building a diagnostic branch to measure
something the log already said.

**Why:** on Windows `subprocess` decodes in a **daemon reader thread**. A
`UnicodeDecodeError` there dies with the thread, `join()` returns normally, the
buffer stays empty, and `communicate()` ends at
`stdout = stdout[0] if stdout else None` — so the caller gets `stdout=None` beside
an intact `returncode` and an intact `stderr=''`. POSIX decodes on the calling
thread and *raises*. Same cause, two presentations, and only one of them names
itself. Any failure whose real exception happened off the main thread will present
as an inexplicable `None`, and the explanation will only ever be in the warnings.

**How to apply:** when a CI failure looks impossible from reading the source, grep
the log for `Warning` before building any instrument. Specifically
`PytestUnhandledThreadExceptionWarning`, `PytestUnraisableExceptionWarning`, and
`ResourceWarning`. And prefer making the run *fail* there —
`-W error::pytest.PytestUnhandledThreadExceptionWarning` turns a dead thread into a
failure at the node that caused it. Related:
[[feedback-verify-against-the-run-not-the-source]],
[[feedback-worktree-pytest-tests-mains-source]], [[project-job31-windows-fixes]].
