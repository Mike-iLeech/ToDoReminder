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
import shutil
import struct
import subprocess
import sys
import time
import uuid
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


def inspect_embedded(path) -> tuple[int, dict | None, bool]:
    """(длина EXE без хвоста, данные из хвоста или None, хвост есть, но повреждён)."""
    path = Path(path)
    size = path.stat().st_size
    if size < TRAILER.size:
        return size, None, False
    with open(path, "rb") as f:
        f.seek(size - TRAILER.size)
        tail = f.read(TRAILER.size)
        length, crc, magic = TRAILER.unpack(tail)
        if magic != MAGIC:
            # файл кончается нулями — типичный след выдернутой флешки (недописанные кластеры):
            # хвост, скорее всего, был и пропал. Программа-то запустится (загрузчик PyInstaller
            # находит свой архив раньше), а вот данные потеряны — об этом надо сказать
            return size, None, tail == b"\x00" * TRAILER.size
        if length > size - TRAILER.size:
            return size, None, True
        base = size - TRAILER.size - length
        f.seek(base)
        payload = f.read(length)
    if zlib.crc32(payload) != crc:
        # хвост повреждён, и поле длины тоже может быть испорчено — тогда «программа без
        # хвоста» оказалась бы обрезанной. Безопаснее считать программой весь файл: новый
        # хвост ляжет после старого, а загрузчик PyInstaller найдёт свой архив как и раньше
        return size, None, True
    try:
        doc = json.loads(zlib.decompress(payload).decode("utf-8"))
    except (zlib.error, ValueError):
        return size, None, True
    if not isinstance(doc, dict):
        return size, None, True
    return base, doc, False


def read_embedded(path) -> tuple[int, dict | None]:
    """(длина EXE без хвоста, данные из хвоста или None)."""
    base, doc, _ = inspect_embedded(path)
    return base, doc


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
    # Путь передаётся через переменную окружения: её значение cmd не разбирает повторно,
    # поэтому %VAR%, %i, &, ^, ! и т.п. в пути не подставляются и ничего не ломают.
    env = dict(os.environ)
    env["TODOREMINDER_OLD"] = str(path)
    # ping — пауза ~1 с между попытками. Условие обязательно в скобках: в cmd всё, что стоит
    # после `if` на той же строке (включая `& ping`), входит в тело if, и без скобок пауза
    # пропускалась — все попытки сгорали за миллисекунды, пока файл ещё занят загрузчиком
    ping = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")
    erase = "del " + "/f /q"
    inner = (f'for /l %i in (1,1,30) do @({erase} "%TODOREMINDER_OLD%" >nul 2>&1 & '
             f'(if not exist "%TODOREMINDER_OLD%" exit /b) & "{ping}" -n 2 127.0.0.1 >nul)')
    # строкой, а не списком: при списке subprocess экранирует кавычки как \", а cmd так не
    # понимает; /s снимает только внешние кавычки и оставляет команду как есть
    try:
        subprocess.Popen(f'cmd /d /s /c "{inner}"', close_fds=True, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    except OSError:
        pass  # не страшно: .old уберёт следующий запуск


def default_work_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ToDoReminder"


# ------------------------------------------------------------------ хранилище

def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _section(doc: dict, key: str) -> dict:
    value = doc.get(key)
    return value if isinstance(value, dict) else {}


class EmbeddedStore:
    """Настройки и дела внутри EXE + рабочая копия на время работы программы.

    «Поколение» (gen) — случайная метка, которая ставится при каждой записи данных в EXE.
    Рабочая копия помнит, от какого поколения она пошла (base_gen). Её изменения берутся,
    только если EXE содержит то же самое поколение: иначе EXE успели изменить в другом
    месте (например, на другом ПК с флешки), и старая рабочая копия перебила бы более
    новые данные. Такая копия не применяется и не удаляется — её откладывают в файл
    «…-conflict-<время>.json» и сообщают пользователю.
    """

    def __init__(self, exe, work_dir=None, legacy_dir=None) -> None:
        self.exe = Path(exe)
        self.work_dir = Path(work_dir) if work_dir else default_work_dir()
        key = hashlib.sha1(str(self.exe).lower().encode("utf-8")).hexdigest()[:16]
        self._key = key
        self.work_file = JsonFile(self.work_dir / f"work-{key}.json")
        self.legacy_dir = Path(legacy_dir) if legacy_dir else self.exe.parent / "data"
        self._migrated_files: list[Path] = []
        self.last_error: str | None = None
        self.notices: list[str] = []          # что показать пользователю после запуска
        self._doc: dict = {"rev": 0, "settings": {}, "tasks": {}}
        self._base_gen: str | None = None     # поколение данных, лежащих сейчас в EXE
        self._pending_gen: str | None = None  # поколение, записанное в скачанное обновление
        self._embedded_rev: int = 0
        self._work_blocked = False            # рабочую копию нельзя перезаписывать (см. _set_aside)
        self._exe_unreadable: str | None = None
        self._work_ok = True                  # последняя запись рабочей копии удалась
        self.fallback_path: Path | None = None  # куда сохранены данные, если в EXE записать не удалось
        self._load()

    # ---- загрузка

    def _read_work(self) -> dict | None:
        if not self.work_file.exists():
            return None
        try:
            data = json.loads(self.work_file.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("rev"), int):
            self._set_aside("damaged", "Рабочая копия данных повреждена и отложена")
            return None
        return data

    def _set_aside(self, tag: str, message: str) -> None:
        """Отложить рабочую копию в отдельный файл (не удалять — там могут быть данные)."""
        try:
            digest = hashlib.sha1(self.work_file.path.read_bytes()).hexdigest()[:10]
        except OSError:
            digest = uuid.uuid4().hex[:10]
        # имя по содержимому: одна и та же копия откладывается один раз, а не при каждом запуске
        existing = list(self.work_dir.glob(f"work-{self._key}-{tag}-*-{digest}.json"))
        if existing:
            _unlink_quietly(self.work_file.path)
            if self.work_file.path.exists():
                self._work_blocked = True   # уже отложена, но оригинал не удалить — не трогаем
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.work_dir / f"work-{self._key}-{tag}-{stamp}-{digest}.json"
        try:
            os.replace(self.work_file.path, target)
        except OSError:
            try:
                shutil.copy2(self.work_file.path, target)   # переименовать не дали — хотя бы копия
                _unlink_quietly(self.work_file.path)
                if self.work_file.path.exists():
                    self._work_blocked = True   # копия есть, оригинал держат — не перезаписывать
            except OSError as e:
                # и скопировать не вышло: тогда рабочую копию не трогаем вовсе, чтобы первое же
                # сохранение не затёрло эти данные (изменения этой сессии живут до выхода)
                self._work_blocked = True
                self.notices.append(f"{message}, но отложить её не удалось ({e}); файл оставлен: "
                                    f"{self.work_file.path}")
                return
        self.notices.append(f"{message}: {target}")

    def _load(self) -> None:
        try:
            _, embedded, damaged = inspect_embedded(self.exe)
        except OSError as e:
            # свой же EXE не прочитался: данные в нём могут быть, просто недоступны сейчас.
            # Писать в EXE в этой сессии нельзя — иначе запись отрезала бы настоящий хвост
            embedded, damaged = None, False
            self._exe_unreadable = f"не удалось прочитать программу: {e}"
        e_gen = embedded.get("gen") if embedded else None
        e_rev = _as_int(embedded.get("rev")) if embedded else 0
        work = self._read_work()
        if embedded is None and not damaged and work is not None and work.get("base_gen"):
            # рабочая копия продолжает данные, которые были в EXE, а в EXE их нет — хвост
            # потерян (обрезан или испорчен целиком); это повреждение, а не «чистый» EXE
            damaged = True

        if work is not None and embedded is not None and \
                _section(work, "settings") == _section(embedded, "settings") and \
                _section(work, "tasks") == _section(embedded, "tasks"):
            # в рабочей копии то же, что в программе (например, её не дал удалить антивирус) —
            # ни восстанавливать, ни откладывать нечего
            self._drop_work()
            work = None

        doc = None
        if damaged:
            if work is not None:
                doc = work
                try:
                    when = time.strftime("%d.%m.%Y %H:%M", time.localtime(self.work_file.path.stat().st_mtime))
                except OSError:
                    when = "неизвестно когда"
                self.notices.append("Данные внутри программы повреждены — восстановлены из рабочей "
                                    f"копии на этом компьютере (сохранена {when}). Если программой "
                                    "пользовались на другом ПК, эти данные могут быть старее")
            else:
                self.notices.append("Данные внутри программы повреждены и не прочитаны — список начат "
                                    "заново. Если у вас есть экспорт, его можно импортировать")
        elif work is not None:
            pending = work.get("pending_gen")
            if work.get("base_gen") == e_gen or (pending and pending == e_gen):
                # продолжение тех же данных (в т.ч. после установки обновления, куда они были
                # перенесены): рабочая копия новее, только если прошлый выход не успел
                # записать их в EXE (сбой, выключение, нет прав, не установилось обновление)
                if embedded is None or work["rev"] > e_rev:
                    doc = work
                    self.notices.append("Восстановлены изменения, которые не успели записаться "
                                        "в программу при прошлом выходе")
            else:
                self._set_aside("conflict", "Найдены несохранённые изменения от другой копии данных — "
                                            "программа уже содержит более новые. Старые изменения "
                                            "отложены в файл")
        if doc is None and embedded is not None:
            doc = embedded
        if doc is None:
            doc = {"rev": 0, "settings": {}, "tasks": {}}

        self._doc = {"rev": _as_int(doc.get("rev")), "settings": _section(doc, "settings"),
                     "tasks": _section(doc, "tasks")}
        self._base_gen = e_gen
        self._embedded_rev = e_rev if embedded is not None else 0
        self._merge_legacy()

    def _merge_legacy(self) -> None:
        """Папка data от старых версий: забрать то, чего ещё нет внутри, и удалить её после
        записи в EXE. Повторяется при каждом запуске, пока файлы лежат (например, если
        файл не читался, а его потом исправили)."""
        changed = False
        for key, path in (("settings", self.legacy_dir / "settings.json"),
                          ("tasks", self.legacy_dir / "tasks.json")):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                # не прочитался — не переносим и, главное, не удаляем: пусть лежит как был
                self.last_error = f"не удалось прочитать {path}"
                self.notices.append(f"Не удалось прочитать старый файл данных {path} — он оставлен как есть")
                continue
            if not isinstance(data, dict):
                continue
            if not self._doc[key]:
                self._doc[key] = data
                changed = True
            # если внутри уже есть свои данные, файл — остаток прошлого переноса: просто удалить
            self._migrated_files.append(path)
        if changed:
            self._doc["rev"] += 1
            self._write_work()
        elif self._migrated_files and not self.dirty:
            self._embedded_rev = -1     # данные уже внутри, но папку data нужно убрать при выходе

    # ---- чтение / запись

    def load_settings(self) -> dict:
        return json.loads(json.dumps(self._doc["settings"]))

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
        self._write_work()

    def _work_payload(self) -> dict:
        return dict(self._doc, base_gen=self._base_gen, pending_gen=self._pending_gen)

    def _write_work(self) -> None:
        if self._work_blocked:
            return
        try:
            self.work_file.save(self._work_payload())
            self._work_ok = True
        except OSError as e:
            self._work_ok = False
            self.last_error = f"рабочая копия: {e}"

    @property
    def dirty(self) -> bool:
        return self._doc["rev"] != self._embedded_rev

    def _embedded_doc(self, gen: str) -> dict:
        return dict(self._doc, gen=gen)

    # ---- запись внутрь EXE

    def finalize(self) -> bool:
        """При выходе: записать данные внутрь EXE. False — не удалось (данные остаются
        в рабочей копии на этом ПК и будут записаны при следующем выходе)."""
        if not self.dirty:
            self._drop_work()
            return True
        if self._exe_unreadable:
            self.last_error = self._exe_unreadable
            self._save_fallback()
            return False
        gen = uuid.uuid4().hex
        embed = self.exe.with_name(self.exe.name + EMBED_SUFFIX)
        old = self.exe.with_name(self.exe.name + OLD_SUFFIX)
        try:
            write_exe_with_data(self.exe, embed, self._embedded_doc(gen))
            _unlink_quietly(old)
            _replace_with_retry(self.exe, old)
        except OSError as e:
            _unlink_quietly(embed)
            self.last_error = f"запись в программу: {e}"
            self._save_fallback()
            return False
        try:
            _replace_with_retry(embed, self.exe)
        except OSError as e:
            try:
                os.replace(old, self.exe)       # вернуть рабочий EXE на место
                _unlink_quietly(embed)
            except OSError:
                pass        # .embed не удаляем: если не вернулся и прежний EXE, в нём наши данные
            self.last_error = f"запись в программу: {e}"
            self._save_fallback()
            return False
        self._base_gen = gen
        self._pending_gen = None
        self._embedded_rev = self._doc["rev"]
        self._drop_work()
        self._drop_legacy()
        schedule_delete(old)
        return True

    def embed_into(self, path) -> None:
        """Перенести текущие данные в другой EXE (скачанное обновление) — чтобы после
        подмены программы дела и настройки не потерялись.

        Состояние текущего EXE не меняется: обновление ещё может не установиться, и тогда
        при выходе данные должны записаться в прежний EXE как обычно. Рабочая копия лишь
        запоминает поколение обновления (pending_gen) — после установки новая версия
        узнает в ней продолжение своих данных и не примет её за чужую."""
        path = Path(path)
        gen = uuid.uuid4().hex
        tmp = path.with_name(path.name + EMBED_SUFFIX)
        write_exe_with_data(path, tmp, self._embedded_doc(gen))
        os.replace(tmp, path)
        self._pending_gen = gen
        # не записалась — не страшно и удалять её нельзя: в ней тот же текущий набор данных,
        # что ушёл в обновление; после установки её тихо уберёт проверка «то же содержимое»,
        # а если установка не удастся и случится сбой — из неё восстановятся правки сессии
        self._write_work()

    def _save_fallback(self) -> None:
        """В EXE записать не удалось — убедиться, что данные сессии лежат хоть где-то на диске,
        и запомнить где (для сообщения пользователю)."""
        self.fallback_path = None
        if not self._work_blocked and self._work_ok and self.work_file.exists():
            self.fallback_path = self.work_file.path
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for target in (self.work_dir / f"work-{self._key}-session-{stamp}-{uuid.uuid4().hex[:6]}.json",
                       self.exe.with_name(self.exe.name + ".unsaved.json")):
            try:
                JsonFile(target).save(self._work_payload())
                self.fallback_path = target
                return
            except OSError:
                continue

    def _drop_work(self) -> None:
        if self._work_blocked:
            return      # там данные, которые не удалось отложить, — не удалять
        _unlink_quietly(self.work_file.path)

    def _drop_legacy(self) -> None:
        for path in self._migrated_files:
            _unlink_quietly(path)
        self._migrated_files = []
        try:
            self.legacy_dir.rmdir()     # только если папка опустела
        except OSError:
            pass
