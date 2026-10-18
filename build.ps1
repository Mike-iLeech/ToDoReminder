$ErrorActionPreference = "Stop"

# Запускать из корня репозитория
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Invoke-Step($what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "${what}: код выхода $LASTEXITCODE" }
}

python -m pip show pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
    Invoke-Step "pip install pyinstaller" { python -m pip install pyinstaller }
}

# 1. Иконка и метаданные версии (версия берётся из version.py)
Invoke-Step "make_icon" { python tools\make_icon.py }
Invoke-Step "gen_version_info" { python tools\gen_version_info.py }

# 2. Сборка one-file windowed EXE.
#    Ненужные модули исключены: меньше EXE — быстрее распаковка при каждом запуске.
Invoke-Step "PyInstaller" {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name "ToDoReminder" `
        --icon "resources\icon.ico" `
        --version-file "version_info.txt" `
        --add-data "resources\icon.ico;resources" `
        --exclude-module tkinter `
        --exclude-module unittest `
        --exclude-module pydoc `
        --exclude-module PySide6.QtNetwork `
        --exclude-module PySide6.QtQml `
        --exclude-module PySide6.QtQuick `
        main.py
}

if (-not (Test-Path "dist\ToDoReminder.exe")) { throw "dist\ToDoReminder.exe не найден" }
Write-Host "BUILD DONE"
