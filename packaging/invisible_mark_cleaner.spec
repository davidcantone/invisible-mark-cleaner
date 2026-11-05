# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# pikepdf 9.3.0 publishes a macOS 12 wheel for x86_64 only, so the app cannot be universal2.
repo = os.path.abspath(os.path.join(SPECPATH, ".."))
# Must match the --limit given to scripts/check_macos_min.py; build_mac.sh passes both from MACOS_MIN.
macos_min = os.environ.get("MACOS_MIN", "12.0")

qt_excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "pytest",
    "pypdf",
    "pypdfium2",
    "tkinter",
]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[repo],
    binaries=collect_dynamic_libs("pikepdf"),
    datas=[],
    hiddenimports=collect_submodules("invisible_mark_cleaner") + collect_submodules("pikepdf"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=qt_excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="InvisibleMarkCleaner",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch="x86_64",
        codesign_identity=None,
        entitlements_file=None,
    )
elif sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name="Invisible Mark Cleaner",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch="x86_64",
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="Invisible Mark Cleaner",
    )
    app = BUNDLE(
        coll,
        name="Invisible Mark Cleaner.app",
        bundle_identifier="org.invisiblemarkcleaner.app",
        version="1.0.0",
        info_plist={
            "CFBundleName": "Invisible Mark Cleaner",
            "CFBundleDisplayName": "Invisible Mark Cleaner",
            "CFBundleIdentifier": "org.invisiblemarkcleaner.app",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": macos_min,
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "PDF",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["com.adobe.pdf"],
                    "CFBundleTypeExtensions": ["pdf"],
                }
            ],
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name="invisible-mark-cleaner",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="invisible-mark-cleaner",
    )
