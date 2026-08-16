from __future__ import annotations

import math

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QTextOption
from PySide6.QtWidgets import QWidget

from models import Task, TaskStatus, status_color


class ReminderWindow(QWidget):
    """Полноэкранное уведомление с настраиваемым числом колонок по статусам.

    Показываются только активные задачи (Done скрыто, если настройка не включена).
    Задачи распределяются round-robin по колонкам своего статуса.
    Число колонок для To Do и Started настраивается отдельно в настройках.
    Шрифт адаптируется под количество задач, чтобы всё поместилось в высоту экрана.
    """

    hiddenRequested = Signal()

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

    # ------------------------------------------------------------------ helpers

    def _distribute_round_robin(self, tasks: list, n_cols: int) -> list[list]:
        """Распределяет задачи по n_cols колонкам round-robin."""
        cols: list[list] = [[] for _ in range(n_cols)]
        for i, t in enumerate(tasks):
            cols[i % n_cols].append(t)
        return cols

    def _measure_column_height(self, painter, col_tasks: list[Task], font_size: int, col_width: float) -> int:
        """Измеряет фактическую высоту колонки с учётом word-wrap и срочных задач."""
        s = self._settings
        base_font = QFont(s.font_family)
        base_font.setPixelSize(font_size)
        if s.font_style_index in (1, 3):
            base_font.setWeight(QFont.Bold)
        if s.font_style_index in (2, 3):
            base_font.setItalic(True)

        urgent_delta = s.urgent_fullscreen_size_delta
        gap = max(8, font_size // 3)
        margin_top = int(font_size * 0.5)
        pad = max(8, int(self.width() * 0.02))
        inner_w = max(10, int(col_width) - 2 * pad - 12)
        align_flags = self._align_flags()

        total_h = margin_top
        for task in col_tasks:
            if task.urgent and task.status is not TaskStatus.DONE:
                size = font_size + urgent_delta
            else:
                size = font_size
            f = QFont(base_font)
            f.setPixelSize(size)
            painter.setFont(f)
            fm = painter.fontMetrics()
            title = ("⚡ " + task.title) if (task.urgent and task.status is not TaskStatus.DONE) else (task.title or " ")
            rect = QRectF(0, 0, inner_w, 20000)
            h = fm.boundingRect(rect.toRect(), align_flags | Qt.TextWordWrap, title).height()
            total_h += h + gap
        return total_h - gap if col_tasks else margin_top

    def _max_word_width(self, painter, columns: list[list[Task]], font_size: int) -> int:
        """Возвращает ширину самого широкого слова среди всех задач (с учётом срочных)."""
        s = self._settings
        base_font = QFont(s.font_family)
        if s.font_style_index in (1, 3):
            base_font.setWeight(QFont.Bold)
        if s.font_style_index in (2, 3):
            base_font.setItalic(True)
        urgent_delta = s.urgent_fullscreen_size_delta

        max_w = 0
        for col in columns:
            for task in col:
                size = font_size + urgent_delta if (task.urgent and task.status is not TaskStatus.DONE) else font_size
                f = QFont(base_font)
                f.setPixelSize(size)
                painter.setFont(f)
                fm = painter.fontMetrics()
                title = ("⚡ " + task.title) if (task.urgent and task.status is not TaskStatus.DONE) else (task.title or "")
                for word in title.split():
                    w = fm.horizontalAdvance(word)
                    if w > max_w:
                        max_w = w
        return max_w

    def _calc_adaptive_font_size(self, painter, columns: list[list[Task]], base_size: int) -> int:
        """Рассчитывает размер шрифта чтобы все колонки поместились в высоту и ширину экрана."""
        h = self.height()
        n_cols = len(columns)
        col_width = w / n_cols if (w := self.width()) else 100.0
        pad = max(8, int(self.width() * 0.02))
        inner_w = max(10, int(col_width) - 2 * pad - 12)

        def fits(size: int) -> bool:
            # Проверка ширины: ни одно слово не должно быть шире колонки
            if self._max_word_width(painter, columns, size) > inner_w:
                return False
            # Проверка высоты
            for col in columns:
                if not col:
                    continue
                measured = self._measure_column_height(painter, col, size, col_width)
                if measured > h:
                    return False
            return True

        if fits(base_size):
            return base_size

        min_size = getattr(self._settings, "fullscreen_min_font_size", 14)
        lo, hi = min_size, base_size
        best = min_size
        while lo <= hi:
            mid = (lo + hi) // 2
            if fits(mid):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _apply_urgent_style(self, font: QFont, task: Task, base_size: int) -> tuple[QFont, QColor]:
        """Применяет стиль срочной задачи. Возвращает (font, color)."""
        s = self._settings
        if task.urgent and task.status is not TaskStatus.DONE:
            f = QFont(font)
            delta = s.urgent_fullscreen_size_delta
            style_idx = s.urgent_fullscreen_style_index
            f.setPixelSize(base_size + delta)
            if style_idx in (1, 3):
                f.setWeight(QFont.Bold)
            if style_idx in (2, 3):
                f.setItalic(True)
            return f, QColor(s.urgent_fullscreen_color)
        if task.status is TaskStatus.DONE:
            f = QFont(font)
            f.setStrikeOut(True)
            return f, None
        return font, None

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event) -> None:
        s = self._settings
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        bg_hex, fg_hex = self._effective_colors()
        painter.fillRect(self.rect(), QColor(bg_hex))

        text_color = QColor(fg_hex)

        # Собираем задачи по статусам
        todo_tasks = [t for t in self._tasks if t.status is TaskStatus.TO_DO]
        started_tasks = [t for t in self._tasks if t.status is TaskStatus.STARTED]
        done_tasks = [t for t in self._tasks if t.status is TaskStatus.DONE]

        todo_tasks.sort(key=lambda t: (not t.urgent, t.position))
        started_tasks.sort(key=lambda t: (not t.urgent, t.position))
        done_tasks.sort(key=lambda t: (not t.urgent, t.position))

        # Определяем колонки (число колонок настраивается отдельно для каждого статуса)
        columns: list[list[Task]] = []
        n_todo_cols = max(1, getattr(s, "fullscreen_columns_todo", 2))
        n_started_cols = max(1, getattr(s, "fullscreen_columns_started", 2))
        for col in self._distribute_round_robin(todo_tasks, n_todo_cols):
            columns.append(col)
        for col in self._distribute_round_robin(started_tasks, n_started_cols):
            columns.append(col)

        show_done = s.show_done_in_fullscreen and len(done_tasks) > 0
        if show_done:
            for col in self._distribute_round_robin(done_tasks, n_todo_cols):
                columns.append(col)

        shown_total = sum(len(c) for c in columns)
        if shown_total == 0:
            self._paint_empty(painter, w, h)
            return

        n_cols = len(columns)
        col_width = w / n_cols

        # Адаптивный размер шрифта: измеряем фактическую высоту каждой колонки
        base_size = self._calc_adaptive_font_size(painter, columns, s.text_size)

        font = QFont(s.font_family)
        font.setPixelSize(base_size)
        if s.font_style_index == 1:
            font.setWeight(QFont.Bold)
        elif s.font_style_index == 3:
            font.setWeight(QFont.Bold)
            font.setItalic(True)
        elif s.font_style_index == 2:
            font.setItalic(True)

        # Разделительные линии 3px между колонками
        line_color = text_color
        for ci in range(1, n_cols):
            x = int(ci * col_width) - 1
            painter.fillRect(QRect(x, 0, 3, h), line_color)

        pad = max(8, int(w * 0.02))
        align_flags = self._align_flags()

        for ci, col_tasks in enumerate(columns):
            x0 = int(ci * col_width) + pad
            x1 = int((ci + 1) * col_width) - pad
            inner_w = max(10, x1 - x0 - 12)
            y = int(base_size * 0.5)

            for task in col_tasks:
                task_font, special_color = self._apply_urgent_style(font, task, base_size)
                if task.status is TaskStatus.DONE:
                    painter.setFont(task_font)
                    task_color = text_color.darker(160)
                else:
                    painter.setFont(task_font)
                    task_color = special_color if special_color else text_color

                title = ("⚡ " + task.title) if (task.urgent and task.status is not TaskStatus.DONE) else (task.title or " ")
                rect = QRectF(x0 + 12, y, inner_w, 20000)
                fmt = QTextOption(align_flags)
                fmt.setWrapMode(QTextOption.WordWrap)
                fm = painter.fontMetrics()
                height = fm.boundingRect(rect.toRect(), align_flags | Qt.TextWordWrap, title).height()

                painter.setPen(task_color)
                painter.drawText(rect, align_flags | Qt.TextWordWrap, title)

                # Визуальный статус — цветной маркер слева от названия
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(status_color(task.status, self._settings)))
                painter.drawRoundedRect(QRectF(x0, y + 4, 6, max(6, height - 8)), 2, 2)
                painter.setBrush(Qt.NoBrush)

                gap = max(8, base_size // 3)
                y += height + gap

    def _paint_empty(self, painter, w: int, h: int) -> None:
        message = "Вы не добавили ни одного дела в список"
        s = self._settings
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
        painter.setPen(QColor(fg_hex))
        rect = QRectF(0, 0, w, h)
        fmt = QTextOption(Qt.AlignCenter)
        fmt.setWrapMode(QTextOption.WordWrap)
        painter.drawText(rect, message, fmt)

    def _align_flags(self) -> Qt.AlignmentFlag:
        alignments = [Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight]
        return alignments[self._settings.alignment_index % len(alignments)]
