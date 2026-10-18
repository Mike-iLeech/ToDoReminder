"""Печатает раздел CHANGELOG.md для версии — текст релиза на GitHub.

Именно этот текст автообновление показывает пользователю в окне «Доступно обновление».
python tools/release_notes.py 2.7.0.0 notes.md
Файл пишется напрямую в UTF-8: при перенаправлении через PowerShell кириллица
искажается кодировкой консоли раннера.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    if not m:
        return f"ToDo Reminder {version}"
    return m.group(1).strip().rstrip("-").strip()


if __name__ == "__main__":
    notes = section(sys.argv[1].lstrip("vV"))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(notes + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(notes)
