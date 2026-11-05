#!/usr/bin/env python3
"""Open the real window, drop one PDF, and save Idle and Done screenshots."""

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


def run(pdf: Path, outdir: Path, timeout: float = 30.0) -> int:
    configure_platform()
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication

    from invisible_mark_cleaner.app import MainWindow, create_application
    from invisible_mark_cleaner.session import Done, Failed

    outdir.mkdir(parents=True, exist_ok=True)
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
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
    mime.setUrls([QUrl.fromLocalFile(str(pdf))])
    drop = QDropEvent(
        QPointF(40, 40),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if isinstance(window.session, (Done, Failed)):
            break
        time.sleep(0.02)
    else:
        print("timed out waiting for a result", file=sys.stderr)
        window.close()
        return 1

    app.processEvents()
    if isinstance(window.session, Failed):
        save_grab("failed.png")
        print(window.session.message, file=sys.stderr)
        window.close()
        return 1
    if not isinstance(window.session, Done):
        print("window did not finish", file=sys.stderr)
        window.close()
        return 1
    if not save_grab("done.png"):
        window.close()
        return 1
    window.close()
    print(window.session.report.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ui_smoke.py")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("outdir", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    if not args.pdf.is_file():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1
    return run(args.pdf, args.outdir, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
