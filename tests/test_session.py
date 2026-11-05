from pathlib import Path

from invisible_mark_cleaner.model import CleanError, OutputNotWritable
from invisible_mark_cleaner.session import (
    DROP_PDFS_ONLY,
    Analyzing,
    Cleaning,
    FileResult,
    clean_failure,
    pdf_paths,
    to_clean,
    with_result,
)
from tests.helpers import sample_analysis, sample_report


def test_drop_accepts_one_or_more_pdfs_in_order_without_repeats():
    pdf, other = Path("/tmp/notes.pdf"), Path("/tmp/Other.PDF")
    assert pdf_paths([pdf]) == (pdf,)
    assert pdf_paths([other, pdf, other]) == (other, pdf)
    assert pdf_paths([pdf, Path("/tmp/notes.txt")]) is None
    assert pdf_paths([]) is None
    assert DROP_PDFS_ONLY == "Drop PDF files only."


def test_only_files_with_marks_and_no_clean_copy_need_cleaning(tmp_path):
    source = tmp_path / "notes.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    marked = FileResult(source, analysis=sample_analysis(source))
    files = (
        marked,
        FileResult(source, analysis=sample_analysis(source, findings=())),
        FileResult(source, error="This PDF is encrypted."),
        FileResult(source, analysis=sample_analysis(source), report=sample_report(source)),
        FileResult(source, analysis=sample_analysis(source), clean_error="That folder is not writable."),
    )
    assert to_clean(files) == (0, 4)
    assert [result.has_marks for result in files] == [True, False, False, True, True]
    updated = with_result(files, 0, report=sample_report(source))
    assert to_clean(updated) == (4,)
    assert updated[1:] == files[1:]
    assert files[0] is marked


def test_busy_states_name_the_file_in_progress():
    first, second = Path("/tmp/a.pdf"), Path("/tmp/b.pdf")
    assert Analyzing((first, second)).current == first
    assert Analyzing((first, second), (FileResult(first, error="x"),)).current == second
    files = (FileResult(first), FileResult(second))
    assert Cleaning(files, (1,)).current == second


def test_unwritable_output_keeps_the_suggested_path():
    suggested = Path("/tmp/notes-clean.pdf")
    failure = clean_failure(OutputNotWritable(suggested, "That folder is not writable."))
    assert failure.message == "That folder is not writable."
    assert failure.save_as == suggested


def test_other_clean_errors_do_not_ask_for_a_new_path():
    failure = clean_failure(CleanError("This PDF is encrypted."))
    assert failure.message == "This PDF is encrypted."
    assert failure.save_as is None


def test_blank_error_gets_a_readable_message():
    failure = clean_failure(CleanError("  "))
    assert failure.message == "This PDF could not be cleaned."
    assert failure.save_as is None
