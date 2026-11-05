from __future__ import annotations

import json
import platform
from pathlib import Path

from .model import Report


def summary(report: Report) -> str:
    count = len(report.findings)
    if count == 0:
        return "No invisible marks found. A clean copy was saved anyway."
    mark = "invisible mark" if count == 1 else "invisible marks"
    pages = len(report.pages_affected)
    if pages == 0:
        return f"Removed {count} {mark}."
    page_word = "page" if pages == 1 else "pages"
    return f"Removed {count} {mark} on {pages} {page_word}."


def finding_rows(report: Report) -> list[tuple[str, str, str, str]]:
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
