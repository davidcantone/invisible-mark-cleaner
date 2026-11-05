from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class MarkKind(Enum):
    WHITE_TEXT = "White text"
    TRANSPARENT_TEXT = "Transparent text"
    INVISIBLE_TEXT = "Invisible text mode"
    HIDDEN_LAYER = "Hidden layer"
    METADATA = "Metadata field"

    @property
    def label(self) -> str:
        return self.value


@dataclass(frozen=True)
class Finding:
    kind: MarkKind
    page: int | None
    text: str
    detail: str


class _Findings:
    findings: tuple[Finding, ...]

    def count(self, kind: MarkKind) -> int:
        return sum(1 for f in self.findings if f.kind is kind)

    @property
    def pages_affected(self) -> tuple[int, ...]:
        return tuple(sorted({f.page for f in self.findings if f.page is not None}))


@dataclass(frozen=True)
class Analysis(_Findings):
    source: Path
    page_count: int
    findings: tuple[Finding, ...]

    @property
    def has_marks(self) -> bool:
        return bool(self.findings)


@dataclass(frozen=True)
class Report(_Findings):
    source: Path
    output: Path
    page_count: int
    findings: tuple[Finding, ...]


class CleanError(Exception):
    """Raised for inputs the cleaner cannot process. The message is shown to the user as is."""


class OutputNotWritable(CleanError):
    """The clean copy could not be written to the requested path (for example a read-only folder)."""

    def __init__(self, path: Path, message: str):
        super().__init__(message)
        self.path = path
