from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = ("synth" + "etic", "fa" + "ke")


SKIPPED_DIRS = {".git", ".venv", "build", "dist", "__pycache__", ".pytest_cache"}


def tracked_and_new_files() -> list[Path]:
    """Repo files per git, or the whole tree minus build output when run from a source archive."""
    if (ROOT / ".git").exists():
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        return [ROOT / line for line in out.splitlines() if (ROOT / line).is_file()]
    return [
        path for path in ROOT.rglob("*")
        if path.is_file()
        and not SKIPPED_DIRS.intersection(path.relative_to(ROOT).parts)
        and not any(part.endswith(".egg-info") for part in path.parts)
    ]


def test_banned_words_appear_nowhere_in_the_repo():
    offenders = []
    for path in tracked_and_new_files():
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        offenders += [f"{path.relative_to(ROOT)}: {word}" for word in BANNED if word in text]
    assert offenders == []
