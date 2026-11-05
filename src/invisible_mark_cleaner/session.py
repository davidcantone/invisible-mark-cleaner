from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import OutputNotWritable, Report

DROP_ONE_PDF = "Drop one PDF at a time."


@dataclass(frozen=True)
class Idle:
    notice: str | None = None


@dataclass(frozen=True)
class Working:
    source: Path
    output: Path | None = None


@dataclass(frozen=True)
class Done:
    report: Report


@dataclass(frozen=True)
class Failed:
    message: str


Session = Idle | Working | Done | Failed


@dataclass(frozen=True)
class CleanFailure:
    message: str
    save_as: Path | None = None


def single_pdf(paths: list[Path]) -> Path | None:
    if len(paths) != 1:
        return None
    path = paths[0]
    if path.suffix.lower() != ".pdf":
        return None
    return path


def failure_message(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or "This PDF could not be cleaned."


def clean_failure(exc: BaseException) -> CleanFailure:
    if isinstance(exc, OutputNotWritable):
        return CleanFailure(failure_message(exc), exc.path)
    return CleanFailure(failure_message(exc))
