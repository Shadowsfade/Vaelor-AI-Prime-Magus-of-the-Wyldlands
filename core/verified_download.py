"""Bounded, pinned SHA-256 downloads; publish only verified bytes."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.request

MAX_BYTES = 32 * 1024 * 1024


def verify_file(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("A reviewed SHA-256 checksum is required.")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Artifact must be a regular file, not a symbolic link.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("Artifact exceeds the 32 MiB limit.")
            digest.update(chunk)
    if not size or not hmac.compare_digest(digest.hexdigest(), expected):
        raise ValueError("Artifact SHA-256 mismatch; execution blocked.")
    return size, digest.hexdigest()


def download_verified(url, target, expected):
    if not url.startswith("https://"):
        raise ValueError("Verified artifacts require HTTPS.")
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("A reviewed SHA-256 checksum is required before downloading.")
    target = Path(target)
    started = time.monotonic()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(url, timeout=20) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Artifact redirect left HTTPS.")
                total = 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > MAX_BYTES or time.monotonic() - started > 60:
                        raise ValueError("Artifact exceeded download size or time limit.")
                    output.write(chunk)
        size, checksum = verify_file(temporary, expected)
        temporary.chmod(temporary.stat().st_mode | 0o111)
        os.replace(temporary, target)
        return size, checksum
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
