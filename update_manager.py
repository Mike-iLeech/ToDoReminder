"""Qt-часть автообновления: фоновая проверка, диалог новой версии, загрузка с прогрессом."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSystemTrayIcon,
    QTextBrowser,
    QVBoxLayout,
)

import updater
from theme import build_stylesheet
from version import APP_VERSION

FIRST_CHECK_DELAY_MS = 20_000              # после запуска — не мешать старту
PERIODIC_CHECK_MS = 6 * 60 * 60 * 1000     # приложение живёт в трее неделями
CLEANUP_RETRY_MS = 3_000


def _safe_emit(signal, *args) -> None:
    """emit из рабочего потока; после выхода из программы мост удалён — молча пропускаем."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


class _Bridge(QObject):
    """Сигналы из рабочего потока в GUI-поток (queued-соединение)."""

    checked = Signal(object, bool)      # ReleaseInfo | None, silent
    check_failed = Signal(str, bool)    # текст ошибки, silent
    progress = Signal(int, int)
    downloaded = Signal(object)         # Path
    download_failed = Signal(str)


class UpdateManager(QObject):
    def __init__(self, ctx) -> None:
        super().__init__()
        self._ctx = ctx
        self._bridge = _Bridge(self)
        self._bridge.checked.connect(self._on_checked)
        self._bridge.check_failed.connect(self._on_check_failed)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.downloaded.connect(self._on_downloaded)
        self._bridge.download_failed.connect(self._on_download_failed)
        self._checking = False
        self._manual_pending = False
        self._dialog = None
        self._progress_dlg = None
        self._cancel = threading.Event()
        self._downloading = False
        self._closing = False
        self._modal_messages = 0

        self._first = QTimer(self)
        self._first.setSingleShot(True)
        self._first.setInterval(FIRST_CHECK_DELAY_MS)
        self._first.timeout.connect(self._auto_check)
        self._periodic = QTimer(self)
        self._periodic.setInterval(PERIODIC_CHECK_MS)
        self._periodic.timeout.connect(self._auto_check)
        self._cleanup_tries = 0
        self._cleanup = QTimer(self)
        self._cleanup.setInterval(CLEANUP_RETRY_MS)
        self._cleanup.timeout.connect(self._cleanup_old)

    def start(self) -> None:
        if not updater.cleanup_old():
            # прошлая версия ещё завершается и держит свой .old — повторим чуть позже
            self._cleanup.start()
        self._first.start()
        self._periodic.start()

    def shutdown(self) -> None:
        """Выход из программы: остановить таймеры и прервать идущую загрузку."""
        self._closing = True
        self._first.stop()
        self._periodic.stop()
        self._cleanup.stop()
        self._cancel.set()

    @property
    def blocks_reminders(self) -> bool:
        """Открыто модальное окно обновления (загрузка или сообщение). Полноэкранное
        напоминание поверх всех окон оказалось бы под его блокировкой и не закрывалось
        бы кликом, поэтому его стоит отложить."""
        return self._downloading or self._modal_messages > 0

    def _cleanup_old(self) -> None:
        self._cleanup_tries += 1
        if updater.cleanup_old() or self._cleanup_tries >= 20:
            self._cleanup.stop()

    # ------------------------------------------------------------------ check

    def _auto_check(self) -> None:
        if self._ctx.settings_manager.s.auto_update_check:
            self.check(silent=True)

    def check(self, silent: bool = False) -> None:
        if self._downloading:
            # во время загрузки — без модальных окон: её завершение закрывает прогресс
            if not silent and self._ctx.tray is not None:
                self._ctx.tray.showMessage("ToDo Reminder", "Обновление уже загружается.",
                                           QSystemTrayIcon.Information, 4000)
            return
        if self._checking:
            # ручной запрос во время фоновой проверки: результат покажем как для ручного
            self._manual_pending = self._manual_pending or not silent
            return
        self._checking = True
        self._manual_pending = False

        bridge = self._bridge

        def work():
            try:
                info = updater.fetch_latest()
            except updater.UpdateError as e:
                _safe_emit(bridge.check_failed, str(e), silent)
            except Exception as e:  # noqa: BLE001 — сеть не должна ронять приложение
                _safe_emit(bridge.check_failed, f"Ошибка проверки обновлений: {e}", silent)
            else:
                _safe_emit(bridge.checked, info, silent)

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _on_check_failed(self, message: str, silent: bool) -> None:
        self._checking = False
        silent = silent and not self._manual_pending
        if not silent and not self._downloading and not self._closing:
            self._message(QMessageBox.Warning, message)

    def _on_checked(self, info, silent: bool) -> None:
        self._checking = False
        silent = silent and not self._manual_pending
        if self._downloading or self._closing:
            return  # проверка вернулась во время загрузки или уже при выходе из программы
        s = self._ctx.settings_manager.s
        if info is None or not updater.is_newer(info.version):
            if not silent:
                self._message(QMessageBox.Information, f"У вас последняя версия ({APP_VERSION}).")
            return
        if silent and s.update_skip_version and updater.parse_version(s.update_skip_version) == updater.parse_version(info.version):
            return
        if silent and self._ctx.tray is not None:
            self._ctx.tray.showMessage("ToDo Reminder", f"Доступна новая версия {info.version}",
                                       QSystemTrayIcon.Information, 8000)
        self._show_offer(info, silent)

    # ------------------------------------------------------------------ dialog

    # Все окна обновления — верхнего уровня, без родителя. С родителем-главным окном
    # их блокировали бы «Настройки» (WindowModal), а с родителем-модальным диалогом они
    # умирали бы вместе с ним (и падали, если он удалялся во время их exec()).

    def _styled(self, widget) -> None:
        widget.setStyleSheet(build_stylesheet(self._ctx.settings_manager.s.theme))

    def _message(self, icon, text: str, title: str = "Обновления") -> None:
        box = QMessageBox(icon, title, text)
        self._styled(box)
        self._modal_messages += 1
        try:
            box.exec()
        finally:
            self._modal_messages -= 1

    def _show_offer(self, info, silent: bool = False) -> None:
        if self._dialog is not None:
            if silent and getattr(self._dialog, "release_version", None) == info.version:
                return  # фоновая проверка не пересоздаёт уже открытое окно и не крадёт фокус
            self._dialog.close()
        dlg = QDialog(None)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowTitle("Доступно обновление")
        dlg.resize(460, 420)
        self._styled(dlg)
        lay = QVBoxLayout(dlg)
        head = QLabel(f"<b>Доступна версия {info.version}</b> — у вас {APP_VERSION}.")
        head.setTextFormat(Qt.RichText)
        lay.addWidget(head)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes.strip() or "_Описание изменений не указано._")
        lay.addWidget(notes, 1)

        row = QHBoxLayout()
        skip_btn = QPushButton("Пропустить версию")
        later_btn = QPushButton("Позже")
        if updater.is_frozen():
            go_btn = QPushButton("Обновить сейчас")
            go_btn.clicked.connect(lambda: (dlg.close(), self._start_download(info)))
        else:
            # запуск из исходников: подменять нечего, обновляются через git pull
            go_btn = QPushButton("Открыть страницу релиза")
            go_btn.clicked.connect(lambda: (dlg.close(), QDesktopServices.openUrl(QUrl(info.page_url))))
        go_btn.setProperty("accent", True)
        skip_btn.clicked.connect(lambda: (self._skip(info), dlg.close()))
        later_btn.clicked.connect(dlg.close)
        row.addWidget(skip_btn)
        row.addStretch(1)
        row.addWidget(later_btn)
        row.addWidget(go_btn)
        lay.addLayout(row)
        dlg.release_version = info.version
        # обнулять ссылку только если умирает именно текущее окно, а не закрытое ранее
        dlg.destroyed.connect(lambda *_, d=dlg: self._forget_dialog(d))
        self._dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _forget_dialog(self, dlg) -> None:
        if self._dialog is dlg:
            self._dialog = None

    def _skip(self, info) -> None:
        self._ctx.settings_manager.s.update_skip_version = info.version
        self._ctx.settings_manager.save()

    # ------------------------------------------------------------------ download

    def _start_download(self, info) -> None:
        if self._downloading:
            return
        exe = updater.current_exe()
        if not updater.can_write_next_to(exe):
            box = QMessageBox(QMessageBox.Warning, "Обновление",
                              f"Нет прав на запись в папку программы:\n{exe.parent}\n\n"
                              "Скачайте новую версию со страницы релиза вручную.")
            self._styled(box)
            open_btn = box.addButton("Открыть страницу релиза", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Close)
            self._modal_messages += 1
            try:
                box.exec()
            finally:
                self._modal_messages -= 1
            if box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl(info.page_url))
            return
        self._downloading = True
        self._cancel.clear()
        dlg = QProgressDialog("Загрузка обновления…", "Отмена", 0, 100, None)
        self._styled(dlg)
        dlg.setWindowTitle(f"Обновление до {info.version}")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(self._cancel.set)
        dlg.setValue(0)
        dlg.show()
        self._progress_dlg = dlg
        dest = updater.download_path(exe)

        bridge = self._bridge
        emit = _safe_emit

        def work():
            try:
                path = updater.download(info, dest, progress=lambda d, t: emit(bridge.progress, d, t),
                                        cancelled=self._cancel.is_set)
            except updater.UpdateCancelled:
                emit(bridge.download_failed, "")
            except updater.UpdateError as e:
                emit(bridge.download_failed, str(e))
            except Exception as e:  # noqa: BLE001
                emit(bridge.download_failed, f"Не удалось скачать обновление: {e}")
            else:
                emit(bridge.downloaded, path)

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress_dlg is None:
            return
        if total > 0:
            self._progress_dlg.setValue(min(100, done * 100 // total))
            self._progress_dlg.setLabelText(f"Загрузка обновления… {done / 1048576:.1f} из {total / 1048576:.1f} МБ")

    def _close_progress(self) -> None:
        self._downloading = False
        if self._progress_dlg is not None:
            self._progress_dlg.close()
            self._progress_dlg.deleteLater()
            self._progress_dlg = None

    def _on_download_failed(self, message: str) -> None:
        self._close_progress()
        if message:
            self._message(QMessageBox.Warning, message, "Обновление")

    def _on_downloaded(self, path) -> None:
        # «Отмена» могла прийти после последнего чанка; проверяем до закрытия прогресса,
        # потому что close() у QProgressDialog сам испускает canceled
        cancelled = self._cancel.is_set()
        self._close_progress()
        if cancelled:
            updater.discard(path)
            return
        mw = self._ctx.main_window
        args = ["--updated"]
        if mw is None or not mw.isVisible():
            args.append("--hide")
        self._ctx.save_all()
        try:
            updater.install_and_restart(path, args)
        except OSError as e:
            self._message(QMessageBox.Critical,
                          f"Не удалось установить обновление: {e}\nПрограмма продолжит работу в текущей версии.",
                          "Обновление")
            return
        # всё уже сохранено, новая версия запущена — выходим, не трогая файлы данных
        self._ctx.quit(save=False)
