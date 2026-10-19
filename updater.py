"""Автообновление из GitHub Releases — без собственного сервера.

Логика без Qt (чтобы её можно было тестировать отдельно):
- fetch_latest() спрашивает GitHub API о последнем опубликованном релизе;
- download() качает EXE-ассет релиза, сверяя размер и SHA-256 (поле digest от GitHub);
- install_and_restart() подменяет работающий EXE новым и запускает его.

Работающий EXE в Windows нельзя удалить или перезаписать, но можно переименовать:
текущий файл уходит в ToDoReminder.exe.old, новый встаёт на его место, а .old
удаляет уже новая версия при запуске (cleanup_old).
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from version import APP_VERSION

REPO = "Mike-iLeech/ToDoReminder"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAME = "ToDoReminder.exe"
USER_AGENT = f"ToDoReminder/{APP_VERSION}"
CHUNK = 64 * 1024


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    asset_url: str
    asset_size: int
    sha256: str | None


def parse_version(text: str) -> tuple[int, ...]:
    """'v2.6.3.2' → (2, 6, 3, 2). Хвостовые нули не важны: 2.7 == 2.7.0.0."""
    m = re.search(r"\d+(?:\.\d+)*", text or "")
    if not m:
        return ()
    parts = [int(p) for p in m.group(0).split(".")]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def is_frozen() -> bool:
    """Обновлять на месте можно только собранный EXE; из исходников — git pull."""
    return bool(getattr(sys, "frozen", False))


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})


def parse_release(data: dict) -> ReleaseInfo | None:
    """Разбирает ответ /releases/latest. None — в релизе нет EXE-файла."""
    tag = str(data.get("tag_name") or "")
    assets = [a for a in data.get("assets") or [] if isinstance(a, dict)]
    asset = next((a for a in assets if str(a.get("name", "")).lower() == ASSET_NAME.lower()), None)
    if asset is None:
        asset = next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    if asset is None or not asset.get("browser_download_url"):
        return None
    digest = str(asset.get("digest") or "")
    sha256 = digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else None
    return ReleaseInfo(
        version=tag[1:] if tag[:1] in ("v", "V") else tag,
        tag=tag,
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or RELEASES_PAGE),
        asset_url=str(asset["browser_download_url"]),
        asset_size=int(asset.get("size") or 0),
        sha256=sha256,
    )


def fetch_latest(timeout: float = 15) -> ReleaseInfo | None:
    try:
        with urllib.request.urlopen(_request(API_LATEST, "application/vnd.github+json"), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # ни одного опубликованного релиза
        if e.code in (403, 429):
            raise UpdateError("GitHub временно ограничил число запросов. Попробуйте позже.") from e
        raise UpdateError(f"GitHub ответил ошибкой {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("Нет связи с GitHub. Проверьте подключение к интернету.") from e
    except ValueError as e:
        raise UpdateError("Не удалось разобрать ответ GitHub.") from e
    if not isinstance(data, dict):
        raise UpdateError("Не удалось разобрать ответ GitHub.")
    return parse_release(data)


def download(info: ReleaseInfo, dest: Path, progress=None, cancelled=None, timeout: float = 30) -> Path:
    """Качает EXE в dest (через dest.part), проверяет размер и SHA-256."""
    dest = Path(dest)
    if not info.sha256 and not info.asset_size:
        raise UpdateError("GitHub не сообщил ни размер, ни контрольную сумму файла — проверить его нельзя.")
    part = dest.with_name(dest.name + ".part")
    sha = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(_request(info.asset_url, "application/octet-stream"), timeout=timeout) as resp, \
                open(part, "wb") as f:
            try:
                total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            except ValueError:
                total = info.asset_size
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateCancelled("Загрузка отменена.")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        if info.asset_size and done != info.asset_size:
            raise UpdateError(f"Файл скачался не полностью ({done} из {info.asset_size} байт).")
        if info.sha256 and sha.hexdigest() != info.sha256:
            raise UpdateError("Контрольная сумма скачанного файла не совпала — обновление отменено.")
        os.replace(part, dest)
        return dest
    except UpdateError:
        _unlink_quietly(part)
        raise
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
        _unlink_quietly(part)
        raise UpdateError(f"Не удалось скачать обновление: {e}") from e


def discard(path: Path) -> None:
    """Удалить скачанный, но не установленный файл."""
    _unlink_quietly(path)


def _unlink_quietly(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def old_exe_path(exe: Path) -> Path:
    return exe.with_name(exe.name + ".old")


def download_path(exe: Path) -> Path:
    # рядом с EXE: тот же диск, поэтому подмена — атомарный rename
    return exe.with_name(exe.name + ".new")


def can_write_next_to(exe: Path) -> bool:
    probe = exe.with_name(f".{exe.name}.write-test")
    try:
        with open(probe, "wb"):
            pass
        probe.unlink()
        return True
    except OSError:
        return False


def _replace_with_retry(src: Path, dst: Path, attempts: int = 10, delay: float = 0.3) -> None:
    # антивирус может держать свежескачанный файл открытым долю секунды
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def swap_executables(exe: Path, new_exe: Path) -> None:
    """exe → exe.old, new_exe → exe. При сбое возвращает исходный EXE на место."""
    old = old_exe_path(exe)
    _unlink_quietly(old)
    _replace_with_retry(exe, old)
    try:
        _replace_with_retry(new_exe, exe)
    except OSError:
        os.replace(old, exe)
        raise


def clean_child_env() -> dict:
    """Окружение для запуска нового EXE как самостоятельного процесса.

    Onefile-загрузчик PyInstaller передаёт потомкам служебные переменные; без сброса
    новый EXE решил бы, что он дочерний процесс старого, и взял бы чужую папку _MEI.
    """
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("_PYI") and k.upper() != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def launch(exe: Path, args: list[str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), *args], cwd=str(exe.parent), env=clean_child_env(),
                     close_fds=True, creationflags=flags)


def install_and_restart(new_exe: Path, args: list[str]) -> None:
    """Ставит скачанный EXE на место текущего и запускает его. Вызывающий после этого
    должен сразу завершить приложение."""
    exe = current_exe()
    swap_executables(exe, Path(new_exe))
    try:
        launch(exe, args)
    except OSError:
        # новая версия не стартует — откатываемся, чтобы не остаться без рабочего EXE
        _unlink_quietly(exe.with_name(exe.name + ".failed"))
        os.replace(exe, exe.with_name(exe.name + ".failed"))
        os.replace(old_exe_path(exe), exe)
        raise


def cleanup_old() -> bool:
    """Удаляет остатки прошлого обновления. True — всё убрано (или нечего убирать)."""
    if not is_frozen():
        return True
    exe = current_exe()
    ok = True
    for leftover in (old_exe_path(exe), exe.with_name(exe.name + ".failed"),
                     download_path(exe), download_path(exe).with_name(download_path(exe).name + ".part"),
                     # недописанные копии при записи данных внутрь EXE (datastore)
                     exe.with_name(exe.name + ".embed"), exe.with_name(exe.name + ".embed.part"),
                     exe.with_name(exe.name + ".new.embed"), exe.with_name(exe.name + ".new.embed.part")):
        if leftover.exists():
            try:
                leftover.unlink()
            except OSError:
                ok = False  # старый процесс ещё не завершился — попробуем позже
    return ok
