#!/usr/bin/env python3
"""Check whether a memo file already contains the expected edition title."""

from pathlib import Path
import sys


def is_current_memo(path: Path, expected_title: str) -> bool:
    """Return true when the first line matches, ignoring Markdown line breaks."""
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (FileNotFoundError, IndexError, OSError):
        return False
    return first_line.rstrip() == expected_title.rstrip()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"Usage: {argv[0]} MEMO_PATH EXPECTED_TITLE", file=sys.stderr)
        return 2
    return 0 if is_current_memo(Path(argv[1]), argv[2]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
