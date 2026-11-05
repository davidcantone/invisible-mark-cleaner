import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from invisible_mark_cleaner.app import CleanerApplication, MainWindow, create_application, pdf_args
from invisible_mark_cleaner.model import CleanError, OutputNotWritable
from invisible_mark_cleaner.session import DROP_ONE_PDF, Done, Failed, Idle, Working
from tests.helpers import LONG_TEXT, sample_report

ROOT = Path(__file__).resolve().parents[1]


def pump(app, window, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if not isinstance(window.session, Working):
            return
        time.sleep(0.02)
    raise AssertionError(f"still working: {window.session!r}")


@pytest.fixture
def qapp():
    app = create_application()
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def window(qapp):
    widget = MainWindow()
    widget.resize(880, 640)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    qapp.processEvents()


def test_pdf_args_keeps_pdf_paths_and_skips_flags():
    paths = pdf_args(["--clean", "notes.pdf", "-o", "out.pdf", "other.PDF", "notes.txt"])
    assert paths == [Path("notes.pdf"), Path("other.PDF")]


def test_drop_of_two_files_stays_on_the_drop_zone(window):
    window.receive_paths([Path("/tmp/a.pdf"), Path("/tmp/b.pdf")])
    assert isinstance(window.session, Idle)
    assert window.notice_label.text() == DROP_ONE_PDF
    assert window.notice_label.isVisible()
    assert window.stack.currentWidget() is window.idle_page


def test_drop_of_a_non_pdf_uses_the_same_message(window):
    window.receive_paths([Path("/tmp/notes.txt")])
    assert window.notice_label.text() == "Drop one PDF at a time."


def test_done_table_shows_document_and_the_full_text_on_the_tooltip(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    window.submit_pdf(source)
    pump(qapp, window)
    assert isinstance(window.session, Done)
    assert window.summary_label.text() == "Removed 4 invisible marks on 2 pages."
    assert window.table.rowCount() == 4
    assert window.table.item(0, 0).text() == "1"
    assert window.table.item(0, 1).text() == "White text"
    assert window.table.item(0, 2).text() == " ".join(LONG_TEXT.split())
    assert window.table.item(0, 2).toolTip() == window.table.item(0, 2).text()
    assert window.table.item(3, 0).text() == "Document"
    assert window.table.textElideMode() == Qt.TextElideMode.ElideRight
    assert window.path_label.text() == str(tmp_path / "notes-clean.pdf")
    expected = {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(sys.platform, "Show in folder")
    assert window.reveal_button.text() == expected
    flags = window.table.item(0, 2).flags()
    assert not (flags & Qt.ItemFlag.ItemIsEditable)
    window.again_button.click()
    qapp.processEvents()
    assert isinstance(window.session, Idle)
    assert window.notice_label.isVisible() is False


def test_clean_error_offers_another_pdf(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "locked.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        raise CleanError("This PDF is encrypted.")

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    window.submit_pdf(source)
    pump(qapp, window)
    assert isinstance(window.session, Failed)
    assert window.failed_label.text() == "This PDF is encrypted."
    assert window.retry_button.text() == "Try another PDF"
    window.retry_button.click()
    qapp.processEvents()
    assert isinstance(window.session, Idle)


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
        return sample_report(path, output, findings=())

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(chosen), "PDF files (*.pdf)"),
    )
    window.submit_pdf(source)
    pump(qapp, window)
    assert calls == [None, chosen]
    assert isinstance(window.session, Done)
    assert window.session.report.output == chosen
    assert window.summary_label.text() == "No invisible marks found. A clean copy was saved anyway."


def test_cancel_save_as_shows_the_error(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        raise OutputNotWritable(source.with_name("notes-clean.pdf"), "That folder is not writable.")

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    window.submit_pdf(source)
    pump(qapp, window)
    assert isinstance(window.session, Failed)
    assert window.failed_label.text() == "That folder is not writable."


def test_save_as_refuses_the_original_path(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    calls = []

    def stub(path, output=None):
        calls.append(output)
        raise OutputNotWritable(source.with_name("notes-clean.pdf"), "That folder is not writable.")

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(source), "PDF files (*.pdf)"),
    )
    window.submit_pdf(source)
    pump(qapp, window)
    assert calls == [None]
    assert isinstance(window.session, Failed)
    assert "original" in window.failed_label.text().lower()


def test_a_second_drop_while_working_is_ignored(monkeypatch, qapp, window, tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-1.4\n")
    second.write_bytes(b"%PDF-1.4\n")
    release = threading.Event()
    started = threading.Event()

    def stub(path, output=None):
        started.set()
        assert release.wait(5)
        return sample_report(path, output, findings=())

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    window.submit_pdf(first)
    assert isinstance(window.session, Working)
    assert started.wait(2)
    window.receive_paths([second])
    assert window.session.source == first
    release.set()
    pump(qapp, window)
    assert isinstance(window.session, Done)
    assert window.session.report.source == first


def test_choose_button_opens_the_selected_pdf(monkeypatch, qapp, window, tmp_path):
    source = tmp_path / "picked.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        return sample_report(path, output, findings=())

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    monkeypatch.setattr(
        "invisible_mark_cleaner.app.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(source), "PDF files (*.pdf)"),
    )
    window.choose_button.click()
    pump(qapp, window)
    assert isinstance(window.session, Done)
    assert window.session.report.source == source


def test_file_open_before_the_window_exists_is_cleaned(monkeypatch, qapp, tmp_path):
    from PySide6.QtGui import QFileOpenEvent

    assert isinstance(qapp, CleanerApplication)
    source = tmp_path / "from-dock.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        return sample_report(path, output, findings=())

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    qapp._window = None
    qapp._queued.clear()
    assert qapp.event(QFileOpenEvent(str(source))) is True
    widget = MainWindow()
    widget.show()
    qapp.attach(widget)
    pump(qapp, widget)
    assert isinstance(widget.session, Done)
    assert widget.session.report.source == source
    widget.close()
    qapp.processEvents()


def test_ui_smoke_script_saves_idle_and_done(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import ui_smoke

    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    outdir = tmp_path / "shots"
    assert ui_smoke.run(source, outdir, timeout=10) == 0
    idle = (outdir / "idle.png").read_bytes()
    done = (outdir / "done.png").read_bytes()
    assert len(idle) > 1000
    assert len(done) > 1000
    assert idle != done


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
        from invisible_mark_cleaner.model import Finding, MarkKind, Report

        def stub(source, output=None):
            dest = output or source.with_name(source.stem + "-clean.pdf")
            dest.write_bytes(b"%PDF-1.4\\n")
            text = "hidden fragment " * 12
            findings = (
                Finding(MarkKind.WHITE_TEXT, 1, text, "near-white fill on a light background"),
                Finding(MarkKind.TRANSPARENT_TEXT, 2, "see-through line", "alpha 0"),
                Finding(MarkKind.INVISIBLE_TEXT, 2, "render mode three", "text render mode 3"),
                Finding(MarkKind.METADATA, None, "Author", "marker-like Info field"),
            )
            return Report(source=source, output=dest, page_count=2, findings=findings)

        pkg.clean_pdf = stub
        pkg.cleaner.clean_pdf = stub
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
    assert (outdir / "idle.png").stat().st_size > 1000
    assert (outdir / "done.png").stat().st_size > 1000
