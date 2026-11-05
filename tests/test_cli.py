from pathlib import Path

import pytest

from invisible_mark_cleaner.cli import main
from invisible_mark_cleaner.model import CleanError
from tests.helpers import sample_report


def test_cli_prints_the_report_and_leaves_the_original(monkeypatch, tmp_path, capsys):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4 original\n")
    before = source.read_bytes()

    def stub(path, output=None):
        assert path == source
        assert output is None
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.cli.clean_pdf", stub)
    assert main([str(source)]) == 0
    out = capsys.readouterr().out
    assert "Removed 4 invisible marks on 2 pages." in out
    assert "Document" in out
    assert "White text" in out
    assert "Author" in out
    assert str(tmp_path / "notes-clean.pdf") in out
    assert source.read_bytes() == before
    assert not (tmp_path / "notes-clean.pdf.report.json").exists()


def test_cli_passes_the_output_path(monkeypatch, tmp_path, capsys):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    chosen = tmp_path / "elsewhere" / "clean.pdf"
    seen = {}

    def stub(path, output=None):
        seen["output"] = output
        return sample_report(path, output)

    monkeypatch.setattr("invisible_mark_cleaner.cli.clean_pdf", stub)
    assert main([str(source), "-o", str(chosen)]) == 0
    assert seen["output"] == chosen
    assert str(chosen) in capsys.readouterr().out
    assert chosen.is_file()


def test_cli_exits_2_on_clean_error(monkeypatch, tmp_path, capsys):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")

    def stub(path, output=None):
        raise CleanError("This PDF is encrypted.")

    monkeypatch.setattr("invisible_mark_cleaner.cli.clean_pdf", stub)
    assert main([str(source)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "This PDF is encrypted." in captured.err
    assert list(tmp_path.glob("*.pdf")) == [source]


def test_cli_rejects_a_missing_file_argument():
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
