# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
# ─── How to run ───
# uv run scripts/update_pin.py <commit> <total>
# ──────────────────
"""Update the pinned upstream constants after a new catalog is extracted."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Final


class _Args(argparse.Namespace):
    """Typed namespace for parsed CLI arguments."""

    commit: str = ""
    total: int = 0


REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

SOURCE_COMMIT_RE: Final[re.Pattern[str]] = re.compile(
    r'(SOURCE_COMMIT: Final\[str\] = ")[^"]+(")'
)
EXPECTED_TOTAL_RE: Final[re.Pattern[str]] = re.compile(
    r"(EXPECTED_TOTAL_SKILLS: Final\[int\] = )\d+"
)


def _replace_in_file(path: Path, new_commit: str, new_total: int) -> None:
    """Replace the pinned constants in a single file if present."""
    text = path.read_text(encoding="utf-8")
    original = text

    text = SOURCE_COMMIT_RE.sub(lambda m: f"{m.group(1)}{new_commit}{m.group(2)}", text)
    text = EXPECTED_TOTAL_RE.sub(lambda m: f"{m.group(1)}{new_total}", text)

    if text != original:
        _ = path.write_text(text, encoding="utf-8")


def main() -> None:
    """Parse CLI args and update pinned constants."""
    parser = argparse.ArgumentParser(
        description="Update pinned upstream commit and expected skill count."
    )
    _ = parser.add_argument("commit", help="New upstream commit hash.")
    _ = parser.add_argument(
        "total", type=int, help="New expected total number of skills."
    )
    args = parser.parse_args(namespace=_Args())

    _replace_in_file(
        REPO_ROOT / "scripts" / "generate_directory.py", args.commit, args.total
    )
    _replace_in_file(REPO_ROOT / "tests" / "test_directory.py", args.commit, args.total)


if __name__ == "__main__":
    main()
