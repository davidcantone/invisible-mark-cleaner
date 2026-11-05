from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from invisible_mark_cleaner import CleanError, clean_pdf
from invisible_mark_cleaner.present import (
    finding_rows,
    reveal_command,
    reveal_label,
    summary,
    write_report_json,
)
from invisible_mark_cleaner.session import (
    DROP_ONE_PDF,
    CleanFailure,
    Done,
    Failed,
    Idle,
    Session,
    Working,
    clean_failure,
    single_pdf,
)

STYLESHEET = """
QMainWindow, QWidget#page {
    background: #eef1f5;
    color: #1c2330;
}
QLabel {
    background: transparent;
    color: #1c2330;
}
QLabel#appTitle {
    font-size: 22px;
    font-weight: 600;
}
QFrame#dropZone {
    background: #ffffff;
    border: 2px dashed #b7c0ce;
    border-radius: 16px;
}
QLabel#dropTitle {
    font-size: 28px;
    font-weight: 600;
}
QLabel#dropHint, QLabel#pathLabel, QLabel#workingHint {
    color: #5c6778;
}
QLabel#notice, QLabel#failedMessage {
    color: #8d2f2f;
}
QLabel#summary {
    font-size: 16px;
}
QLabel#failedMessage {
    font-size: 16px;
}
QPushButton {
    background: #2c5278;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    min-height: 36px;
}
QPushButton:hover {
    background: #234463;
}
QPushButton:pressed {
    background: #1b364f;
}
QPushButton#secondary {
    background: #e4e8ef;
    color: #1c2330;
}
QPushButton#secondary:hover {
    background: #d5dbe4;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f6f8fb;
    border: 1px solid #e1e5ec;
    border-radius: 8px;
    gridline-color: #eef1f5;
    selection-background-color: #d9e4f0;
    selection-color: #1c2330;
}
QHeaderView::section {
    background: #f7f8fa;
    color: #1c2330;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #e1e5ec;
    font-weight: 600;
}
QProgressBar {
    border: none;
    background: #e1e6ee;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk {
    background: #2c5278;
    border-radius: 5px;
}
"""


def prepare_application() -> None:
    if QApplication.instance() is not None:
        return
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


class CleanerApplication(QApplication):
    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.setApplicationDisplayName("Invisible Mark Cleaner")
        self.setStyle("Fusion")
        font = QFont(self.font())
        font.setPointSize(12)
        self.setFont(font)
        self.setStyleSheet(STYLESHEET)
        self._window: MainWindow | None = None
        self._queued: list[Path] = []

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            self.note_open(Path(event.file()))
            return True
        return super().event(event)

    def note_open(self, path: Path) -> None:
        if self._window is None:
            self._queued.append(path)
            return
        self._window.submit_pdf(path)

    def attach(self, window: MainWindow) -> None:
        self._window = window
        queued = list(self._queued)
        self._queued.clear()
        for path in queued:
            window.submit_pdf(path)


class _CleanWorker(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, object)

    def __init__(self, token: int, source: Path, output: Path | None) -> None:
        super().__init__()
        self._token = token
        self._source = source
        self._output = output

    def run(self) -> None:
        try:
            report = clean_pdf(self._source, self._output)
        except Exception as exc:
            self.failed.emit(self._token, clean_failure(exc))
        else:
            self.succeeded.emit(self._token, report)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Invisible Mark Cleaner")
        self.setMinimumSize(760, 520)
        self.resize(880, 640)
        self.session: Session = Idle()
        self._worker: _CleanWorker | None = None
        self._token = 0

        root = QWidget()
        root.setObjectName("page")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        title = QLabel("Invisible Mark Cleaner")
        title.setObjectName("appTitle")
        outer.addWidget(title)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.idle_page = self._build_idle()
        self.working_page = self._build_working()
        self.done_page = self._build_done()
        self.failed_page = self._build_failed()
        for page in (self.idle_page, self.working_page, self.done_page, self.failed_page):
            self.stack.addWidget(page)

        self._accept_drops(root)
        self._render_idle(Idle())
        self.stack.setCurrentWidget(self.idle_page)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _accept_drops(self, root: QWidget) -> None:
        self.setAcceptDrops(True)
        root.setAcceptDrops(True)
        for widget in root.findChildren(QWidget):
            widget.setAcceptDrops(True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        root = self.centralWidget()
        if root is not None:
            self._accept_drops(root)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not self._is_ours(obj):
            return False
        kind = event.type()
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            self.dragEnterEvent(event)
            return True
        if kind == QEvent.Type.Drop:
            self.dropEvent(event)
            return True
        return False

    def _is_ours(self, obj: QObject) -> bool:
        while obj is not None:
            if obj is self:
                return True
            obj = obj.parent()
        return False

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        paths: list[Path] = []
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    paths.append(Path(url.toLocalFile()))
        self.receive_paths(paths)
        event.acceptProposedAction()

    def receive_paths(self, paths: list[Path]) -> None:
        if isinstance(self.session, Working):
            return
        chosen = single_pdf(paths)
        if chosen is None:
            self.apply(Idle(DROP_ONE_PDF))
            return
        self.apply(Working(chosen))
        self._start(chosen, None)

    def submit_pdf(self, source: Path) -> None:
        self.receive_paths([source])

    def apply(self, session: Session) -> None:
        self.session = session
        if isinstance(session, Idle):
            self._render_idle(session)
            self.stack.setCurrentWidget(self.idle_page)
        elif isinstance(session, Working):
            self._render_working(session)
            self.stack.setCurrentWidget(self.working_page)
        elif isinstance(session, Done):
            self._render_done(session)
            self.stack.setCurrentWidget(self.done_page)
        elif isinstance(session, Failed):
            self._render_failed(session)
            self.stack.setCurrentWidget(self.failed_page)
        else:
            raise TypeError(type(session))

    def _start(self, source: Path, output: Path | None) -> None:
        self._token += 1
        token = self._token
        worker = _CleanWorker(token, source, output)
        worker.succeeded.connect(self._on_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)
        self._worker = worker
        worker.start()

    def _on_succeeded(self, token: int, report) -> None:
        if token != self._token:
            return
        self.apply(Done(report))

    def _on_failed(self, token: int, failure: CleanFailure) -> None:
        if token != self._token:
            return
        if failure.save_as is not None and isinstance(self.session, Working):
            self._prompt_save_as(self.session.source, failure)
            return
        self.apply(Failed(failure.message))

    def _prompt_save_as(self, source: Path, failure: CleanFailure) -> None:
        suggested = str(failure.save_as) if failure.save_as is not None else ""
        chosen, _selected = QFileDialog.getSaveFileName(
            self,
            "Save clean PDF",
            suggested,
            "PDF files (*.pdf)",
        )
        if not chosen:
            self.apply(Failed(failure.message))
            return
        dest = Path(chosen)
        if dest.suffix.lower() != ".pdf":
            dest = dest.with_suffix(".pdf")
        try:
            same = dest.resolve() == source.resolve()
        except OSError:
            same = False
        if same:
            self.apply(Failed("Choose a different file. The original PDF stays as it is."))
            return
        self.apply(Working(source, dest))
        self._start(source, dest)

    def _choose(self) -> None:
        if isinstance(self.session, Working):
            return
        chosen, _selected = QFileDialog.getOpenFileName(
            self,
            "Choose PDF",
            str(Path.home()),
            "PDF files (*.pdf)",
        )
        if chosen:
            self.receive_paths([Path(chosen)])

    def _reveal(self) -> None:
        if not isinstance(self.session, Done):
            return
        subprocess.run(reveal_command(self.session.report.output), check=False)

    def _open_pdf(self) -> None:
        if not isinstance(self.session, Done):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.report.output)))

    def _reset(self) -> None:
        if isinstance(self.session, Working):
            return
        self.apply(Idle())

    def _build_idle(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        zone = QFrame()
        zone.setObjectName("dropZone")
        zone.setMinimumHeight(240)
        zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        zone_layout = QVBoxLayout(zone)
        zone_layout.setContentsMargins(24, 24, 24, 24)
        zone_layout.addStretch(1)
        drop_title = QLabel("Drop a PDF here")
        drop_title.setObjectName("dropTitle")
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("One PDF. The original stays where it is.")
        hint.setObjectName("dropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone_layout.addWidget(drop_title)
        zone_layout.addSpacing(8)
        zone_layout.addWidget(hint)
        zone_layout.addStretch(1)

        self.choose_button = QPushButton("Choose PDF...")
        self.choose_button.setMinimumWidth(180)
        self.choose_button.clicked.connect(self._choose)
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.choose_button)
        button_row.addStretch(1)

        self.notice_label = QLabel("")
        self.notice_label.setObjectName("notice")
        self.notice_label.setWordWrap(True)
        self.notice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice_label.setVisible(False)

        layout.addWidget(zone, 1)
        layout.addLayout(button_row)
        layout.addWidget(self.notice_label)
        return page

    def _build_working(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self.working_label = QLabel("Checking...")
        self.working_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.working_label.setWordWrap(True)
        hint = QLabel("The original file is left as it is.")
        hint.setObjectName("workingHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(360)
        bar_row.addStretch(1)
        bar_row.addWidget(self.progress)
        bar_row.addStretch(1)
        layout.addWidget(self.working_label)
        layout.addSpacing(12)
        layout.addLayout(bar_row)
        layout.addSpacing(8)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_done(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("summary")
        self.summary_label.setWordWrap(True)
        self.path_label = QLabel("")
        self.path_label.setObjectName("pathLabel")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.reveal_button = QPushButton(reveal_label())
        self.reveal_button.setObjectName("secondary")
        self.open_button = QPushButton("Open clean PDF")
        self.again_button = QPushButton("Clean another PDF")
        self.again_button.setObjectName("secondary")
        for button in (self.reveal_button, self.open_button, self.again_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reveal_button.clicked.connect(self._reveal)
        self.open_button.clicked.connect(self._open_pdf)
        self.again_button.clicked.connect(self._reset)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.reveal_button)
        row.addWidget(self.open_button)
        row.addStretch(1)
        row.addWidget(self.again_button)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Page", "Type", "Text", "Details"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)

        layout.addWidget(self.summary_label)
        layout.addWidget(self.path_label)
        layout.addLayout(row)
        layout.addWidget(self.table, 1)
        return page

    def _build_failed(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self.failed_label = QLabel("")
        self.failed_label.setObjectName("failedMessage")
        self.failed_label.setWordWrap(True)
        self.failed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.retry_button = QPushButton("Try another PDF")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(self._reset)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.retry_button)
        button_row.addStretch(1)
        layout.addWidget(self.failed_label)
        layout.addSpacing(16)
        layout.addLayout(button_row)
        layout.addStretch(1)
        return page

    def _render_idle(self, session: Idle) -> None:
        notice = session.notice or ""
        self.notice_label.setText(notice)
        self.notice_label.setVisible(bool(notice))

    def _render_working(self, session: Working) -> None:
        self.working_label.setText(f"Checking {session.source.name}...")

    def _render_done(self, session: Done) -> None:
        report = session.report
        self.summary_label.setText(summary(report))
        self.path_label.setText(str(report.output))
        self.reveal_button.setText(reveal_label())
        rows = finding_rows(report)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(value)
                self.table.setItem(row_index, column, item)
        self.table.resizeRowsToContents()

    def _render_failed(self, session: Failed) -> None:
        self.failed_label.setText(session.message)

    def closeEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)
        super().closeEvent(event)


def create_application() -> QApplication:
    prepare_application()
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return CleanerApplication(["invisible-mark-cleaner"])


def pdf_args(argv: list[str]) -> list[Path]:
    paths: list[Path] = []
    skip_value = False
    for arg in argv:
        if skip_value:
            skip_value = False
            continue
        if arg in {"-o", "--output"}:
            skip_value = True
            continue
        if arg.startswith("-"):
            continue
        path = Path(arg)
        if path.suffix.lower() == ".pdf":
            paths.append(path)
    return paths


def headless(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="invisible-mark-cleaner")
    parser.add_argument("--clean", required=True, type=Path, help="PDF to clean")
    parser.add_argument("--output", type=Path, help="where to write the clean copy")
    args = parser.parse_args(argv)
    try:
        report = clean_pdf(args.clean, args.output)
    except CleanError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        path = write_report_json(report)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(summary(report))
    print(report.output)
    print(path)
    return 0


def gui(argv: list[str]) -> int:
    application = create_application()
    application.setQuitOnLastWindowClosed(True)
    window = MainWindow()
    if isinstance(application, CleanerApplication):
        application.attach(window)
    paths = pdf_args(argv)
    if paths:
        window.submit_pdf(paths[0])
    window.show()
    return int(application.exec())


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--clean" in argv:
        return headless(argv)
    return gui(argv)
