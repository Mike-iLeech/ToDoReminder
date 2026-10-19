"""Хранение настроек и дел внутри самого EXE.

Пользователь хочет один файл: переносишь EXE на флешку — дела и настройки едут с ним.

Как это устроено:
- Данные лежат в конце EXE «хвостом»: [сжатый JSON][длина, CRC32, метка]. Загрузчик
  PyInstaller ищет свой архив с конца файла и такой хвост пропускает (проверено на
  настоящих onefile-сборках, в т.ч. с хвостом в 5 МБ).
- Работающий EXE в Windows переписать нельзя, но можно переименовать. Поэтому при выходе
  программа пишет рядом копию себя с новым хвостом (.embed) и подменяет EXE: текущий
  уходит в .old (его удаляет отложенная команда сразу после выхода), копия встаёт на место.
- Пока программа работает, каждое изменение сразу пишется в рабочую копию в
  %LOCALAPPDATA%\\ToDoReminder — если программа упадёт или выключат питание, при следующем
  запуске на этом ПК данные возьмутся оттуда (у неё номер ревизии больше).
- Старая папка data рядом с EXE при первом запуске переносится внутрь и удаляется.

Модуль без Qt, чтобы его можно было тестировать отдельно.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

from storage import JsonFile

MAGIC = b"TODOREMINDER-D1\x00"          # 16 байт: метка и версия формата хвоста
TRAILER = struct.Struct("<QI16s")       # длина данных, CRC32 данных, метка
CHUNK = 1024 * 1024
EMBED_SUFFIX = ".embed"
OLD_SUFFIX = ".old"


# ------------------------------------------------------------------ формат хвоста

def pack(doc: dict) -> bytes:
    payload = zlib.compress(json.dumps(doc, ensure_ascii=False).encode("utf-8"), 6)
    return payload + TRAILER.pack(len(payload), zlib.crc32(payload), MAGIC)


def read_embedded(path) -> tuple[int, dict | None]:
    """(длина EXE без хвоста, данные из хвоста или None)."""
    path = Path(path)
    size = path.stat().st_size
    if size < TRAILER.size:
        return size, None
    with open(path, "rb") as f:
        f.seek(size - TRAILER.size)
        length, crc, magic = TRAILER.unpack(f.read(TRAILER.size))
        if magic != MAGIC or length > size - TRAILER.size:
            return size, None
        base = size - TRAILER.size - length
        f.seek(base)
        payload = f.read(length)
    if zlib.crc32(payload) != crc:
        return base, None       # хвост повреждён — данных нет, но и в копию его не тащим
    try:
        doc = json.loads(zlib.decompress(payload).decode("utf-8"))
    except (zlib.error, ValueError):
        return base, None
    return base, doc if isinstance(doc, dict) else None


def write_exe_with_data(src, dst, doc: dict) -> None:
    """dst = программа из src (без старого хвоста) + новый хвост с doc. Атомарно."""
    src, dst = Path(src), Path(dst)
    base, _ = read_embedded(src)
    tmp = dst.with_name(dst.name + ".part")
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            left = base
            while left > 0:
                chunk = fin.read(min(CHUNK, left))
                if not chunk:
                    raise OSError("исходный EXE оказался короче ожидаемого")
                fout.write(chunk)
                left -= len(chunk)
            fout.write(pack(doc))
            fout.flush()
            os.fsync(fout.fileno())
        os.replace(tmp, dst)
    except BaseException:
        _unlink_quietly(tmp)
        raise


def _unlink_quietly(path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _replace_with_retry(src: Path, dst: Path, attempts: int = 10, delay: float = 0.2) -> None:
    # антивирус может на долю секунды держать свежезаписанный файл
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def schedule_delete(path) -> None:
    """Удалить файл сразу после выхода программы (пока она работает, .old занят загрузчиком)."""
    if sys.platform != "win32":
        return
    p = str(path)
    # ping — пауза ~1 с между попытками. Условие обязательно в скобках: в cmd всё, что стоит
    # после `if` на той же строке (включая `& ping`), входит в тело if, и без скобок пауза
    # пропускалась — все попытки сгорали за миллисекунды, пока файл ещё занят загрузчиком
    ping = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
    erase = "del " + "/f /q"
    inner = (f'for /l %i in (1,1,30) do @({erase} "{p}" >nul 2>&1 & '
             f'(if not exist "{p}" exit /b) & "{ping}" -n 2 127.0.0.1 >nul)')
    # строкой, а не списком: при списке subprocess экранирует кавычки как \", а cmd так не
    # понимает; /s снимает только внешние кавычки и оставляет команду как есть
    try:
        # явные стандартные потоки: у отсоединённого процесса их нет, и без них ping
        # завершался мгновенно — все попытки удаления проскакивали, пока файл ещё занят
        subprocess.Popen(f'cmd /d /s /c "{inner}"', close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    except OSError:
        pass  # не страшно: .old уберёт следующий запуск


def default_work_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ToDoReminder"


# ------------------------------------------------------------------ хранилище

class EmbeddedStore:
    """Настройки и дела внутри EXE + рабочая копия на время работы программы."""

    def __init__(self, exe, work_dir=None, legacy_dir=None) -> None:
        self.exe = Path(exe)
        self.work_dir = Path(work_dir) if work_dir else default_work_dir()
        key = hashlib.sha1(str(self.exe).lower().encode("utf-8")).hexdigest()[:16]
        self.work_file = JsonFile(self.work_dir / f"work-{key}.json")
        self.legacy_dir = Path(legacy_dir) if legacy_dir else self.exe.parent / "data"
        self._migrated_files: list[Path] = []
        self.last_error: str | None = None
        self._doc, self._embedded_rev = self._load()

    # ---- загрузка

    def _load(self) -> tuple[dict, int]:
        try:
            _, embedded = read_embedded(self.exe)
        except OSError:
            embedded = None
        work = self.work_file.load(None) if self.work_file.exists() else None
        work = work if isinstance(work, dict) else None
        embedded_rev = int(embedded.get("rev", 0)) if embedded else -1
        candidates = [d for d in (embedded, work) if d]
        if candidates:
            # у рабочей копии ревизия больше, только если прошлый выход не успел записать EXE
            doc = max(candidates, key=lambda d: int(d.get("rev", 0)))
            return self._normalize(doc), embedded_rev
        doc = self._migrate_legacy()
        # чистый первый запуск: записывать в EXE нечего, пока ничего не изменилось
        return doc, (embedded_rev if self._migrated_files else doc["rev"])

    @staticmethod
    def _normalize(doc: dict) -> dict:
        return {
            "rev": int(doc.get("rev", 0)),
            "settings": doc.get("settings") if isinstance(doc.get("settings"), dict) else {},
            "tasks": doc.get("tasks") if isinstance(doc.get("tasks"), dict) else {},
        }

    def _migrate_legacy(self) -> dict:
        """Первый запуск после перехода: забрать данные из старой папки data рядом с EXE."""
        doc = {"rev": 0, "settings": {}, "tasks": {}}
        for key, name in (("settings", "settings.json"), ("tasks", "tasks.json")):
            path = self.legacy_dir / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                # не прочитался — не переносим и, главное, не удаляем: пусть лежит как был
                self.last_error = f"не удалось прочитать {path}"
                continue
            if isinstance(data, dict):
                doc[key] = data
                self._migrated_files.append(path)
        if self._migrated_files:
            doc["rev"] = 1          # данные есть, но в EXE их ещё нет — записать при выходе
            self._write_work(doc)
        return doc

    # ---- чтение / запись

    def load_settings(self) -> dict:
        return dict(self._doc["settings"])

    def load_tasks(self) -> dict:
        return json.loads(json.dumps(self._doc["tasks"]))

    def save_settings(self, data: dict) -> None:
        self._update("settings", data)

    def save_tasks(self, data: dict) -> None:
        self._update("tasks", data)

    def _update(self, key: str, data: dict) -> None:
        if self._doc.get(key) == data:
            return
        self._doc[key] = json.loads(json.dumps(data))
        self._doc["rev"] += 1
        self._write_work(self._doc)

    def _write_work(self, doc: dict) -> None:
        try:
            self.work_file.save(doc)
        except OSError as e:
            self.last_error = f"рабочая копия: {e}"

    @property
    def dirty(self) -> bool:
        return self._doc["rev"] != self._embedded_rev

    # ---- запись внутрь EXE

    def finalize(self) -> bool:
        """При выходе: записать данные внутрь EXE. False — не удалось (данные остаются
        в рабочей копии на этом ПК и будут записаны при следующем выходе)."""
        if not self.dirty:
            self._drop_work()
            return True
        embed = self.exe.with_name(self.exe.name + EMBED_SUFFIX)
        old = self.exe.with_name(self.exe.name + OLD_SUFFIX)
        try:
            write_exe_with_data(self.exe, embed, self._doc)
            _unlink_quietly(old)
            _replace_with_retry(self.exe, old)
            try:
                _replace_with_retry(embed, self.exe)
            except OSError:
                os.replace(old, self.exe)       # вернуть рабочий EXE на место
                raise
        except OSError as e:
            _unlink_quietly(embed)
            self.last_error = f"запись в EXE: {e}"
            return False
        self._embedded_rev = self._doc["rev"]
        self._drop_work()
        self._drop_legacy()
        schedule_delete(old)
        return True

    def embed_into(self, path) -> None:
        """Перенести текущие данные в другой EXE (скачанное обновление) — чтобы после
        подмены программы дела и настройки не потерялись."""
        path = Path(path)
        tmp = path.with_name(path.name + EMBED_SUFFIX)
        write_exe_with_data(path, tmp, self._doc)
        os.replace(tmp, path)

    def _drop_work(self) -> None:
        _unlink_quietly(self.work_file.path)

    def _drop_legacy(self) -> None:
        for path in self._migrated_files:
            _unlink_quietly(path)
        self._migrated_files = []
        try:
            self.legacy_dir.rmdir()     # только если папка опустела
        except OSError:
            pass
