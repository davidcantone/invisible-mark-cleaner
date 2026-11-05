from pathlib import Path

from invisible_mark_cleaner.model import CleanError, OutputNotWritable
from invisible_mark_cleaner.session import DROP_ONE_PDF, clean_failure, single_pdf


def test_drop_accepts_exactly_one_pdf():
    pdf = Path("/tmp/notes.pdf")
    assert single_pdf([pdf]) == pdf
    assert single_pdf([pdf, Path("/tmp/other.pdf")]) is None
    assert single_pdf([Path("/tmp/notes.txt")]) is None
    assert single_pdf([]) is None
    assert DROP_ONE_PDF == "Drop one PDF at a time."


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
