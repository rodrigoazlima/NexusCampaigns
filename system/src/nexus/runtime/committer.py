"""nexus.runtime.committer — stages a scoped set of paths and commits them.
Shared by agent dispatch (Runtime.commit_changes) and the worker loop —
both auto-commit only their own declared commit_scope, never a blanket `git add`.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from nexus.shared import FileLock, Logger

from .paths import GIT_COMMIT_LOCK_TARGET, PROJECT_ROOT


def commit_scoped(label: str, scope: list[str], log: Logger) -> None:
    """Stage only the scoped paths and commit."""
    # `git reset` clobbers the whole index, so in async mode two agents
    # committing at once could wipe each other's staged scope — serialize
    # the reset→add→commit critical section regardless of pipeline_mode.
    with FileLock(GIT_COMMIT_LOCK_TARGET, timeout=30.0):
        # Clear the index first so any stray pre-staged file (leftover from a
        # prior partial run, manual `git add`, etc.) cannot leak into the auto
        # commit. After this, the index holds ONLY the scope paths staged below.
        subprocess.run(
            ["git", "reset", "-q"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
        )

        for path in scope:
            subprocess.run(
                ["git", "add", "--", path],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
            )

        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(PROJECT_ROOT),
        )
        if staged.returncode == 0:
            return

        ts  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"chore(auto): {label} run at {ts}"
        subprocess.run(
            ["git", "commit", "-m", msg, "--", *scope],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
    log.info(f"Committed scoped changes for {label} (paths: {scope})")
