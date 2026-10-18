from __future__ import annotations

from dataclasses import astuple, dataclass

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextOption
from PySide6.QtWidgets import QWidget

from models import Task, TaskStatus, status_color

TEXT_LEFT = 12            # отступ текста от левого края колонки (место под маркер статуса)
MEASURE_HEIGHT = 20000    # «бесконечная» высота прямоугольника при измерении переноса


@dataclass
class _Item:
    rect: QRectF
    height: int
    font: QFont
    color: QColor
    marker: QColor
    title: str


@dataclass
class _Layout:
    base_size: int
    col_bounds: list          # [(x0, inner_w)] по колонкам
    items: list               # [_Item]
    n_cols: int
    col_width: float


def _is_urgent(task: Task) -> bool:
    return task.urgent and task.status is not TaskStatus.DONE


def _title(task: Task) -> str:
    return ("⚡ " + task.title) if _is_urgent(task) else (task.title or " ")


class ReminderWindow(QWidget):
    """Полноэкранное уведомление с настраиваемым числом колонок по статусам.

    Показываются только активные задачи (Done скрыто, если настройка не включена).
    Задачи распределяются round-robin по колонкам своего статуса.
    Число колонок для To Do и Started настраивается отдельно в настройках.
    Шрифт адаптируется под количество задач, чтобы всё поместилось в высоту экрана.

    Раскладка (подбор размера шрифта и измерение переносов) считается один раз
    и кэшируется до смены задач, размера окна или настроек.
    """

    hiddenRequested = Signal()

    def __init__(self, settings, tasks, is_preview: bool = False) -> None:
        super().__init__(None)
        self._settings = settings
        self._tasks = list(tasks)
        self._tasks_version = 0
        self._layout_key = None
        self._layout: _Layout | None = None
        self._is_preview = is_preview
        flags = Qt.FramelessWindowHint | Qt.Tool
        if settings.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self._screen = None

    def set_tasks(self, tasks) -> None:
        self._tasks = list(tasks)
        self._tasks_version += 1
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

    # ------------------------------------------------------------------ fonts

    def _base_font(self, size: int) -> QFont:
        s = self._settings
        font = QFont(s.font_family)
        font.setPixelSize(size)
        if s.font_style_index in (1, 3):
            font.setWeight(QFont.Bold)
        if s.font_style_index in (2, 3):
            font.setItalic(True)
        return font

    def _fonts_for(self, size: int) -> dict:
        """Шрифты, которыми реально рисуются обычные, срочные и выполненные дела."""
        s = self._settings
        base = self._base_font(size)
        urgent = QFont(base)
        urgent.setPixelSize(size + s.urgent_fullscreen_size_delta)
        if s.urgent_fullscreen_style_index in (1, 3):
            urgent.setWeight(QFont.Bold)
        if s.urgent_fullscreen_style_index in (2, 3):
            urgent.setItalic(True)
        done = QFont(base)
        done.setStrikeOut(True)
        return {"base": base, "urgent": urgent, "done": done}

    @staticmethod
    def _font_kind(task: Task) -> str:
        if _is_urgent(task):
            return "urgent"
        if task.status is TaskStatus.DONE:
            return "done"
        return "base"

    # ------------------------------------------------------------------ layout

    def _columns(self) -> list[list[Task]]:
        s = self._settings

        def by_status(status):
            tasks = [t for t in self._tasks if t.status is status]
            tasks.sort(key=lambda t: (not t.urgent, t.position))
            return tasks

        def round_robin(tasks, n_cols):
            cols = [[] for _ in range(max(1, n_cols))]
            for i, t in enumerate(tasks):
                cols[i % len(cols)].append(t)
            return cols

        columns = round_robin(by_status(TaskStatus.TO_DO), getattr(s, "fullscreen_columns_todo", 2))
        columns += round_robin(by_status(TaskStatus.STARTED), getattr(s, "fullscreen_columns_started", 2))
        done = by_status(TaskStatus.DONE)
        if s.show_done_in_fullscreen and done:
            columns += round_robin(done, getattr(s, "fullscreen_columns_done", 2))
        return columns

    def _col_bounds(self, n_cols: int) -> list[tuple[int, int]]:
        w = self.width()
        col_width = w / n_cols
        pad = max(8, int(w * 0.02))
        bounds = []
        for ci in range(n_cols):
            x0 = int(ci * col_width) + pad
            x1 = int((ci + 1) * col_width) - pad
            bounds.append((x0, max(10, x1 - x0 - TEXT_LEFT)))
        return bounds

    def _fits(self, columns, bounds, size: int) -> bool:
        """Влезают ли все колонки при данном размере шрифта: ни одно слово не шире
        колонки и суммарная высота с переносами не выше экрана."""
        metrics = {kind: QFontMetrics(f) for kind, f in self._fonts_for(size).items()}
        flags = self._align_flags() | Qt.TextWordWrap
        gap = max(8, size // 3)
        h = self.height()
        for col, (_, inner_w) in zip(columns, bounds):
            if not col:
                continue
            total = int(size * 0.5)
            for task in col:
                fm = metrics[self._font_kind(task)]
                title = _title(task)
                for word in title.split():
                    if fm.horizontalAdvance(word) > inner_w:
                        return False
                total += fm.boundingRect(QRect(0, 0, inner_w, MEASURE_HEIGHT), flags, title).height() + gap
                if total - gap > h:
                    return False
        return True

    def _adaptive_font_size(self, columns, bounds) -> int:
        base_size = self._settings.text_size
        if self._fits(columns, bounds, base_size):
            return base_size
        min_size = getattr(self._settings, "fullscreen_min_font_size", 14)
        lo, hi = min_size, base_size
        best = min_size
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._fits(columns, bounds, mid):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _compute_layout(self) -> _Layout | None:
        columns = self._columns()
        if not any(columns):
            return None
        s = self._settings
        n_cols = len(columns)
        bounds = self._col_bounds(n_cols)
        size = self._adaptive_font_size(columns, bounds)
        fonts = self._fonts_for(size)
        metrics = {kind: QFontMetrics(f) for kind, f in fonts.items()}
        flags = self._align_flags() | Qt.TextWordWrap
        text_color = QColor(s.text_color)
        urgent_color = QColor(s.urgent_fullscreen_color)
        markers = {st: QColor(status_color(st, s)) for st in TaskStatus}
        gap = max(8, size // 3)

        items = []
        for col, (x0, inner_w) in zip(columns, bounds):
            y = int(size * 0.5)
            for task in col:
                kind = self._font_kind(task)
                title = _title(task)
                height = metrics[kind].boundingRect(QRect(x0 + TEXT_LEFT, y, inner_w, MEASURE_HEIGHT), flags, title).height()
                if kind == "done":
                    color = text_color.darker(160)
                elif kind == "urgent":
                    color = urgent_color
                else:
                    color = text_color
                items.append(_Item(QRectF(x0 + TEXT_LEFT, y, inner_w, MEASURE_HEIGHT), height,
                                   fonts[kind], color, markers[task.status], title))
                y += height + gap
        return _Layout(size, bounds, items, n_cols, self.width() / n_cols)

    def _current_layout(self) -> _Layout | None:
        key = (self.width(), self.height(), self._tasks_version, astuple(self._settings))
        if key != self._layout_key:
            self._layout = self._compute_layout()
            self._layout_key = key
        return self._layout

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        bg_hex, fg_hex = self._effective_colors()
        painter.fillRect(self.rect(), QColor(bg_hex))

        layout = self._current_layout()
        if layout is None:
            self._paint_empty(painter, w, h)
            return

        # Разделительные линии 3px между колонками
        line_color = QColor(fg_hex)
        for ci in range(1, layout.n_cols):
            x = int(ci * layout.col_width) - 1
            painter.fillRect(QRect(x, 0, 3, h), line_color)

        flags = self._align_flags() | Qt.TextWordWrap
        for item in layout.items:
            painter.setFont(item.font)
            painter.setPen(item.color)
            painter.drawText(item.rect, flags, item.title)

            # Визуальный статус — цветной маркер слева от названия
            painter.setPen(Qt.NoPen)
            painter.setBrush(item.marker)
            painter.drawRoundedRect(QRectF(item.rect.x() - TEXT_LEFT, item.rect.y() + 4, 6, max(6, item.height - 8)), 2, 2)
            painter.setBrush(Qt.NoBrush)

    def _paint_empty(self, painter, w: int, h: int) -> None:
        message = "Вы не добавили ни одного дела в список"
        s = self._settings
        painter.setFont(self._base_font(s.text_size))
        _, fg_hex = self._effective_colors()
        painter.setPen(QColor(fg_hex))
        rect = QRectF(0, 0, w, h)
        fmt = QTextOption(Qt.AlignCenter)
        fmt.setWrapMode(QTextOption.WordWrap)
        painter.drawText(rect, message, fmt)

    def _align_flags(self) -> Qt.AlignmentFlag:
        alignments = [Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight]
        return alignments[self._settings.alignment_index % len(alignments)]
