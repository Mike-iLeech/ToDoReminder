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

import getpass
import hashlib
import json
import os
import shutil
import socket
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
PYI_COOKIE = b"MEI\x0c\x0b\x0a\x0b\x0e"   # метка архива PyInstaller в конце onefile-EXE
PYI_COOKIE_RECORD = 88                    # struct «!8sIIii64s»: метка, длины, версия, имя python*.dll
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
            # Нашего хвоста нет. Чистая программа (из релиза, ещё без данных) кончается ровно
            # служебной записью PyInstaller (cookie «MEI…», 88 байт) — это нормально. Если же
            # в самом конце нет ни нашего хвоста, ни cookie, файл обрезан или испорчен (например,
            # флешку выдернули при записи) — данные пропали. Искать cookie «где-то рядом» нельзя:
            # при обрезке нескольких байт хвоста она нашлась бы перед ним, и потеря прошла бы тихо
            clean = False
            if size >= PYI_COOKIE_RECORD:
                f.seek(size - PYI_COOKIE_RECORD)
                clean = f.read(len(PYI_COOKIE)) == PYI_COOKIE
            return size, None, not clean
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
        self._obsolete_files: list[Path] = []   # учтённые запасные файлы — убрать после записи в EXE
        self._base_unknown = False             # EXE не читался и копий не было — «основа» правок неизвестна
        self._origin = self._make_origin()
        self._load()

    # ---- загрузка
    #
    # «Копии» — рабочая копия (work-<ключ>.json) и запасные файлы прошлых неудачных выходов
    # (work-<ключ>-session-*.json, <exe>.unsaved.json). У всех один формат: данные + rev +
    # base_gen/pending_gen (от какого поколения данных в EXE они пошли). Правила:
    #   1. копия с тем же содержимым, что в EXE, — лишняя: удаляется сразу;
    #   2. копия «своей линии» (поколение совпадает с EXE): берётся самая свежая, если она новее
    #      EXE (прошлый выход не успел записать); старшие свои копии уже перекрыты — удаляются;
    #   3. копия чужой линии (EXE меняли в другом месте) или сделанная, когда EXE не читался, —
    #      не выбирается и не удаляется: один раз откладывается в …-conflict/unsaved-<хэш>.json
    #      с сообщением (открыть можно через «Импорт»);
    #   4. хвост EXE повреждён — опора на рабочую копию этого ПК и копии её линии.

    def _make_origin(self) -> str:
        """Метка «где сделана копия»: ПК + пользователь + рабочая папка. Нужна, чтобы отличать
        копии одной основы, сделанные в разных местах (флешка переезжает между ПК вместе с
        <exe>.unsaved.json): «перекрытой» считается только своя же более старая копия."""
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001
            user = ""
        raw = f"{socket.gethostname()}|{user}|{self.work_dir}".lower().encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:12]

    def _origin_of(self, copy) -> str | None:
        """Происхождение копии. У копий без метки (созданы до её появления) своей считается
        только та, что лежит в рабочей папке этого ПК (рабочая копия и session-файлы всегда
        локальны); <exe>.unsaved.json без метки мог приехать на флешке с другого ПК —
        происхождение неизвестно (None), его не удаляют как «перекрытый», а откладывают."""
        path, data = copy
        return data.get("origin") or (self._origin if path.parent == self.work_dir else None)

    def _copy_paths(self) -> list[Path]:
        paths = [self.work_file.path] if self.work_file.exists() else []
        if self.work_dir.exists():
            paths += sorted(self.work_dir.glob(f"work-{self._key}-session-*.json"))
        unsaved = self.exe.with_name(self.exe.name + ".unsaved.json")
        if unsaved.exists():
            paths.append(unsaved)
        return paths

    @staticmethod
    def _read_copy(path: Path) -> dict | None:
        for attempt in range(3):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                break
            except OSError:
                if attempt == 2:
                    return None
                time.sleep(0.1)     # файл на миг занят (антивирус) — не считать его испорченным
            except ValueError:
                return None
        return data if isinstance(data, dict) and isinstance(data.get("rev"), int) else None

    @staticmethod
    def _same_content(a: dict, b: dict) -> bool:
        return _section(a, "settings") == _section(b, "settings") and _section(a, "tasks") == _section(b, "tasks")

    @staticmethod
    def _modified(path: Path) -> str:
        try:
            return time.strftime("%d.%m.%Y %H:%M", time.localtime(path.stat().st_mtime))
        except OSError:
            return "неизвестно когда"

    def _remove_copy(self, path: Path) -> None:
        if path == self.work_file.path:
            self._drop_work()
        else:
            _unlink_quietly(path)

    def _set_aside(self, path: Path, tag: str, message: str) -> None:
        """Отложить копию в отдельный файл (не удалять — там могут быть данные). Одна и та же
        копия откладывается один раз: имя файла — по хэшу содержимого."""
        is_work = path == self.work_file.path
        try:
            digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
        except OSError:
            digest = uuid.uuid4().hex[:10]
        if list(self.work_dir.glob(f"work-{self._key}-{tag}-*-{digest}.json")):
            _unlink_quietly(path)                   # уже отложена раньше — оригинал лишний
            if is_work and path.exists():
                self._work_blocked = True
            return
        target = self.work_dir / f"work-{self._key}-{tag}-{time.strftime('%Y%m%d-%H%M%S')}-{digest}.json"
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        except OSError:
            try:
                shutil.copy2(path, target)          # переименовать не дали — хотя бы копия
                _unlink_quietly(path)
            except OSError as e:
                if is_work:
                    # рабочую копию не перезаписывать и не удалять, чтобы не затереть эти данные
                    self._work_blocked = True
                self.notices.append(f"{message}, но отложить не удалось ({e}); файл оставлен: {path}")
                return
            if is_work and path.exists():
                self._work_blocked = True
        self.notices.append(f"{message}: {target}")

    def _load(self) -> None:
        try:
            _, embedded, damaged = inspect_embedded(self.exe)
        except OSError as e:
            self._load_unreadable(e)
            return
        e_gen = embedded.get("gen") if embedded else None
        e_rev = _as_int(embedded.get("rev")) if embedded else 0
        work_path = self.work_file.path

        copies: list[tuple[Path, dict]] = []
        for path in self._copy_paths():
            data = self._read_copy(path)
            if data is None:
                self._set_aside(path, "damaged", "Файл с копией данных повреждён и отложен")
            elif embedded is not None and self._same_content(data, embedded):
                self._remove_copy(path)             # правило 1
            else:
                copies.append((path, data))

        def gens(d: dict) -> set:
            return {d.get("base_gen"), d.get("pending_gen")} - {None}

        if embedded is None and not damaged and any(d.get("base_gen") for _, d in copies):
            # копии продолжают данные, которые были в EXE, а в EXE их нет — хвост потерян
            # (обрезан или испорчен целиком); это повреждение, а не «чистый» EXE
            damaged = True

        chosen = None
        own: list[tuple[Path, dict]] = []
        if damaged:
            anchor = next((c for c in copies if c[0] == work_path), None)
            if anchor is None and copies:
                anchor = max(copies, key=lambda c: c[0].stat().st_mtime if c[0].exists() else 0)
            if anchor is not None:
                line = gens(anchor[1])
                own = [c for c in copies if c is anchor or not c[1].get("base_unknown") and (
                    (line and gens(c[1]) & line) or (not line and not gens(c[1])))]
                chosen = max(own, key=lambda c: c[1]["rev"])
                self.notices.append("Данные внутри программы повреждены — восстановлены из копии на этом "
                                    f"компьютере (сохранена {self._modified(chosen[0])}). Если программой "
                                    "пользовались на другом ПК, эти данные могут быть старее")
            else:
                self.notices.append("Данные внутри программы повреждены и не прочитаны — список начат "
                                    "заново. Если у вас есть экспорт, его можно импортировать")
        else:
            own = [c for c in copies if not c[1].get("base_unknown")
                   and (c[1].get("base_gen") == e_gen or (c[1].get("pending_gen") and c[1].get("pending_gen") == e_gen))]
            newer = [c for c in own if embedded is None or c[1]["rev"] > e_rev]
            if newer:
                chosen = max(newer, key=lambda c: c[1]["rev"])
                self.notices.append("Восстановлены изменения, которые не успели записаться "
                                    "в программу при прошлом выходе")

        for c in copies:
            if c is chosen:
                continue
            path, data = c
            reference = self._origin_of(chosen) if chosen else self._origin
            same_origin = reference is not None and self._origin_of(c) == reference
            superseded = c in own and same_origin and (
                chosen is None or data["rev"] <= chosen[1]["rev"])
            if superseded:
                if damaged:
                    self._obsolete_files.append(path)   # своя, но старше выбранной — убрать после записи
                else:
                    self._remove_copy(path)             # правило 2: перекрыта EXE или выбранной копией
            elif c in own and chosen is None:
                self._remove_copy(path)                 # той же основы и не новее EXE — уже внутри
            elif data.get("base_unknown"):
                self._set_aside(path, "unsaved", "Изменения, сделанные, когда данные программы не "
                                                 f"читались ({self._modified(path)}), отложены — их можно "
                                                 "открыть через «Импорт»")
            else:
                self._set_aside(path, "conflict", "Найдены несохранённые изменения от другой копии данных "
                                                  f"({self._modified(path)}) — в программе уже другие данные. "
                                                  "Эти изменения отложены — их можно открыть через «Импорт»")

        doc = chosen[1] if chosen else (embedded or {"rev": 0, "settings": {}, "tasks": {}})
        self._doc = {"rev": _as_int(doc.get("rev")), "settings": _section(doc, "settings"),
                     "tasks": _section(doc, "tasks")}
        self._base_gen = e_gen
        self._embedded_rev = e_rev if embedded is not None else 0
        if damaged:
            self._embedded_rev = -1         # переписать испорченный хвост при выходе
        if chosen is not None and chosen[0] != work_path:
            self._obsolete_files.append(chosen[0])   # запасной файл → рабочая копия, убрать после записи
            self._write_work()
        self._merge_legacy()

    def _load_unreadable(self, error: OSError) -> None:
        """Свой же EXE не прочитался (занят, сбой диска): данные в нём могут быть, просто сейчас
        недоступны. Писать в EXE в этой сессии нельзя — иначе запись отрезала бы настоящий хвост.
        Работаем с самой свежей копией (если есть), сохраняя её «родословную»; если копий нет,
        правки помечаются как сделанные «без основы» — в следующий раз они будут отложены с
        понятным сообщением, а не приняты за чужие или устаревшие."""
        self._exe_unreadable = f"не удалось прочитать программу: {error}"
        copies = [(p, d) for p in self._copy_paths() if (d := self._read_copy(p)) is not None]
        # самая свежая копия ЭТОГО ПК (рабочая или его же запасной файл): чужой копией рабочую
        # не подменяем, а устаревшую рабочую не берём поверх более свежего своего запасного файла
        mine = [c for c in copies if self._origin_of(c) == self._origin]
        chosen = (max(mine, key=lambda c: c[1]["rev"]) if mine
                  else (max(copies, key=lambda c: c[1]["rev"]) if copies else None))
        for c in mine:
            if c is not chosen and c[0] != self.work_file.path:
                self._obsolete_files.append(c[0])   # свои и старше выбранной — убрать после записи
        doc = chosen[1] if chosen else {"rev": 0, "settings": {}, "tasks": {}}
        self._doc = {"rev": _as_int(doc.get("rev")), "settings": _section(doc, "settings"),
                     "tasks": _section(doc, "tasks")}
        self._base_gen = doc.get("base_gen")
        self._pending_gen = doc.get("pending_gen")
        self._base_unknown = chosen is None or bool(doc.get("base_unknown"))
        self._embedded_rev = self._doc["rev"]
        if chosen is not None and chosen[0] != self.work_file.path:
            self._write_work()
        self.notices.append(f"Не удалось прочитать данные программы ({error}). Изменения этой сессии "
                            "будут сохранены на этом компьютере, но не внутри программы")

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
                self._migrated_files.append(path)   # удалить после записи в EXE
            else:
                # внутри уже есть свои данные (они сохранены в EXE или копии) — файл лишь
                # остаток прошлого переноса: убрать сразу
                _unlink_quietly(path)
        if changed:
            self._doc["rev"] += 1
            self._write_work()
        try:
            if not self._migrated_files:
                self.legacy_dir.rmdir()     # только если папка опустела
        except OSError:
            pass

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
        payload = dict(self._doc, base_gen=self._base_gen, pending_gen=self._pending_gen, origin=self._origin)
        if self._base_unknown:
            payload["base_unknown"] = True
        return payload

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
            if not self._exe_unreadable:    # EXE не прочитан — рабочая копия единственный источник
                self._drop_work()
            return True
        if self._exe_unreadable:
            self.last_error = self._exe_unreadable
            return self._write_failed()
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
            return self._write_failed()
        try:
            _replace_with_retry(embed, self.exe)
        except OSError as e:
            try:
                os.replace(old, self.exe)       # вернуть рабочий EXE на место
                _unlink_quietly(embed)
            except OSError:
                pass        # .embed не удаляем: если не вернулся и прежний EXE, в нём наши данные
            self.last_error = f"запись в программу: {e}"
            return self._write_failed()
        self._base_gen = gen
        self._pending_gen = None
        self._embedded_rev = self._doc["rev"]
        self._drop_work()
        self._drop_legacy()
        for path in self._obsolete_files:
            _unlink_quietly(path)
        self._obsolete_files = []
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

    def _write_failed(self) -> bool:
        """В EXE записать не удалось. Сохранять нечего (пустой список, настройки по умолчанию) —
        это не ошибка выхода; иначе данные кладутся в файл на диске, и выход считается неудачным."""
        if not self._doc["settings"] and not self._doc["tasks"]:
            return True
        self._save_fallback()
        return False

    def _save_fallback(self) -> None:
        """В EXE записать не удалось — убедиться, что данные сессии лежат хоть где-то на диске,
        и запомнить где (для сообщения пользователю)."""
        self.fallback_path = None
        if not self._doc["settings"] and not self._doc["tasks"]:
            return      # сохранять нечего
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
