from pathlib import Path

from invisible_mark_cleaner.model import Finding, MarkKind, Report
from invisible_mark_cleaner.present import (
    analysis_summary,
    clean_label,
    file_status,
    finding_rows,
    format_report,
    report_payload,
    results_summary,
    reveal_command,
    reveal_label,
    summary,
)
from invisible_mark_cleaner.session import FileResult
from tests.helpers import sample_analysis, sample_report


def _report(tmp_path: Path, findings) -> Report:
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    return sample_report(source, findings=findings)


def test_summary_for_several_marks_on_several_pages(tmp_path):
    report = _report(tmp_path, None)
    assert summary(report) == "Removed 4 invisible marks on 2 pages."


def test_summary_when_nothing_was_found(tmp_path):
    report = _report(tmp_path, ())
    assert summary(report) == "No invisible marks found. A clean copy was saved anyway."


def test_summary_uses_singular_for_one_mark_on_one_page(tmp_path):
    findings = (Finding(MarkKind.WHITE_TEXT, 3, "only", "fill"),)
    report = _report(tmp_path, findings)
    assert summary(report) == "Removed 1 invisible mark on 1 page."


def test_summary_omits_pages_when_the_mark_is_not_on_a_page(tmp_path):
    findings = (
        Finding(MarkKind.METADATA, None, "Author", "Info"),
        Finding(MarkKind.METADATA, None, "Keywords", "XMP"),
    )
    report = _report(tmp_path, findings)
    assert summary(report) == "Removed 2 invisible marks."


def test_rows_keep_report_order_and_name_a_missing_page_document(tmp_path):
    report = _report(tmp_path, None)
    rows = finding_rows(report)
    assert rows[0][0] == "1"
    assert rows[0][1] == "White text"
    assert rows[-1][0] == "Document"
    assert rows[-1][1] == "Metadata field"
    assert [row[1] for row in rows] == [
        "White text",
        "Transparent text",
        "Invisible text mode",
        "Metadata field",
    ]


def test_cli_text_includes_the_clean_copy_path(tmp_path):
    report = _report(tmp_path, ())
    text = format_report(report)
    assert str(report.output) in text
    assert "No invisible marks found. A clean copy was saved anyway." in text


def test_json_payload_uses_null_for_a_document_level_mark(tmp_path):
    report = _report(tmp_path, None)
    payload = report_payload(report)
    assert payload["pages_affected"] == [1, 2]
    assert payload["findings"][-1]["page"] is None
    assert payload["findings"][-1]["kind"] == "Metadata field"
    assert payload["source"] == str(report.source)
    assert payload["output"] == str(report.output)


def test_reveal_commands_match_the_desktop():
    path = Path("/tmp/notes-clean.pdf")
    assert reveal_label("Darwin") == "Show in Finder"
    assert reveal_command(path, "Darwin") == ["open", "-R", str(path)]
    assert reveal_label("Windows") == "Show in Explorer"
    assert reveal_command(path, "Windows") == ["explorer", "/select," + str(path)]
    assert reveal_label("Linux") == "Show in folder"
    assert reveal_command(path, "Linux") == ["xdg-open", str(path.parent)]


def test_analysis_summary_says_what_was_found_and_that_nothing_was_saved(tmp_path):
    source = tmp_path / "notes.pdf"
    assert analysis_summary(sample_analysis(source)) == "Found 4 invisible marks on 2 pages."
    assert analysis_summary(sample_analysis(source, findings=())) == (
        "No invisible marks found. No clean copy was made."
    )
    one = (Finding(MarkKind.METADATA, None, "Author", "Info"),)
    assert analysis_summary(sample_analysis(source, findings=one)) == "Found 1 invisible mark."


def test_clean_button_names_how_many_pdfs_it_cleans():
    assert clean_label(0) == "Clean PDF"
    assert clean_label(1) == "Clean PDF"
    assert clean_label(3) == "Clean 3 PDFs"


def test_single_file_summary_follows_the_file_through_cleaning(tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    checked = FileResult(source, analysis=sample_analysis(source))
    assert results_summary((checked,)) == (
        "Found 4 invisible marks on 2 pages. Click Clean PDF to save a clean copy."
    )
    assert file_status(checked) == "4 invisible marks on 2 pages"
    cleaned = FileResult(source, analysis=checked.analysis, report=sample_report(source))
    assert results_summary((cleaned,)) == "Removed 4 invisible marks on 2 pages."
    assert file_status(cleaned) == "Cleaned: notes-clean.pdf"
    failed = FileResult(source, analysis=checked.analysis, clean_error="That folder is not writable.")
    assert results_summary((failed,)) == "Found 4 invisible marks on 2 pages. That folder is not writable."
    assert file_status(failed) == "That folder is not writable."
    unreadable = FileResult(source, error="This PDF is encrypted.")
    assert results_summary((unreadable,)) == "This PDF is encrypted."
    assert file_status(unreadable) == "This PDF is encrypted."
    nothing = FileResult(source, analysis=sample_analysis(source, findings=()))
    assert file_status(nothing) == "No invisible marks"


def test_several_files_summary_counts_marked_cleaned_and_unreadable(tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    marked = FileResult(source, analysis=sample_analysis(source))
    plain = FileResult(source, analysis=sample_analysis(source, findings=()))
    unreadable = FileResult(source, error="This PDF is encrypted.")
    cleaned = FileResult(source, analysis=marked.analysis, report=sample_report(source))
    assert results_summary((plain, plain)) == "Checked 2 PDFs. None has invisible marks. No clean copy was made."
    assert results_summary((marked, plain)) == "Checked 2 PDFs. 1 has invisible marks."
    assert results_summary((marked, cleaned, unreadable)) == (
        "Checked 3 PDFs. 2 have invisible marks. 1 cleaned. 1 could not be read."
    )
