from __future__ import annotations

import argparse
import sys
from pathlib import Path

from invisible_mark_cleaner import CleanError, clean_pdf
from invisible_mark_cleaner.present import format_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invisible-mark-cleaner-cli")
    parser.add_argument("file", type=Path, help="PDF to clean")
    parser.add_argument("-o", "--output", type=Path, help="where to write the clean copy")
    args = parser.parse_args(argv)
    try:
        report = clean_pdf(args.file, args.output)
    except CleanError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(format_report(report))
    return 0
