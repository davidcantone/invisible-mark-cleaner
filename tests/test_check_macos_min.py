import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_macos_min

CPU_X86_64 = 0x01000007
CPU_ARM64 = 0x0100000C
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24


def pack_version(major: int, minor: int = 0, patch: int = 0) -> int:
    return (major << 16) | (minor << 8) | patch


def thin(cputype: int, minos: tuple[int, int, int], *, legacy: bool = False, commands: bool = True) -> bytes:
    if not commands:
        cmd = b""
    elif legacy:
        cmd = struct.pack("<IIII", LC_VERSION_MIN_MACOSX, 16, pack_version(*minos), pack_version(13, 0))
    else:
        cmd = struct.pack(
            "<IIIIII",
            LC_BUILD_VERSION,
            24,
            1,
            pack_version(*minos),
            pack_version(13, 0),
            0,
        )
    header = struct.pack(
        "<IIIIIIII",
        0xFEEDFACF,
        cputype,
        0,
        2,
        1 if cmd else 0,
        len(cmd),
        0,
        0,
    )
    return header + cmd


def fat(parts: list[tuple[int, bytes]]) -> bytes:
    offset = 8 + 20 * len(parts)
    blob = struct.pack(">II", 0xCAFEBABE, len(parts))
    cursor = offset
    bodies = []
    for cputype, body in parts:
        blob += struct.pack(">IIIII", cputype, 0, cursor, len(body), 3)
        bodies.append(body)
        cursor += len(body)
    return blob + b"".join(bodies)


def test_thin_x86_64_at_12_passes(tmp_path, capsys):
    path = tmp_path / "lib.dylib"
    path.write_bytes(thin(CPU_X86_64, (12, 0, 0)))
    slices = check_macos_min.scan_path(path)
    assert [(item.arch, item.minos) for item in slices] == [("x86_64", (12, 0, 0))]
    assert check_macos_min.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "architectures: x86_64" in out
    assert "highest minimum macOS: 12.0" in out
    assert "result: ok" in out


def test_minos_14_fails(tmp_path, capsys):
    path = tmp_path / "lib.dylib"
    path.write_bytes(thin(CPU_X86_64, (14, 0, 0)))
    assert check_macos_min.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "needs macOS 14.0" in out
    assert "result: failed" in out


def test_patch_above_12_fails(tmp_path):
    path = tmp_path / "lib.dylib"
    path.write_bytes(thin(CPU_X86_64, (12, 0, 1)))
    assert check_macos_min.main([str(path)]) == 1


def test_arm64_only_fails(tmp_path, capsys):
    path = tmp_path / "lib.dylib"
    path.write_bytes(thin(CPU_ARM64, (12, 0, 0)))
    assert check_macos_min.main([str(path)]) == 1
    assert "lacks x86_64 (arm64)" in capsys.readouterr().out


def test_fat_x86_64_and_arm64_at_12_passes(tmp_path, capsys):
    path = tmp_path / "lib.dylib"
    path.write_bytes(
        fat(
            [
                (CPU_X86_64, thin(CPU_X86_64, (12, 0, 0))),
                (CPU_ARM64, thin(CPU_ARM64, (12, 0, 0))),
            ]
        )
    )
    slices = check_macos_min.scan_path(path)
    assert {item.arch for item in slices} == {"x86_64", "arm64"}
    assert check_macos_min.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "architectures: arm64, x86_64" in out
    assert "result: ok" in out


def test_fat_slice_above_12_fails(tmp_path, capsys):
    path = tmp_path / "lib.dylib"
    path.write_bytes(
        fat(
            [
                (CPU_X86_64, thin(CPU_X86_64, (12, 0, 0))),
                (CPU_ARM64, thin(CPU_ARM64, (14, 0, 0))),
            ]
        )
    )
    assert check_macos_min.main([str(path)]) == 1
    assert "arm64 needs macOS 14.0" in capsys.readouterr().out


def test_legacy_version_min_command_counts(tmp_path):
    path = tmp_path / "lib.dylib"
    path.write_bytes(thin(CPU_X86_64, (12, 0, 0), legacy=True))
    slices = check_macos_min.scan_path(path)
    assert slices[0].minos == (12, 0, 0)
    assert check_macos_min.main([str(path)]) == 0


def test_directory_walk_ignores_other_files(tmp_path, capsys):
    bundle = tmp_path / "Invisible Mark Cleaner.app" / "Contents" / "MacOS"
    bundle.mkdir(parents=True)
    (bundle / "app").write_bytes(thin(CPU_X86_64, (12, 0, 0)))
    (bundle / "readme.txt").write_text("hello")
    (tmp_path / "NotABinary.class").write_bytes(b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61) + b"\x00" * 64)
    assert check_macos_min.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "mach-o files: 1" in out
    assert "result: ok" in out


def test_zip_members_are_scanned(tmp_path):
    wheel = tmp_path / "sample.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/lib.dylib", thin(CPU_X86_64, (11, 0, 0)))
        archive.writestr("pkg/readme.txt", "hello")
    slices = check_macos_min.scan_path(wheel)
    assert len(slices) == 1
    assert slices[0].arch == "x86_64"
    assert slices[0].minos == (11, 0, 0)
    assert check_macos_min.main([str(wheel)]) == 0


def test_missing_version_does_not_invent_one(tmp_path, capsys):
    path = tmp_path / "lib.dylib"
    path.write_bytes(thin(CPU_X86_64, (12, 0, 0), commands=False))
    slices = check_macos_min.scan_path(path)
    assert slices[0].minos is None
    assert check_macos_min.main([str(path)]) == 0
    assert "highest minimum macOS: unknown" in capsys.readouterr().out
