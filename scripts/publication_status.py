"""Sanitized, content-bound receipt for the edition visible on the public site."""

import hashlib
import json
from pathlib import Path


def memo_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publication_status(memo: Path) -> dict:
    title = memo.read_text(encoding="utf-8").splitlines()[0].strip()
    status = {
        "schemaVersion": 1,
        "editionDate": memo.stem.removeprefix("memo-"),
        "editionMode": "intraday" if title.startswith("Intraday Market Memo") else "preopen",
        "title": title,
        "memoSha256": memo_hash(memo),
        "qualityPassed": False,
        "researchCutoff": None,
        "generatedAt": None,
    }
    try:
        receipt = json.loads(memo.with_suffix(".status.json").read_text(encoding="utf-8"))
        if (isinstance(receipt, dict)
                and all(receipt.get(key) == status[key] for key in
                        ("schemaVersion", "editionDate", "editionMode", "memoSha256"))
                and receipt.get("qualityPassed") is True
                and isinstance(receipt.get("researchCutoff"), str)
                and isinstance(receipt.get("generatedAt"), str)):
            # Explicit allowlist: source evidence and private audits never become public.
            for key in ("qualityPassed", "researchCutoff", "generatedAt"):
                status[key] = receipt[key]
    except (OSError, ValueError):
        pass
    return status
