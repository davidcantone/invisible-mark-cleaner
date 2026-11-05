import json
import subprocess
import sys
from pathlib import Path

from invisible_mark_cleaner.app import main
from invisible_mark_cleaner.model import CleanError
from tests.helpers import sample_report

ROOT = Path(__file__).resolve().parents[1]


def test_headless_writes_json_beside_the_clean_copy(monkeypatch, tmp_path, capsys):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    chosen = tmp_path / "notes-clean.pdf"

    def stub(path, output=None):
        assert path == source
        assert output == chosen
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    assert main(["--clean", str(source), "--output", str(chosen)]) == 0
    report_path = Path(str(chosen) + ".report.json")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["output"] == str(chosen)
    assert payload["page_count"] == 2
    assert payload["pages_affected"] == [1, 2]
    assert payload["findings"][0]["kind"] == "White text"
    assert payload["findings"][-1]["page"] is None
    assert "Removed 4 invisible marks on 2 pages." in capsys.readouterr().out


def test_headless_uses_the_path_the_cleaner_chose(monkeypatch, tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        assert output is None
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    assert main(["--clean", str(source)]) == 0
    assert (tmp_path / "notes-clean.pdf").is_file()
    assert (tmp_path / "notes-clean.pdf.report.json").is_file()


def test_headless_exits_2_without_a_report(monkeypatch, tmp_path, capsys):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        raise CleanError("This PDF is encrypted.")

    monkeypatch.setattr("invisible_mark_cleaner.app.clean_pdf", stub)
    assert main(["--clean", str(source)]) == 2
    assert "This PDF is encrypted." in capsys.readouterr().err
    assert list(tmp_path.glob("*.report.json")) == []


def test_headless_process_does_not_open_a_window(tmp_path):
    source = tmp_path / "clean_document.pdf"
    source.write_bytes((ROOT / "tests" / "fixtures" / "clean_document.pdf").read_bytes())
    output = tmp_path / "clean_document-clean.pdf"
    script = """
import sys
from PySide6.QtWidgets import QApplication
from invisible_mark_cleaner.app import main
code = main(["--clean", sys.argv[1], "--output", sys.argv[2]])
if QApplication.instance() is not None:
    raise SystemExit(3)
raise SystemExit(code)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(source), str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.is_file()
    assert Path(str(output) + ".report.json").is_file()
    assert source.read_bytes() == (ROOT / "tests" / "fixtures" / "clean_document.pdf").read_bytes()
