$ErrorActionPreference = "Stop"

# Запускать из корня репозитория
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m pip show pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
    python -m pip install pyinstaller
}

# 1. Иконка
python tools\make_icon.py

# 2. Сборка one-file windowed EXE (метаданные версии из version_info.txt)
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "ToDoReminder" `
    --icon "resources\icon.ico" `
    --version-file "version_info.txt" `
    --add-data "resources\icon.ico;resources" `
    main.py

Write-Host "BUILD DONE"
Test-Path "dist\ToDoReminder.exe"