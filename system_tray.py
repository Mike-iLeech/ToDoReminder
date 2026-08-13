from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from settings import SettingsManager


def make_app_icon() -> QIcon:
    """Единая иконка приложения: синий квадрат с галочкой."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#3B82F6"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawLine(14, 33, 26, 45)
    painter.drawLine(26, 45, 50, 18)
    painter.end()
    return QIcon(pix)


class SystemTray(QSystemTrayIcon):
    """Системный трей: меню, показ/скрытие окна, перемещение на основной экран, выход."""

    def __init__(self, settings_manager: SettingsManager, ctx) -> None:
        super().__init__(ctx.app)
        self._settings_manager = settings_manager
        self._ctx = ctx
        self.setIcon(make_app_icon())
        self.setToolTip("ToDo Reminder")

        menu = QMenu()
        act_open = menu.addAction("Открыть основное окно")
        act_move = menu.addAction("Переместить окно на основной экран")
        menu.addSeparator()
        act_quit = menu.addAction("Выход")

        act_open.triggered.connect(ctx.open_main_window)
        act_move.triggered.connect(ctx.move_to_primary_screen)
        act_quit.triggered.connect(ctx.quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self._settings_manager.s.tray_action_index == 0:
                self._ctx.open_main_window()