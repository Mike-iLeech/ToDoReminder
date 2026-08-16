from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QTextOption
from PySide6.QtWidgets import QWidget

from models import Task, TaskStatus, status_color


class ReminderWindow(QWidget):
    """Полноэкранное уведомление с колонками статусов.

    Показываются только активные задачи (Done скрыто, если настройка не включена).
    Порядок внутри каждой колонки совпадает с порядком в главном списке.
    """

    hiddenRequested = Signal()

    STATUS_ORDER = [TaskStatus.TO_DO, TaskStatus.STARTED]

    def __init__(self, settings, tasks, is_preview: bool = False) -> None:
        super().__init__(None)
        self._settings = settings
        self._tasks = list(tasks)
        self._is_preview = is_preview
        flags = Qt.FramelessWindowHint | Qt.Tool
        if settings.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self._screen = None

    def set_tasks(self, tasks) -> None:
        self._tasks = list(tasks)
        self.update()

    def set_always_on_top(self, enabled: bool) -> None:
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if self.isFullScreen():
            self.showFullScreen()
        self.raise_()

    def attach_to_screen(self, screen) -> None:
        self._screen = screen
        self.setGeometry(screen.geometry())
        s = self._settings
        self.setWindowOpacity(max(0.0, min(1.0, 1.0 - s.opacity_percent / 100.0)))
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ events

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Escape):
            self._hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        self._hide()
        event.accept()

    def _hide(self) -> None:
        self.hide()
        self.deleteLater()
        self.hiddenRequested.emit()

    def _effective_colors(self):
        """Цвета полноэкранного напоминания всегда берутся из настроек (в любой теме)."""
        return self._settings.bg_color, self._settings.text_color

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event) -> None:
        s = self._settings
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        bg_hex, fg_hex = self._effective_colors()
        painter.fillRect(self.rect(), QColor(bg_hex))

        font = QFont(s.font_family)
        font.setPixelSize(s.text_size)
        if s.font_style_index == 1:
            font.setWeight(QFont.Bold)
        elif s.font_style_index == 3:
            font.setWeight(QFont.Bold)
            font.setItalic(True)
        elif s.font_style_index == 2:
            font.setItalic(True)
        painter.setFont(font)

        _, fg_hex = self._effective_colors()
        text_color = QColor(fg_hex)

        statuses = list(self.STATUS_ORDER)
        if s.show_done_in_fullscreen and TaskStatus.DONE not in statuses:
            statuses.append(TaskStatus.DONE)
        column_map = {}
        for st in statuses:
            col_tasks = [t for t in self._tasks if t.status is st]
            col_tasks.sort(key=lambda t: (not t.urgent, t.position))
            column_map[st] = col_tasks

        shown_total = sum(len(v) for v in column_map.values())

        if shown_total == 0:
            self._paint_empty(painter, font, text_color, w, h)
            return

        n_cols = len(statuses)
        col_width = w / n_cols
        line_color = text_color

        # разделительные линии 3 px между колонками
        for ci in range(1, n_cols):
            x = int(ci * col_width) - 1
            painter.fillRect(QRect(x, 0, 3, h), line_color)

        pad = max(8, int(w * 0.02))
        for ci, st in enumerate(statuses):
            x0 = int(ci * col_width) + pad
            x1 = int((ci + 1) * col_width) - pad
            inner_w = x1 - x0 - 12
            y = self.text_size_margin()
            for task in column_map[st]:
                base_font = QFont(font)
                if task.urgent and task.status is not TaskStatus.DONE:
                    delta = s.urgent_fullscreen_size_delta
                    style_idx = s.urgent_fullscreen_style_index
                    base_font.setPixelSize(s.text_size + delta)
                    if style_idx in (1, 3):
                        base_font.setWeight(QFont.Bold)
                    if style_idx in (2, 3):
                        base_font.setItalic(True)
                if task.status is TaskStatus.DONE:
                    base_font.setStrikeOut(True)
                    painter.setFont(base_font)
                    task_color = text_color.darker(160)
                else:
                    painter.setFont(base_font)
                    if task.urgent and task.status is not TaskStatus.DONE:
                        task_color = QColor(s.urgent_fullscreen_color)
                    else:
                        task_color = text_color
                title = ("⚡ " + task.title) if (task.urgent and task.status is not TaskStatus.DONE) else (task.title or " ")
                rect = QRectF(x0 + 12, y, max(10, inner_w), 20000)
                flags = self._align_flags()
                fmt = QTextOption(flags)
                fmt.setWrapMode(QTextOption.WordWrap)  # перенос по словам
                fm = painter.fontMetrics()
                height = fm.boundingRect(rect.toRect(), flags | Qt.TextWordWrap, title).height()
                painter.setPen(task_color)
                painter.drawText(rect, flags | Qt.TextWordWrap, title)
                # визуальный статус — цветной маркер слева от названия
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(status_color(task.status, self._settings)))
                painter.drawRoundedRect(QRectF(x0, y + 4, 6, max(6, height - 8)), 2, 2)
                painter.setBrush(Qt.NoBrush)
                y += height + self.text_gap()

    def _paint_empty(self, painter, font, text_color, w, h) -> None:
        message = "Вы не добавили ни одного дела в список"
        painter.setPen(text_color)
        painter.setFont(font)
        rect = QRectF(0, 0, w, h)
        fmt = QTextOption(Qt.AlignCenter)
        fmt.setWrapMode(QTextOption.WordWrap)
        painter.drawText(rect, message, fmt)

    def text_size_margin(self) -> int:
        return int(self._settings.text_size * 0.5)

    def text_gap(self) -> int:
        return max(8, self._settings.text_size // 3)

    def _align_flags(self) -> Qt.AlignmentFlag:
        alignments = [Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight]
        return alignments[self._settings.alignment_index % len(alignments)]