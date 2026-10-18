"""Генерирует version_info.txt (метаданные EXE для PyInstaller) из version.py.

Единственный источник номера версии — version.py: по нему же автообновление
сравнивает версии, поэтому метаданные EXE не должны расходиться с ним.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from version import APP_AUTHOR, APP_NAME, APP_VERSION  # noqa: E402

nums = [int(p) for p in re.findall(r"\d+", APP_VERSION)][:4]
nums += [0] * (4 - len(nums))
vt = ", ".join(str(n) for n in nums)

TEMPLATE = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({vt}),
    prodvers=({vt}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{APP_AUTHOR}'),
        StringStruct('FileDescription', '{APP_NAME}'),
        StringStruct('FileVersion', '{APP_VERSION}'),
        StringStruct('InternalName', 'ToDoReminder'),
        StringStruct('LegalCopyright', 'Copyright (c) 2026 {APP_AUTHOR}'),
        StringStruct('OriginalFilename', 'ToDoReminder.exe'),
        StringStruct('ProductName', '{APP_NAME}'),
        StringStruct('ProductVersion', '{APP_VERSION}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

out = ROOT / "version_info.txt"
out.write_bytes(TEMPLATE.encode("utf-8"))
print("version_info.txt ->", APP_VERSION)
