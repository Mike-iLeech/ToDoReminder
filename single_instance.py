"""Защита от повторного запуска.

Исключительность держит QLockFile во временной папке пользователя (если процесс упал,
Qt распознаёт «осиротевшую» блокировку по PID и снимает её). Второй экземпляр через
локальный канал (QLocalSocket) просит первый показать главное окно и сразу выходит.
"""
from __future__ import annotations

import getpass
import hashlib
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ACTIVATE = b"activate"


def _key(name: str) -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = ""
    return f"{name}-" + hashlib.sha1(user.lower().encode("utf-8")).hexdigest()[:12]


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, name: str = "ToDoReminder", lock_dir: str | None = None) -> None:
        super().__init__()
        self._key = _key(name)
        directory = Path(lock_dir) if lock_dir else Path(QDir.tempPath())
        self._lock = QLockFile(str(directory / f"{self._key}.lock"))
        self._lock.setStaleLockTime(0)  # только проверка «жив ли владелец», без таймаута по времени
        self._server = None

    def acquire(self, wait_ms: int = 0) -> bool:
        """True — мы единственный экземпляр. wait_ms — сколько ждать, пока прежний завершится."""
        if not self._lock.tryLock(wait_ms):
            return False
        QLocalServer.removeServer(self._key)  # канал от упавшего процесса
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(self._key)
        return True

    def activate_existing(self, timeout_ms: int = 1500) -> bool:
        """Попросить уже запущенный экземпляр показать окно."""
        sock = QLocalSocket()
        sock.connectToServer(self._key)
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(ACTIVATE)
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._on_ready(c))
            conn.disconnected.connect(conn.deleteLater)
            if conn.bytesAvailable():
                self._on_ready(conn)

    def _on_ready(self, conn) -> None:
        if ACTIVATE in bytes(conn.readAll()):
            self.activated.emit()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()
