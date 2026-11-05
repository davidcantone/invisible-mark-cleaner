from __future__ import annotations

import json
import platform
from pathlib import Path

from .model import Analysis, Report
from .session import FileResult

NO_MARKS = "No invisible marks found."
NOTHING_SAVED = "No clean copy was made."


def _marks(found: Analysis | Report) -> str:
    count = len(found.findings)
    mark = "invisible mark" if count == 1 else "invisible marks"
    pages = len(found.pages_affected)
    if pages == 0:
        return f"{count} {mark}"
    page_word = "page" if pages == 1 else "pages"
    return f"{count} {mark} on {pages} {page_word}"


def summary(report: Report) -> str:
    if not report.findings:
        return f"{NO_MARKS} A clean copy was saved anyway."
    return f"Removed {_marks(report)}."


def analysis_summary(analysis: Analysis) -> str:
    if not analysis.has_marks:
        return f"{NO_MARKS} {NOTHING_SAVED}"
    return f"Found {_marks(analysis)}."


def clean_label(count: int) -> str:
    return "Clean PDF" if count <= 1 else f"Clean {count} PDFs"


def file_status(result: FileResult) -> str:
    if result.error is not None:
        return result.error
    if result.report is not None:
        return f"Cleaned: {result.report.output.name}"
    if result.clean_error is not None:
        return result.clean_error
    assert result.analysis is not None
    if not result.analysis.has_marks:
        return "No invisible marks"
    found = _marks(result.analysis)
    return found[0].upper() + found[1:]


def file_summary(result: FileResult) -> str:
    if result.error is not None:
        return result.error
    if result.report is not None:
        return summary(result.report)
    assert result.analysis is not None
    text = analysis_summary(result.analysis)
    if result.clean_error is not None:
        return f"{text} {result.clean_error}"
    if result.has_marks:
        return f"{text} Click {clean_label(1)} to save a clean copy."
    return text


def results_summary(files: tuple[FileResult, ...]) -> str:
    if len(files) == 1:
        return file_summary(files[0])
    marked = sum(1 for result in files if result.has_marks)
    cleaned = sum(1 for result in files if result.report is not None)
    unreadable = sum(1 for result in files if result.error is not None)
    parts = [f"Checked {len(files)} PDFs."]
    if marked == 0:
        parts.append(f"None has invisible marks. {NOTHING_SAVED}")
    elif marked == 1:
        parts.append("1 has invisible marks.")
    else:
        parts.append(f"{marked} have invisible marks.")
    if cleaned:
        parts.append(f"{cleaned} cleaned.")
    if unreadable:
        parts.append(f"{unreadable} could not be read.")
    return " ".join(parts)


def finding_rows(report: Analysis | Report) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for finding in report.findings:
        page = "Document" if finding.page is None else str(finding.page)
        text = " ".join(finding.text.split())
        detail = " ".join(finding.detail.split())
        rows.append((page, finding.kind.label, text, detail))
    return rows


def format_table(rows: list[tuple[str, str, str, str]]) -> str:
    headers = ("Page", "Type", "Text", "Details")
    if not rows:
        widths = [len(header) for header in headers]
    else:
        widths = [
            max(len(headers[index]), *(len(row[index]) for row in rows))
            for index in range(4)
        ]

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    rule = "  ".join("-" * width for width in widths)
    body = [line(headers), rule]
    body.extend(line(row) for row in rows)
    return "\n".join(body)


def format_report(report: Report) -> str:
    parts = [summary(report), "", str(report.output), "", format_table(finding_rows(report))]
    return "\n".join(parts) + "\n"


def report_payload(report: Report) -> dict:
    return {
        "source": str(report.source),
        "output": str(report.output),
        "page_count": report.page_count,
        "pages_affected": list(report.pages_affected),
        "findings": [
            {
                "kind": finding.kind.label,
                "page": finding.page,
                "text": finding.text,
                "detail": finding.detail,
            }
            for finding in report.findings
        ],
    }


def report_json_path(output: Path) -> Path:
    return Path(str(output) + ".report.json")


def write_report_json(report: Report) -> Path:
    path = report_json_path(report.output)
    path.write_text(
        json.dumps(report_payload(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def reveal_label(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Darwin":
        return "Show in Finder"
    if system == "Windows":
        return "Show in Explorer"
    return "Show in folder"


def reveal_command(path: Path, system: str | None = None) -> list[str]:
    system = system or platform.system()
    if system == "Darwin":
        return ["open", "-R", str(path)]
    if system == "Windows":
        # Explorer wants the comma attached to /select, in the same argument.
        return ["explorer", "/select," + str(path)]
    return ["xdg-open", str(path.parent)]
