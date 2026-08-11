# Master baseline

Baseline measurement was not performed.

The required first command was:

    git checkout --detach origin/master
    git rev-parse --short HEAD

It failed with:

    fatal: Unable to create 'C:/Users/3fall/Projects/cryodaq/.git/worktrees/f366/index.lock': Permission denied

The command printed `b141de0b`. The required master SHA was `474a60a8`, so this worktree was not measured. No test or Ruff command was run.

- WHAT I CHANGED: Added `MASTER_BASELINE.md` to record the failed master checkout and prevent measurement of the wrong tree. No source files changed.
- CONTROL: NOT DETERMINABLE; no behavior was changed and no control run was authorized or applicable.
- DIRECTORY: `tests/drivers`, `tests/docs`, `tests/governance`, `tests/channels`, and `tests/integration` were not run because the required tree could not be established.
- RUFF: NOT RUN; no source files were touched.
- FILES CHANGED: `MASTER_BASELINE.md` (uncommitted).
- REFUTED OR NOT DETERMINABLE: The required master baseline is NOT DETERMINABLE. The worktree remains at `b141de0b`; `474a60a8` was not established. GREEN/NOT GREEN status for every requested directory is NOT DETERMINABLE.
