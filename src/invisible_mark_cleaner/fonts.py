from __future__ import annotations

import re
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Array, Dictionary, Stream

Codespace = tuple[tuple[bytes, bytes], ...]

ONE_BYTE: Codespace = ((b"\x00", b"\xff"),)
TWO_BYTES: Codespace = ((b"\x00\x00", b"\xff\xff"),)
MAX_CID = 0xFFFF
UNREADABLE = "\ufffd"
CODECS = {"/WinAnsiEncoding": "cp1252", "/MacRomanEncoding": "mac_roman"}

SECTION = re.compile(rb"begin(codespacerange|bfchar|bfrange)(.*?)end\1", re.S)
TOKEN = re.compile(rb"<([0-9A-Fa-f\s]*)>|\[|\]|/[^\s<>\[\]()/]*")


@dataclass(frozen=True)
class CMap:
    codespace: Codespace = ()
    chars: dict[bytes, str] = field(default_factory=dict)
    ranges: tuple[tuple[bytes, bytes, bytes | list[str]], ...] = ()

    def lookup(self, code: bytes) -> str | None:
        if code in self.chars:
            return self.chars[code]
        for low, high, target in self.ranges:
            if len(low) == len(code) and low <= code <= high:
                offset = int.from_bytes(code, "big") - int.from_bytes(low, "big")
                if isinstance(target, list):
                    return target[offset] if offset < len(target) else None
                value = (int.from_bytes(target, "big") + offset) % (1 << (8 * len(target)))
                return utf16(value.to_bytes(len(target), "big"))
        return None


@dataclass(frozen=True)
class Font:
    codespace: Codespace = ONE_BYTE
    to_unicode: CMap | None = None
    codec: str | None = "latin-1"
    widths: dict[int, float] = field(default_factory=dict)
    default_width: float | None = None
    type3: bool = False

    def split(self, data: bytes) -> list[bytes]:
        codes, i = [], 0
        shortest = len(self.codespace[0][0])
        while i < len(data):
            n = next(
                (len(low) for low, high in self.codespace
                 if i + len(low) <= len(data) and low <= data[i:i + len(low)] <= high),
                shortest,
            )
            codes.append(data[i:i + n])
            i += n
        return codes

    def text(self, code: bytes) -> str:
        mapped = self.to_unicode.lookup(code) if self.to_unicode else None
        if mapped is not None:
            return mapped
        if self.codec is None:
            return UNREADABLE
        try:
            return code.decode(self.codec)
        except UnicodeDecodeError:
            return code.decode("latin-1")

    def advance(self, code: bytes) -> float | None:
        """Glyph advance in text space units for a font size of 1, or None when unknown."""
        return self.widths.get(int.from_bytes(code, "big"), self.default_width)


UNKNOWN_FONT = Font()


def load_font(font: Dictionary) -> Font:
    cmap = read_cmap(font.get("/ToUnicode"))
    if font.get("/Subtype") == pikepdf.Name.Type0:
        return composite_font(font, cmap)
    return simple_font(font, cmap)


def simple_font(font: Dictionary, cmap: CMap | None) -> Font:
    type3 = font.get("/Subtype") == pikepdf.Name.Type3
    unit = float(font.FontMatrix[0]) if type3 and "/FontMatrix" in font else 0.001
    first = int(font.get("/FirstChar", 0))
    widths = {first + i: float(w) * unit for i, w in enumerate(font.get("/Widths", []))}
    descriptor = font.get("/FontDescriptor")
    missing = descriptor.get("/MissingWidth") if isinstance(descriptor, Dictionary) else None
    encoding = font.get("/Encoding")
    if isinstance(encoding, Dictionary):
        encoding = encoding.get("/BaseEncoding")
    return Font(
        to_unicode=cmap,
        codec=CODECS.get(str(encoding), "latin-1"),
        widths=widths,
        default_width=float(missing) * unit if widths and missing is not None else None,
        type3=type3,
    )


def composite_font(font: Dictionary, cmap: CMap | None) -> Font:
    encoding = font.get("/Encoding")
    if isinstance(encoding, Stream):
        codespace = (read_cmap(encoding) or CMap()).codespace or TWO_BYTES
    elif str(encoding) in ("/Identity-H", "/Identity-V"):
        codespace = TWO_BYTES
    else:
        codespace = cmap.codespace if cmap and cmap.codespace else TWO_BYTES
    descendants = font.get("/DescendantFonts")
    descendant = descendants[0] if isinstance(descendants, Array) and len(descendants) else None
    if str(encoding) != "/Identity-H" or not isinstance(descendant, Dictionary):
        # Without Identity-H the code-to-CID mapping (or the writing direction) is unknown.
        return Font(codespace, cmap, codec=None)
    return Font(
        codespace,
        cmap,
        codec=None,
        widths=cid_widths(descendant.get("/W", [])),
        default_width=float(descendant.get("/DW", 1000)) / 1000,
    )


def cid_widths(w: Array) -> dict[int, float]:
    items, widths, i = list(w), {}, 0
    while i + 1 < len(items):
        first, second = int(items[i]), items[i + 1]
        if isinstance(second, Array):
            widths.update({first + k: float(v) / 1000 for k, v in enumerate(second)})
            i += 2
        elif i + 2 < len(items):
            value = float(items[i + 2]) / 1000
            widths.update({cid: value for cid in range(max(first, 0), min(int(second), MAX_CID) + 1)})
            i += 3
        else:
            break
    return widths


def read_cmap(stream: object) -> CMap | None:
    if not isinstance(stream, Stream):
        return None
    try:
        return parse_cmap(stream.read_bytes())
    except pikepdf.PdfError:
        return None


def parse_cmap(data: bytes) -> CMap:
    codespace, chars, ranges = [], {}, []
    for kind, body in SECTION.findall(data):
        items = tokens(body)
        if kind == b"codespacerange":
            codespace += [(lo, hi) for lo, hi in zip(items[::2], items[1::2]) if is_code(lo, hi)]
        elif kind == b"bfchar":
            chars.update({src: utf16(dst) for src, dst in zip(items[::2], items[1::2]) if is_code(src, dst)})
        else:
            for lo, hi, dst in zip(items[::3], items[1::3], items[2::3]):
                if is_code(lo, hi) and isinstance(dst, bytes):
                    ranges.append((lo, hi, dst))
                elif is_code(lo, hi) and isinstance(dst, list):
                    ranges.append((lo, hi, [utf16(d) for d in dst if isinstance(d, bytes)]))
    return CMap(tuple(sorted(codespace, key=lambda r: len(r[0]))), chars, tuple(ranges))


def tokens(body: bytes) -> list:
    """Hex strings as bytes, arrays as lists, anything else (names) as None placeholders."""
    items, array = [], None
    for match in TOKEN.finditer(body):
        token = match.group()
        if token == b"[":
            array = []
        elif token == b"]":
            items.append(array or [])
            array = None
        else:
            value = unhex(match.group(1)) if token.startswith(b"<") else None
            (items if array is None else array).append(value)
    return items


def unhex(digits: bytes) -> bytes:
    digits = re.sub(rb"\s", b"", digits)
    return bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode())


def utf16(data: bytes) -> str:
    return data.decode("utf-16-be", errors="replace")


def is_code(*values: object) -> bool:
    return all(isinstance(v, bytes) and v for v in values)
