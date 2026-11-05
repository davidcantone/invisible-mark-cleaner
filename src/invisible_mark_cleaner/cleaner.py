from __future__ import annotations

import itertools
import os
import tempfile
from pathlib import Path

import pikepdf

from .content import clean_pages
from .layers import Layers
from .metadata import clean_metadata
from .model import CleanError, OutputNotWritable, Report

PASSWORD_PROTECTED = "This PDF is password-protected. Remove the password and try again."
NOT_READABLE = "This file could not be read as a PDF. It may be damaged, or it may not be a PDF."


def suggested_output_path(source: Path) -> Path:
    """`name-clean.pdf` next to the source, or `name-clean-2.pdf`, `-3`... if taken."""
    source = Path(source)
    names = (f"{source.stem}-clean{'' if n == 1 else f'-{n}'}.pdf" for n in itertools.count(1))
    return next(path for path in map(source.with_name, names) if not path.exists())


def clean_pdf(source: Path, output: Path | None = None) -> Report:
    """Detect invisible marks in `source`, write a copy without them to `output`
    (default: `suggested_output_path(source)`), and return the report.

    Never writes to `source`. Raises CleanError for unreadable, encrypted or non-PDF input.
    """
    source = Path(source).absolute()
    output = Path(output).absolute() if output is not None else suggested_output_path(source)
    if output.resolve() == source.resolve():
        raise CleanError("The clean copy can't replace the original file. Choose a different name.")
    if not source.is_file():
        raise CleanError(f"Could not find the file {source.name}.")
    try:
        with pikepdf.open(source) as pdf:
            layers = Layers(pdf)
            findings = clean_metadata(pdf) + clean_pages(pdf, layers)
            layers.prune(pdf)
            write(pdf, output)
            return Report(source, output, len(pdf.pages), tuple(findings))
    except pikepdf.PasswordError:
        raise CleanError(PASSWORD_PROTECTED) from None
    except pikepdf.PdfError:
        raise CleanError(NOT_READABLE) from None
    except OSError as error:
        raise CleanError(f"Could not open {source.name}: {error.strerror or error}.") from None


def write(pdf: pikepdf.Pdf, output: Path) -> None:
    """Write through a temporary file in the output folder so a failure never leaves a partial PDF behind."""
    try:
        fd, temp = tempfile.mkstemp(prefix=f".{output.stem}-", suffix=".part", dir=output.parent)
    except OSError as error:
        raise not_writable(output, error) from None
    try:
        with os.fdopen(fd, "wb") as stream:
            pdf.save(stream, fix_metadata_version=False, encryption=pdf.is_encrypted)
        os.replace(temp, output)
    except OSError as error:
        Path(temp).unlink(missing_ok=True)
        raise not_writable(output, error) from None
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def not_writable(output: Path, error: OSError) -> OutputNotWritable:
    reason = error.strerror or str(error)
    return OutputNotWritable(output, f"Could not save the clean copy to {output.parent}: {reason}.")
