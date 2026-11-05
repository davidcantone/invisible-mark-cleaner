from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .model import Analysis, OutputNotWritable, Report

DROP_PDFS_ONLY = "Drop PDF files only."
SAME_AS_ORIGINAL = "Choose a different file. The original PDF stays as it is."


@dataclass(frozen=True)
class FileResult:
    source: Path
    analysis: Analysis | None = None
    error: str | None = None
    report: Report | None = None
    clean_error: str | None = None

    @property
    def has_marks(self) -> bool:
        return self.analysis is not None and self.analysis.has_marks

    @property
    def needs_cleaning(self) -> bool:
        return self.has_marks and self.report is None


@dataclass(frozen=True)
class Idle:
    notice: str | None = None


@dataclass(frozen=True)
class Analyzing:
    sources: tuple[Path, ...]
    done: tuple[FileResult, ...] = ()

    @property
    def current(self) -> Path:
        return self.sources[len(self.done)]


@dataclass(frozen=True)
class Results:
    files: tuple[FileResult, ...]


@dataclass(frozen=True)
class Cleaning:
    files: tuple[FileResult, ...]
    pending: tuple[int, ...]
    output: Path | None = None

    @property
    def current(self) -> Path:
        return self.files[self.pending[0]].source


Session = Idle | Analyzing | Results | Cleaning
BUSY = (Analyzing, Cleaning)


@dataclass(frozen=True)
class CleanFailure:
    message: str
    save_as: Path | None = None


def pdf_paths(paths: list[Path]) -> tuple[Path, ...] | None:
    """The dropped or chosen PDFs in order, without repeats; None unless every path is a PDF."""
    if not paths or any(path.suffix.lower() != ".pdf" for path in paths):
        return None
    return tuple(dict.fromkeys(paths))


def to_clean(files: tuple[FileResult, ...]) -> tuple[int, ...]:
    return tuple(index for index, result in enumerate(files) if result.needs_cleaning)


def with_result(files: tuple[FileResult, ...], index: int, **changes) -> tuple[FileResult, ...]:
    return files[:index] + (replace(files[index], **changes),) + files[index + 1:]


def failure_message(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or "This PDF could not be cleaned."


def clean_failure(exc: BaseException) -> CleanFailure:
    if isinstance(exc, OutputNotWritable):
        return CleanFailure(failure_message(exc), exc.path)
    return CleanFailure(failure_message(exc))
