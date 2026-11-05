#!/usr/bin/env bash
# Intel Mac or the macos-15-intel runner. pikepdf 9.3.0 has no arm64 macOS 12 wheel.
set -euo pipefail
cd "$(dirname "$0")/.."

# Lowest macOS the app claims to support. A python.org 3.12 build keeps every binary at 12.0 or lower.
# A Python compiled locally (pyenv) inherits the build Mac's version, e.g. MACOS_MIN=12.6.
export MACOS_MIN="${MACOS_MIN:-12.0}"

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
python -m PyInstaller packaging/invisible_mark_cleaner.spec --noconfirm

APP="dist/Invisible Mark Cleaner.app"
python scripts/check_macos_min.py --limit "$MACOS_MIN" "$APP"
/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" "$APP/Contents/Info.plist" | grep -qx "$MACOS_MIN"

BIN="$APP/Contents/MacOS/Invisible Mark Cleaner"
work="$(mktemp -d)"
cp tests/fixtures/white_text.pdf "$work/white_text.pdf"
"$BIN" --clean "$work/white_text.pdf"
jsons=("$work"/*.report.json)
pdfs=("$work"/*.pdf)
test "${#jsons[@]}" -ge 1
test "${#pdfs[@]}" -ge 2

stage="$(mktemp -d)"
cp -R "$APP" "$stage/"
ln -s /Applications "$stage/Applications"
hdiutil create \
  -volname "Invisible Mark Cleaner" \
  -srcfolder "$stage" \
  -ov \
  -format UDZO \
  "dist/InvisibleMarkCleaner.dmg"
