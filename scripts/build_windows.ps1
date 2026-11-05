# Windows PowerShell 5.1 or PowerShell 7. Produces dist\InvisibleMarkCleaner.exe.
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path .venv\Scripts\python.exe)) {
    python -m venv .venv
}
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"

& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Offscreen keeps pytest from opening a window on a build agent.
$env:QT_QPA_PLATFORM = "offscreen"
& $py -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py -m PyInstaller packaging\invisible_mark_cleaner.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path (Get-Location) "dist\InvisibleMarkCleaner.exe"
if (-not (Test-Path $exe)) {
    Write-Error "missing $exe"
    exit 1
}

$work = Join-Path $env:TEMP ("invisible-mark-cleaner-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $work | Out-Null
Copy-Item tests\fixtures\white_text.pdf (Join-Path $work "white_text.pdf")
& $exe --clean (Join-Path $work "white_text.pdf")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$json = @(Get-ChildItem $work -Filter *.report.json)
$pdfs = @(Get-ChildItem $work -Filter *.pdf)
if ($json.Count -lt 1 -or $pdfs.Count -lt 2) {
    Write-Error "headless smoke did not write a clean copy and a report"
    exit 1
}
