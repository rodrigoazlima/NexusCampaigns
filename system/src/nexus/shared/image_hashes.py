"""nexus.shared.image_hashes — durable content-hash ledger for de-duplication.

Populated at ingestion time (first-seen wins), independent of whether/when
vision has processed the image. This is the fix for a real gap: the only
prior dedup check (dashboard upload-image route) looked up
agents/vision/state/processed-images.json, which only gains an entry once
vision *finishes* classifying an image — a batch/interval delay that can run
minutes. Any duplicate landing before that (a second dashboard upload, or a
file dropped straight into 00-Inbox/ outside the dashboard entirely) sailed
through untouched. system/state/image-hashes.json closes both gaps: it is
the ledger ingestion.py (the single queue producer every inbox file funnels
through) checks and claims before ever creating pipeline work for an image.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .file_lock import FileLock


def claim_image_hash(hashes_file: Path, hash_: str, rel_path: str) -> Optional[dict]:
    """Atomically check-and-claim a content hash in the ledger.

    Returns the existing {"path", "firstSeenAt"} entry if `hash_` was already
    claimed by a different path — a genuine duplicate. Otherwise claims
    `hash_` for `rel_path` (first-seen wins) and returns None.

    ponytail: no staleness check against the claimed path still existing —
    00-Inbox/ is never modified or deleted from (vault hard rule), so a claim
    can't go stale via its source file disappearing.
    """
    # FileLock creates its .lock file with O_CREAT, which on Windows still
    # requires the parent directory to already exist — mkdir before
    # acquiring, not after (system/state/ is normally bootstrapped ahead of
    # time, but nothing here should depend on that).
    hashes_file.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(hashes_file):
        data: dict = {}
        if hashes_file.exists():
            try:
                data = json.loads(hashes_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        entry = data.get(hash_)
        if entry and entry.get("path") != rel_path:
            return entry

        data[hash_] = {
            "path":        rel_path,
            "firstSeenAt": datetime.now(timezone.utc).isoformat(),
        }
        tmp = hashes_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(hashes_file)
        return None
