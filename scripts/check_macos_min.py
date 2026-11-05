#!/usr/bin/env python3
"""Report Mach-O minimum macOS versions and fail above --limit (default 12.0) or without x86_64."""

from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Apple packs a version as (major << 16) | (minor << 8) | patch.
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
PLATFORM_MACOS = 1
ABI64 = 0x01000000
ABI64_32 = 0x02000000

THIN_MAGICS = {
    b"\xcf\xfa\xed\xfe": ("<", 64),
    b"\xfe\xed\xfa\xcf": (">", 64),
    b"\xce\xfa\xed\xfe": ("<", 32),
    b"\xfe\xed\xfa\xce": (">", 32),
}
FAT_MAGICS = {
    b"\xca\xfe\xba\xbe": (">", False),
    b"\xbe\xba\xfe\xca": ("<", False),
    b"\xca\xfe\xba\xbf": (">", True),
    b"\xbf\xba\xfe\xca": ("<", True),
}

ARCH_NAMES = {
    7: "i386",
    7 | ABI64: "x86_64",
    12: "arm",
    12 | ABI64: "arm64",
    12 | ABI64_32: "arm64_32",
    18: "ppc",
    18 | ABI64: "ppc64",
}


@dataclass(frozen=True)
class Slice:
    label: str
    arch: str
    minos: tuple[int, int, int] | None


@dataclass(frozen=True)
class ScanResult:
    slices: tuple[Slice, ...]
    failures: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failures


def arch_name(cputype: int) -> str:
    return ARCH_NAMES.get(cputype, f"cpu_{cputype:#x}")


def unpack_version(raw: int) -> tuple[int, int, int]:
    return ((raw >> 16) & 0xFFFF, (raw >> 8) & 0xFF, raw & 0xFF)


def format_version(version: tuple[int, int, int] | None) -> str:
    if version is None:
        return "unknown"
    major, minor, patch = version
    if patch:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}"


def parse_limit(text: str) -> tuple[int, int, int]:
    parts = text.split(".")
    if len(parts) > 3 or not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"bad macOS version {text}")
    numbers = [int(part) for part in parts]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def _read_minos(blob: bytes, endian: str, ncmds: int) -> tuple[int, int, int] | None:
    build = None
    legacy = None
    pos = 0
    for _ in range(ncmds):
        if pos + 8 > len(blob):
            break
        cmd, cmdsize = struct.unpack_from(endian + "II", blob, pos)
        if cmdsize < 8 or pos + cmdsize > len(blob):
            break
        if cmd == LC_BUILD_VERSION and cmdsize >= 24:
            platform, raw, _sdk, _ntools = struct.unpack_from(endian + "IIII", blob, pos + 8)
            if platform == PLATFORM_MACOS:
                build = unpack_version(raw)
        elif cmd == LC_VERSION_MIN_MACOSX and cmdsize >= 16:
            raw, _sdk = struct.unpack_from(endian + "II", blob, pos + 8)
            legacy = unpack_version(raw)
        pos += cmdsize
    return build if build is not None else legacy


def parse_thin(fh, label: str, offset: int) -> Slice | None:
    fh.seek(offset)
    magic = fh.read(4)
    spec = THIN_MAGICS.get(magic)
    if spec is None:
        return None
    endian, bits = spec
    rest_len = 28 if bits == 64 else 24
    rest = fh.read(rest_len)
    if len(rest) < rest_len:
        return None
    if bits == 64:
        cputype, _subtype, _filetype, ncmds, sizeofcmds, _flags, _reserved = struct.unpack(
            endian + "IIIIIII", rest
        )
    else:
        cputype, _subtype, _filetype, ncmds, sizeofcmds, _flags = struct.unpack(
            endian + "IIIIII", rest
        )
    minos = None
    if 0 < ncmds <= 4096 and 0 < sizeofcmds <= 2_000_000:
        blob = fh.read(sizeofcmds)
        if len(blob) == sizeofcmds:
            minos = _read_minos(blob, endian, ncmds)
    return Slice(label, arch_name(cputype), minos)


def parse_fat(fh, label: str, magic: bytes) -> list[Slice]:
    endian, is64 = FAT_MAGICS[magic]
    count_raw = fh.read(4)
    if len(count_raw) < 4:
        return []
    nfat = struct.unpack(endian + "I", count_raw)[0]
    # Java class files share the CAFEBABE magic. A real fat header has a handful of slices.
    if nfat < 1 or nfat > 16:
        return []
    arch_size = 32 if is64 else 20
    offsets: list[int] = []
    for _ in range(nfat):
        raw = fh.read(arch_size)
        if len(raw) < arch_size:
            return []
        if is64:
            _cputype, _subtype, offset, _size, _align, _reserved = struct.unpack(
                endian + "IIQQII", raw
            )
        else:
            _cputype, _subtype, offset, _size, _align = struct.unpack(endian + "IIIII", raw)
        offsets.append(offset)
    slices: list[Slice] = []
    for offset in offsets:
        try:
            found = parse_thin(fh, label, offset)
        except OSError:
            return []
        if found is None:
            return []
        slices.append(found)
    return slices


def parse_fileobj(fh, label: str) -> list[Slice]:
    try:
        fh.seek(0)
        magic = fh.read(4)
    except OSError:
        return []
    try:
        if magic in FAT_MAGICS:
            return parse_fat(fh, label, magic)
        if magic in THIN_MAGICS:
            found = parse_thin(fh, label, 0)
            return [found] if found is not None else []
    except (OSError, struct.error):
        return []
    return []


def scan_zip(path: Path) -> list[Slice]:
    found: list[Slice] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size < 8:
                continue
            label = f"{path}!{info.filename}"
            try:
                with archive.open(info, "r") as raw:
                    found.extend(parse_fileobj(raw, label))
            except (OSError, zipfile.BadZipFile, RuntimeError):
                continue
    return found


def scan_path(path: Path) -> list[Slice]:
    if path.is_file() and path.suffix.lower() in {".whl", ".zip"}:
        return scan_zip(path)
    files = [path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()]
    found: list[Slice] = []
    for file in files:
        try:
            if file.stat().st_size < 8:
                continue
            with file.open("rb") as fh:
                found.extend(parse_fileobj(fh, str(file)))
        except OSError:
            continue
    return found


def evaluate(slices: list[Slice], limit: tuple[int, int, int] = (12, 0, 0)) -> ScanResult:
    failures: list[str] = []
    if not slices:
        failures.append("no Mach-O binaries found")
    grouped: dict[str, list[Slice]] = {}
    for sl in slices:
        grouped.setdefault(sl.label, []).append(sl)
    for label, group in grouped.items():
        archs = sorted({sl.arch for sl in group})
        if "x86_64" not in archs:
            failures.append(f"{label} lacks x86_64 ({', '.join(archs)})")
        for sl in group:
            if sl.minos is not None and sl.minos > limit:
                failures.append(
                    f"{label} {sl.arch} needs macOS {format_version(sl.minos)}"
                )
    return ScanResult(tuple(slices), tuple(failures))


def format_result(result: ScanResult) -> str:
    known = [sl.minos for sl in result.slices if sl.minos is not None]
    highest = max(known) if known else None
    archs = sorted({sl.arch for sl in result.slices})
    files = len({sl.label for sl in result.slices})
    lines = [
        f"mach-o files: {files}",
        f"slices: {len(result.slices)}",
        f"architectures: {', '.join(archs) if archs else 'none'}",
        f"highest minimum macOS: {format_version(highest)}",
        f"result: {'ok' if result.ok else 'failed'}",
    ]
    lines.extend(result.failures)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_macos_min.py")
    parser.add_argument("path", type=Path, help="app bundle, wheel, zip, or directory")
    parser.add_argument("--limit", default="12.0", help="fail when a slice needs a newer macOS")
    args = parser.parse_args(argv)
    try:
        limit = parse_limit(args.limit)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    path = args.path
    if not path.exists():
        print(f"path not found: {path}")
        return 1
    result = evaluate(scan_path(path), limit)
    sys.stdout.write(format_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
