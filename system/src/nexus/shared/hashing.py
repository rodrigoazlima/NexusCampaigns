"""nexus.shared.hashing — canonical image-identity hash.

blake2b, 32-byte digest — the algorithm behind every "sha256" field in vault
state (processed-images.json, frontmatter, token-links.json). Not actual
SHA-256; the field name is historical and kept for on-disk compatibility.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_CHUNK_SIZE = 4_194_304


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def sha256_of_file(path: Path) -> str:
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    # Dashboard upload route: pipes file bytes on stdin, reads hex digest on stdout.
    print(sha256_of_bytes(sys.stdin.buffer.read()))
