import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt

from invisible_mark_cleaner.app import LAST_DIRECTORY, CleanerApplication, MainWindow, create_application, pdf_args
from invisible_mark_cleaner.model import CleanError, OutputNotWritable
from invisible_mark_cleaner.session import BUSY, DROP_PDFS_ONLY, Analyzing, Cleaning, Idle, Results
from tests.helpers import LONG_TEXT, sample_analysis, sample_report

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def pump(app, window, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if not isinstance(window.session, BUSY):
            app.processEvents()
            return
        time.sleep(0.02)
    raise AssertionError(f"still working: {window.session!r}")


def settings_at(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.Format.IniFormat)


def copy_fixtures(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return [Path(shutil.copy(FIXTURES / name, folder / name)) for name in names]


def listing(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def choose(monkeypatch, paths, seen=None):
    def dialog(parent, caption, directory, file_filter):
        if seen is not None:
            seen.append(directory)
        return [str(path) for path in paths], file_filter

    monkeypatch.setattr("invisible_mark_cleaner.app.QFileDialog.getOpenFileNames", dialog)


@pytest.fixture
def qapp():
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "settings" / "settings.ini"


@pytest.fixture
def window(qapp, settings_file):
    widget = MainWindow(settings_at(settings_file))
    widget.resize(880, 640)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    qapp.processEvents()


def test_pdf_args_keeps_pdf_paths_and_skips_flags():
    paths = pdf_args(["--clean", "notes.pdf", "-o", "out.pdf", "other.PDF", "notes.txt"])
    assert paths == [Path("notes.pdf"), Path("other.PDF")]


def test_drop_of_a_non_pdf_stays_on_the_drop_zone(window):
    window.receive_paths([Path("/tmp/a.pdf"), Path("/tmp/notes.txt")])
    assert isinstance(window.session, Idle)
    assert window.notice_label.text() == DROP_PDFS_ONLY
    assert window.notice_label.isVisible()
    assert window.stack.currentWidget() is window.idle_page


def test_choosing_a_pdf_without_marks_writes_nothing(monkeypatch, qapp, window, tmp_path):
    folder = tmp_path / "docs"
    [source] = copy_fixtures(folder, "clean_document.pdf")
    original = source.read_bytes()
    choose(monkeypatch, [source])
    window.choose_button.click()
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert window.stack.currentWidget() is window.results_page
    assert window.summary_label.text() == "No invisible marks found. No clean copy was made."
    assert not window.clean_button.isEnabled()
    assert window.open_button.isHidden()
    assert window.reveal_button.isHidden()
    window.clean_button.click()
    pump(qapp, window)
    assert listing(folder) == ["clean_document.pdf"]
    assert source.read_bytes() == original


def test_marks_are_only_cleaned_after_clicking_clean(monkeypatch, qapp, window, tmp_path):
    folder = tmp_path / "docs"
    [source] = copy_fixtures(folder, "white_text.pdf")
    choose(monkeypatch, [source])
    window.choose_button.click()
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert listing(folder) == ["white_text.pdf"]
    assert window.summary_label.text() == (
        "Found 4 invisible marks on 1 page. Click Clean PDF to save a clean copy."
    )
    assert window.table.rowCount() == 4
    assert window.clean_button.isEnabled()
    assert window.clean_button.text() == "Clean PDF"
    assert window.open_button.isHidden()
    assert window.path_label.text() == str(source)

    window.clean_button.click()
    pump(qapp, window)
    assert listing(folder) == ["white_text-clean.pdf", "white_text.pdf"]
    result = window.session.files[0]
    assert result.report.output == folder / "white_text-clean.pdf"
    assert window.summary_label.text() == "Removed 4 invisible marks on 1 page."
    assert window.path_label.text() == str(folder / "white_text-clean.pdf")
    assert window.clean_button.isHidden()
    assert not window.open_button.isHidden()
    assert not window.reveal_button.isHidden()


def test_analysis_never_calls_the_cleaner(monkeypatch, qapp, window, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    source = folder / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    calls = []

    def spy(path, output=None):
        calls.append(path)
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", lambda path: sample_analysis(path))
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", spy)
    window.submit_pdf(source)
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert calls == []
    assert listing(folder) == ["notes.pdf"]
    window.clean_button.click()
    pump(qapp, window)
    assert calls == [source]


def test_several_pdfs_are_checked_and_only_the_marked_ones_cleaned(monkeypatch, qapp, window, tmp_path):
    folder = tmp_path / "docs"
    sources = copy_fixtures(folder, "white_text.pdf", "clean_document.pdf", "transparent_text.pdf", "encrypted.pdf")
    choose(monkeypatch, sources)
    window.choose_button.click()
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert listing(folder) == sorted(path.name for path in sources)
    assert not window.files_table.isHidden()
    assert window.files_table.rowCount() == 4
    assert [window.files_table.item(row, 0).text() for row in range(4)] == [path.name for path in sources]
    assert window.files_table.item(1, 1).text() == "No invisible marks"
    assert "password" in window.files_table.item(3, 1).text()
    assert window.summary_label.text() == "Checked 4 PDFs. 2 have invisible marks. 1 could not be read."
    assert window.clean_button.text() == "Clean 2 PDFs"

    window.files_table.setCurrentCell(2, 0)
    qapp.processEvents()
    assert window.path_label.text() == str(folder / "transparent_text.pdf")
    assert window.table.rowCount() == len(window.session.files[2].analysis.findings)
    window.files_table.setCurrentCell(1, 0)
    qapp.processEvents()
    assert window.table.isHidden()

    window.clean_button.click()
    pump(qapp, window)
    assert listing(folder) == sorted(
        [path.name for path in sources] + ["transparent_text-clean.pdf", "white_text-clean.pdf"]
    )
    assert window.files_table.item(0, 1).text() == "Cleaned: white_text-clean.pdf"
    assert window.files_table.item(1, 1).text() == "No invisible marks"
    assert window.files_table.item(2, 1).text() == "Cleaned: transparent_text-clean.pdf"
    assert window.summary_label.text() == (
        "Checked 4 PDFs. 2 have invisible marks. 2 cleaned. 1 could not be read."
    )
    assert window.selected_file().report is not None
    assert not window.open_button.isHidden()
    assert window.clean_button.isHidden()


def test_several_pdfs_without_marks_write_nothing(monkeypatch, qapp, window, tmp_path):
    folder = tmp_path / "docs"
    [first] = copy_fixtures(folder, "clean_document.pdf")
    second = Path(shutil.copy(first, folder / "second.pdf"))
    window.receive_paths([first, second, first])
    pump(qapp, window)
    assert len(window.session.files) == 2
    assert window.summary_label.text() == "Checked 2 PDFs. None has invisible marks. No clean copy was made."
    assert not window.clean_button.isEnabled()
    assert listing(folder) == ["clean_document.pdf", "second.pdf"]


def test_choose_dialog_reopens_in_the_last_folder(monkeypatch, qapp, settings_file, tmp_path):
    folder = tmp_path / "inbox"
    [source] = copy_fixtures(folder, "clean_document.pdf")
    seen = []
    choose(monkeypatch, [source], seen)

    first = MainWindow(settings_at(settings_file))
    first.choose_button.click()
    pump(qapp, first)
    first.choose_button.click()
    pump(qapp, first)
    first.close()
    assert seen == [str(Path.home()), str(folder)]

    second = MainWindow(settings_at(settings_file))
    assert second.last_directory() == str(folder)
    second.choose_button.click()
    pump(qapp, second)
    second.close()
    assert seen[-1] == str(folder)
    assert settings_at(settings_file).value(LAST_DIRECTORY) == str(folder)


def test_choose_dialog_falls_back_to_home_when_the_last_folder_is_gone(qapp, settings_file, tmp_path):
    gone = tmp_path / "gone"
    stored = settings_at(settings_file)
    stored.setValue(LAST_DIRECTORY, str(gone))
    stored.sync()
    widget = MainWindow(settings_at(settings_file))
    assert widget.last_directory() == str(Path.home())
    widget.close()


def test_cancelled_choose_dialog_keeps_the_last_folder(monkeypatch, qapp, window, settings_file, tmp_path):
    window._remember_directory(tmp_path)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([], ""),
    )
    window.choose_button.click()
    assert isinstance(window.session, Idle)
    assert settings_at(settings_file).value(LAST_DIRECTORY) == str(tmp_path)


def test_report_table_shows_document_and_the_full_text_on_the_tooltip(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", lambda path: sample_analysis(path))
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", sample_report)
    window.submit_pdf(source)
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert window.files_table.isHidden()
    assert window.summary_label.text() == (
        "Found 4 invisible marks on 2 pages. Click Clean PDF to save a clean copy."
    )
    assert window.table.rowCount() == 4
    assert window.table.item(0, 0).text() == "1"
    assert window.table.item(0, 1).text() == "White text"
    assert window.table.item(0, 2).text() == " ".join(LONG_TEXT.split())
    assert window.table.item(0, 2).toolTip() == window.table.item(0, 2).text()
    assert window.table.item(3, 0).text() == "Document"
    assert window.table.textElideMode() == Qt.TextElideMode.ElideRight
    flags = window.table.item(0, 2).flags()
    assert not (flags & Qt.ItemFlag.ItemIsEditable)
    window.clean_button.click()
    pump(qapp, window)
    assert window.summary_label.text() == "Removed 4 invisible marks on 2 pages."
    assert window.path_label.text() == str(tmp_path / "notes-clean.pdf")
    expected = {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(sys.platform, "Show in folder")
    assert window.reveal_button.text() == expected
    window.again_button.click()
    qapp.processEvents()
    assert isinstance(window.session, Idle)
    assert window.notice_label.isVisible() is False


def test_unreadable_pdf_is_reported_and_offers_other_pdfs(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "locked.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path):
        raise CleanError("This PDF is encrypted.")

    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", stub)
    window.submit_pdf(source)
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert window.summary_label.text() == "This PDF is encrypted."
    assert not window.clean_button.isEnabled()
    assert window.again_button.text() == "Check other PDFs"
    window.again_button.click()
    qapp.processEvents()
    assert isinstance(window.session, Idle)


def marked(monkeypatch):
    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", lambda path: sample_analysis(path))


def test_unwritable_folder_asks_for_another_path(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    chosen = tmp_path / "elsewhere" / "notes-clean.pdf"
    chosen.parent.mkdir()
    calls = []

    def stub(path, output=None):
        calls.append(output)
        if output is None:
            raise OutputNotWritable(source.with_name("notes-clean.pdf"), "That folder is not writable.")
        return sample_report(path, output)

    marked(monkeypatch)
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(chosen), "PDF files (*.pdf)"),
    )
    window.submit_pdf(source)
    pump(qapp, window)
    assert calls == []
    window.clean_button.click()
    pump(qapp, window)
    assert calls == [None, chosen]
    assert isinstance(window.session, Results)
    assert window.session.files[0].report.output == chosen
    assert window.path_label.text() == str(chosen)


def test_cancel_save_as_shows_the_error_and_allows_a_retry(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        raise OutputNotWritable(source.with_name("notes-clean.pdf"), "That folder is not writable.")

    marked(monkeypatch)
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    window.submit_pdf(source)
    pump(qapp, window)
    window.clean_button.click()
    pump(qapp, window)
    assert isinstance(window.session, Results)
    assert window.session.files[0].clean_error == "That folder is not writable."
    assert window.summary_label.text().endswith("That folder is not writable.")
    assert window.clean_button.isEnabled()


def test_save_as_refuses_the_original_path(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    calls = []

    def stub(path, output=None):
        calls.append(output)
        raise OutputNotWritable(source.with_name("notes-clean.pdf"), "That folder is not writable.")

    marked(monkeypatch)
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(source), "PDF files (*.pdf)"),
    )
    window.submit_pdf(source)
    pump(qapp, window)
    window.clean_button.click()
    pump(qapp, window)
    assert calls == [None]
    assert "original" in window.session.files[0].clean_error.lower()


def test_a_drop_while_checking_joins_the_check(monkeypatch, qapp, window, tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-1.4\n")
    second.write_bytes(b"%PDF-1.4\n")
    release = threading.Event()
    started = threading.Event()

    def stub(path):
        started.set()
        assert release.wait(5)
        return sample_analysis(path, findings=())

    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", stub)
    window.submit_pdf(first)
    assert isinstance(window.session, Analyzing)
    assert started.wait(2)
    window.receive_paths([second])
    window.receive_paths([Path("/tmp/notes.txt")])
    assert window.session.sources == (first, second)
    release.set()
    pump(qapp, window)
    assert [result.source for result in window.session.files] == [first, second]


def test_a_drop_while_cleaning_is_ignored(monkeypatch, qapp, window, tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-1.4\n")
    second.write_bytes(b"%PDF-1.4\n")
    release = threading.Event()
    started = threading.Event()

    def stub(path, output=None):
        started.set()
        assert release.wait(5)
        return sample_report(path, output)

    marked(monkeypatch)
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    window.submit_pdf(first)
    pump(qapp, window)
    window.clean_button.click()
    assert isinstance(window.session, Cleaning)
    assert started.wait(2)
    window.receive_paths([second])
    window.choose_button.click()
    assert isinstance(window.session, Cleaning)
    release.set()
    pump(qapp, window)
    assert [result.source for result in window.session.files] == [first]
    assert window.session.files[0].report is not None


def test_files_opened_before_the_window_exists_are_checked_together(monkeypatch, qapp, tmp_path, settings_file):
    from PySide6.QtGui import QFileOpenEvent

    assert isinstance(qapp, CleanerApplication)
    first = tmp_path / "from-dock.pdf"
    second = tmp_path / "also-from-dock.pdf"
    first.write_bytes(b"%PDF-1.4\n")
    second.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", lambda path: sample_analysis(path))
    qapp._window = None
    qapp._queued.clear()
    assert qapp.event(QFileOpenEvent(str(first))) is True
    assert qapp.event(QFileOpenEvent(str(second))) is True
    widget = MainWindow(settings_at(settings_file))
    widget.show()
    qapp.attach(widget)
    pump(qapp, widget)
    assert isinstance(widget.session, Results)
    assert [result.source for result in widget.session.files] == [first, second]
    assert sorted(path.name for path in tmp_path.glob("*.pdf")) == ["also-from-dock.pdf", "from-dock.pdf"]
    widget.close()
    qapp.processEvents()


def test_ui_smoke_script_saves_idle_report_and_done(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_smoke

    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("invisible_mark_cleaner.app.analyze_pdf", lambda path: sample_analysis(path))
    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", sample_report)
    outdir = tmp_path / "shots"
    assert ui_smoke.run(source, outdir, timeout=10) == 0
    shots = [(outdir / name).read_bytes() for name in ("idle.png", "report.png", "done.png")]
    assert all(len(shot) > 1000 for shot in shots)
    assert len(set(shots)) == 3


def test_ui_smoke_script_process_on_the_display(tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    outdir = tmp_path / "shots"
    env = os.environ.copy()
    if sys.platform in ("darwin", "win32"):
        env["QT_QPA_PLATFORM"] = "offscreen"
    else:
        env["QT_QPA_PLATFORM"] = "xcb"
        env["DISPLAY"] = os.environ.get("DISPLAY", ":1")
    driver = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        import invisible_mark_cleaner as pkg
        from invisible_mark_cleaner.model import Analysis, Finding, MarkKind, Report

        text = "hidden fragment " * 12
        findings = (
            Finding(MarkKind.WHITE_TEXT, 1, text, "near-white fill on a light background"),
            Finding(MarkKind.TRANSPARENT_TEXT, 2, "see-through line", "alpha 0"),
            Finding(MarkKind.INVISIBLE_TEXT, 2, "render mode three", "text render mode 3"),
            Finding(MarkKind.METADATA, None, "Author", "marker-like Info field"),
        )

        def analyze(source):
            return Analysis(source=source, page_count=2, findings=findings)

        def clean(source, output=None):
            dest = output or source.with_name(source.stem + "-clean.pdf")
            dest.write_bytes(b"%PDF-1.4\\n")
            return Report(source=source, output=dest, page_count=2, findings=findings)

        pkg.analyze_pdf = analyze
        pkg.clean_pdf = clean
        import runpy
        sys.argv = [sys.argv[1], sys.argv[2], sys.argv[3]]
        raise SystemExit(runpy.run_path(sys.argv[0], run_name="__main__"))
        """
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            driver,
            str(ROOT / "scripts" / "ui_smoke.py"),
            str(source),
            str(outdir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    for name in ("idle.png", "report.png", "done.png"):
        assert (outdir / name).stat().st_size > 1000
