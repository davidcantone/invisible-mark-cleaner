#!/usr/bin/env python3
"""Open the real window, drop PDFs, and save screenshots of the drop zone, the report and,
when marks were found, the result of clicking Clean PDF."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def configure_platform() -> None:
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    elif sys.platform.startswith("linux"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def run(pdf: Path | list[Path], outdir: Path, timeout: float = 30.0) -> int:
    configure_platform()
    from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    from invisible_mark_cleaner.app import MainWindow, create_application
    from invisible_mark_cleaner.session import BUSY, Results

    pdfs = [pdf] if isinstance(pdf, Path) else list(pdf)
    outdir.mkdir(parents=True, exist_ok=True)
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(QSettings(str(outdir / "settings.ini"), QSettings.Format.IniFormat))
    window.resize(880, 640)
    window.show()
    app.processEvents()

    def save_grab(name: str) -> bool:
        window.repaint()
        app.processEvents()
        pixmap = window.grab()
        if pixmap.isNull() or pixmap.width() < 760 or pixmap.height() < 520:
            print(
                f"screenshot {name} is {pixmap.width()}x{pixmap.height()}",
                file=sys.stderr,
            )
            return False
        path = outdir / name
        if not pixmap.save(str(path), "PNG"):
            print(f"could not save {path}", file=sys.stderr)
            return False
        return True

    if not save_grab("idle.png"):
        window.close()
        return 1

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in pdfs])
    drop = QDropEvent(
        QPointF(40, 40),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop)

    def settle() -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if not isinstance(window.session, BUSY):
                app.processEvents()
                return isinstance(window.session, Results)
            time.sleep(0.02)
        print("timed out waiting for a result", file=sys.stderr)
        return False

    if not settle() or not save_grab("report.png"):
        window.close()
        return 1
    files = window.session.files
    unreadable = [result for result in files if result.error is not None]
    for result in unreadable:
        print(f"{result.source}: {result.error}", file=sys.stderr)
    if not window.clean_button.isEnabled():
        window.close()
        print("No invisible marks found. No clean copy was made.")
        return 1 if unreadable else 0

    window.clean_button.click()
    if not settle() or not save_grab("done.png"):
        window.close()
        return 1
    window.close()
    for result in window.session.files:
        if result.report is not None:
            print(result.report.output)
        elif result.clean_error is not None:
            print(f"{result.source}: {result.clean_error}", file=sys.stderr)
    failed = any(result.clean_error is not None and result.report is None for result in window.session.files)
    return 1 if unreadable or failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ui_smoke.py")
    parser.add_argument("pdf", type=Path, nargs="+")
    parser.add_argument("outdir", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    for pdf in args.pdf:
        if not pdf.is_file():
            print(f"PDF not found: {pdf}", file=sys.stderr)
            return 1
    return run(args.pdf, args.outdir, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
