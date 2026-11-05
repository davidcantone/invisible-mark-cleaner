from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, QThread, QUrl, Qt, Signal
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

from invisible_mark_cleaner import CleanError, analyze_pdf, clean_pdf
from invisible_mark_cleaner.present import (
    clean_label,
    file_status,
    finding_rows,
    results_summary,
    reveal_command,
    reveal_label,
    summary,
    write_report_json,
)
from invisible_mark_cleaner.session import (
    BUSY,
    DROP_PDFS_ONLY,
    SAME_AS_ORIGINAL,
    Analyzing,
    CleanFailure,
    Cleaning,
    FileResult,
    Idle,
    Results,
    Session,
    clean_failure,
    pdf_paths,
    to_clean,
    with_result,
)

APP_NAME = "Invisible Mark Cleaner"
LAST_DIRECTORY = "last_directory"

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
QPushButton:disabled {
    background: #c9d0da;
    color: #f4f6f9;
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
        self.setApplicationDisplayName(APP_NAME)
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
        if queued:
            window.receive_paths(queued)


class _Job(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, object)

    def __init__(self, token: int, work: Callable[[], object]) -> None:
        super().__init__()
        self._token = token
        self._work = work

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as exc:
            self.failed.emit(self._token, clean_failure(exc))
        else:
            self.succeeded.emit(self._token, result)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(760, 520)
        self.resize(880, 640)
        self.session: Session = Idle()
        self.settings = settings if settings is not None else QSettings(APP_NAME, APP_NAME)
        self._worker: _Job | None = None
        self._token = 0

        root = QWidget()
        root.setObjectName("page")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        outer.addWidget(title)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.idle_page = self._build_idle()
        self.working_page = self._build_working()
        self.results_page = self._build_results()
        for page in (self.idle_page, self.working_page, self.results_page):
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
        session = self.session
        if isinstance(session, Cleaning):
            return
        sources = pdf_paths(paths)
        if isinstance(session, Analyzing):
            extra = tuple(path for path in sources or () if path not in session.sources)
            if extra:
                self.apply(Analyzing(session.sources + extra, session.done))
            return
        if sources is None:
            self.apply(Idle(DROP_PDFS_ONLY))
            return
        self.apply(Analyzing(sources))
        self._analyze_next()

    def submit_pdf(self, source: Path) -> None:
        self.receive_paths([source])

    def apply(self, session: Session) -> None:
        self.session = session
        if isinstance(session, Idle):
            self._render_idle(session)
            self.stack.setCurrentWidget(self.idle_page)
        elif isinstance(session, (Analyzing, Cleaning)):
            self._render_working(session)
            self.stack.setCurrentWidget(self.working_page)
        elif isinstance(session, Results):
            self._render_results(session)
            self.stack.setCurrentWidget(self.results_page)
        else:
            raise TypeError(type(session))

    def _start(self, work: Callable[[], object]) -> None:
        previous = self._worker
        if previous is not None:
            previous.wait()
        self._token += 1
        worker = _Job(self._token, work)
        worker.succeeded.connect(self._on_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)
        self._worker = worker
        worker.start()

    def _analyze_next(self) -> None:
        source = self.session.current
        self._start(lambda: analyze_pdf(source))

    def _clean_next(self) -> None:
        source, output = self.session.current, self.session.output
        self._start(lambda: clean_pdf(source, output))

    def _on_succeeded(self, token: int, result) -> None:
        if token != self._token:
            return
        session = self.session
        if isinstance(session, Analyzing):
            self._analyzed(FileResult(session.current, analysis=result))
        elif isinstance(session, Cleaning):
            self._cleaned(report=result)

    def _on_failed(self, token: int, failure: CleanFailure) -> None:
        if token != self._token:
            return
        session = self.session
        if isinstance(session, Analyzing):
            self._analyzed(FileResult(session.current, error=failure.message))
        elif isinstance(session, Cleaning):
            if failure.save_as is not None:
                self._prompt_save_as(session, failure)
            else:
                self._cleaned(clean_error=failure.message)

    def _analyzed(self, result: FileResult) -> None:
        session = self.session
        done = session.done + (result,)
        if len(done) < len(session.sources):
            self.apply(Analyzing(session.sources, done))
            self._analyze_next()
        else:
            self.files_table.setCurrentCell(-1, -1)
            self.apply(Results(done))

    def _clean(self) -> None:
        if not isinstance(self.session, Results):
            return
        pending = to_clean(self.session.files)
        if not pending:
            return
        self.apply(Cleaning(self.session.files, pending))
        self._clean_next()

    def _cleaned(self, report=None, clean_error: str | None = None) -> None:
        session = self.session
        files = with_result(session.files, session.pending[0], report=report, clean_error=clean_error)
        rest = session.pending[1:]
        if rest:
            self.apply(Cleaning(files, rest))
            self._clean_next()
            return
        if files[self._selected_index(files)].report is None:
            cleaned = [index for index, result in enumerate(files) if result.report is not None]
            if cleaned:
                self.files_table.setCurrentCell(cleaned[0], 0)
        self.apply(Results(files))

    def _prompt_save_as(self, session: Cleaning, failure: CleanFailure) -> None:
        source = session.current
        suggested = str(failure.save_as) if failure.save_as is not None else ""
        chosen, _selected = QFileDialog.getSaveFileName(
            self,
            "Save clean PDF",
            suggested,
            "PDF files (*.pdf)",
        )
        if not chosen:
            self._cleaned(clean_error=failure.message)
            return
        dest = Path(chosen)
        if dest.suffix.lower() != ".pdf":
            dest = dest.with_suffix(".pdf")
        try:
            same = dest.resolve() == source.resolve()
        except OSError:
            same = False
        if same:
            self._cleaned(clean_error=SAME_AS_ORIGINAL)
            return
        self.apply(Cleaning(session.files, session.pending, dest))
        self._clean_next()

    def last_directory(self) -> str:
        folder = self.settings.value(LAST_DIRECTORY, "", type=str)
        if folder and Path(folder).is_dir():
            return folder
        return str(Path.home())

    def _remember_directory(self, folder: Path) -> None:
        self.settings.setValue(LAST_DIRECTORY, str(folder))
        self.settings.sync()

    def _choose(self) -> None:
        if isinstance(self.session, BUSY):
            return
        chosen, _selected = QFileDialog.getOpenFileNames(
            self,
            "Choose PDFs",
            self.last_directory(),
            "PDF files (*.pdf)",
        )
        if chosen:
            paths = [Path(path) for path in chosen]
            self._remember_directory(paths[0].parent)
            self.receive_paths(paths)

    def _selected_index(self, files: tuple[FileResult, ...]) -> int:
        row = self.files_table.currentRow()
        return row if 0 <= row < len(files) else 0

    def selected_file(self) -> FileResult | None:
        if not isinstance(self.session, Results):
            return None
        files = self.session.files
        return files[self._selected_index(files)]

    def _reveal(self) -> None:
        selected = self.selected_file()
        if selected is None or selected.report is None:
            return
        subprocess.run(reveal_command(selected.report.output), check=False)

    def _open_pdf(self) -> None:
        selected = self.selected_file()
        if selected is None or selected.report is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(selected.report.output)))

    def _reset(self) -> None:
        if isinstance(self.session, BUSY):
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
        drop_title = QLabel("Drop PDFs here")
        drop_title.setObjectName("dropTitle")
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("One or more PDFs. They are checked first. Nothing is saved until you click Clean PDF.")
        hint.setWordWrap(True)
        hint.setObjectName("dropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone_layout.addWidget(drop_title)
        zone_layout.addSpacing(8)
        zone_layout.addWidget(hint)
        zone_layout.addStretch(1)

        self.choose_button = QPushButton("Choose PDFs...")
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
        self.working_hint = QLabel("")
        hint = self.working_hint
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

    def _build_results(self) -> QWidget:
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

        self.files_table = QTableWidget(0, 2)
        self.files_table.setHorizontalHeaderLabels(["PDF", "Result"])
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.files_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.files_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.files_table.setWordWrap(False)
        self.files_table.setShowGrid(False)
        files_header = self.files_table.horizontalHeader()
        files_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        files_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.files_table.currentCellChanged.connect(self._on_file_selected)

        self.clean_button = QPushButton(clean_label(1))
        self.reveal_button = QPushButton(reveal_label())
        self.reveal_button.setObjectName("secondary")
        self.open_button = QPushButton("Open clean PDF")
        self.open_button.setObjectName("secondary")
        self.again_button = QPushButton("Check other PDFs")
        self.again_button.setObjectName("secondary")
        for button in (self.clean_button, self.reveal_button, self.open_button, self.again_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clean_button.clicked.connect(self._clean)
        self.reveal_button.clicked.connect(self._reveal)
        self.open_button.clicked.connect(self._open_pdf)
        self.again_button.clicked.connect(self._reset)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.clean_button)
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
        layout.addWidget(self.files_table)
        layout.addWidget(self.path_label)
        layout.addLayout(row)
        layout.addWidget(self.table, 1)
        self.results_spacer = QWidget()
        layout.addWidget(self.results_spacer, 1)
        return page

    def _render_idle(self, session: Idle) -> None:
        notice = session.notice or ""
        self.notice_label.setText(notice)
        self.notice_label.setVisible(bool(notice))

    def _render_working(self, session: Analyzing | Cleaning) -> None:
        if isinstance(session, Analyzing):
            verb, position, total = "Checking", len(session.done) + 1, len(session.sources)
            self.working_hint.setText("Nothing is saved while checking.")
        else:
            cleaned = sum(1 for result in session.files if result.report is not None)
            verb, position, total = "Cleaning", cleaned + 1, cleaned + len(session.pending)
            self.working_hint.setText("The original file is left as it is.")
        progress = f" ({position} of {total})" if total > 1 else ""
        self.working_label.setText(f"{verb} {session.current.name}{progress}...")

    def _render_results(self, session: Results) -> None:
        files = session.files
        selected = self._selected_index(files)
        self.files_table.blockSignals(True)
        self.files_table.setRowCount(len(files))
        for row_index, result in enumerate(files):
            for column, value in enumerate((result.source.name, file_status(result))):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(str(result.source) if column == 0 else value)
                self.files_table.setItem(row_index, column, item)
        self.files_table.setCurrentCell(selected, 0)
        self.files_table.blockSignals(False)
        self.files_table.resizeRowsToContents()
        visible_rows = sum(self.files_table.rowHeight(row) for row in range(min(len(files), 5)))
        frame = 2 * self.files_table.frameWidth()
        self.files_table.setFixedHeight(self.files_table.horizontalHeader().sizeHint().height() + visible_rows + frame)
        self.files_table.setVisible(len(files) > 1)
        self.summary_label.setText(results_summary(files))

        pending = to_clean(files)
        cleaned_any = any(result.report is not None for result in files)
        self.clean_button.setText(clean_label(len(pending)))
        self.clean_button.setEnabled(bool(pending))
        self.clean_button.setVisible(bool(pending) or not cleaned_any)
        self._render_selection()

    def _on_file_selected(self, *_args) -> None:
        if isinstance(self.session, Results):
            self._render_selection()

    def _render_selection(self) -> None:
        selected = self.selected_file()
        if selected is None:
            return
        report = selected.report
        self.path_label.setText(str(report.output if report is not None else selected.source))
        self.reveal_button.setText(reveal_label())
        self.reveal_button.setVisible(report is not None)
        self.open_button.setVisible(report is not None)
        found = report or selected.analysis
        rows = finding_rows(found) if found is not None else []
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(value)
                self.table.setItem(row_index, column, item)
        self.table.resizeRowsToContents()
        self.table.setVisible(bool(rows))
        self.results_spacer.setVisible(not rows)

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
        window.receive_paths(paths)
    window.show()
    return int(application.exec())


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--clean" in argv:
        return headless(argv)
    return gui(argv)
