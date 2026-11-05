from __future__ import annotations

from pathlib import Path

from invisible_mark_cleaner.model import Finding, MarkKind, Report

LONG_TEXT = "hidden fragment " * 12

DEFAULT_FINDINGS = (
    Finding(MarkKind.WHITE_TEXT, 1, LONG_TEXT, "near-white fill on a light background"),
    Finding(MarkKind.TRANSPARENT_TEXT, 2, "see-through line", "alpha 0"),
    Finding(MarkKind.INVISIBLE_TEXT, 2, "render mode three", "text render mode 3"),
    Finding(MarkKind.METADATA, None, "Author", "marker-like Info field"),
)


def sample_report(
    source: Path,
    output: Path | None = None,
    findings: tuple[Finding, ...] | None = None,
    page_count: int = 2,
) -> Report:
    dest = output or source.with_name(source.stem + "-clean.pdf")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    if findings is None:
        findings = DEFAULT_FINDINGS
    return Report(source=source, output=dest, page_count=page_count, findings=findings)
