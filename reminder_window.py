from __future__ import annotations

from dataclasses import astuple, dataclass

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextOption
from PySide6.QtWidgets import QWidget

from models import Task, TaskStatus, status_color

TEXT_LEFT = 12            # отступ текста от левого края колонки (место под маркер статуса)
MEASURE_HEIGHT = 20000    # «бесконечная» высота прямоугольника при измерении переноса
MAX_TOTAL_COLUMNS = 12    # общий предел колонок (тот же, что в настройках)


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
        self._note = None          # текст служебной строки внизу, под которую резервируется место
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

    def _by_status(self, status) -> list[Task]:
        tasks = [t for t in self._tasks if t.status is status]
        tasks.sort(key=lambda t: (not t.urgent, t.position))
        return tasks

    def _configured_counts(self) -> dict:
        s = self._settings
        return {
            TaskStatus.TO_DO: max(1, getattr(s, "fullscreen_columns_todo", 2)),
            TaskStatus.STARTED: max(1, getattr(s, "fullscreen_columns_started", 2)),
            TaskStatus.DONE: max(1, getattr(s, "fullscreen_columns_done", 2)),
        }

    def _columns(self, counts: dict | None = None, include_done: bool | None = None) -> list[list[Task]]:
        s = self._settings
        counts = counts or self._configured_counts()
        if include_done is None:
            include_done = s.show_done_in_fullscreen

        def round_robin(tasks, n_cols):
            cols = [[] for _ in range(max(1, n_cols))]
            for i, t in enumerate(tasks):
                cols[i % len(cols)].append(t)
            return cols

        columns = round_robin(self._by_status(TaskStatus.TO_DO), counts[TaskStatus.TO_DO])
        columns += round_robin(self._by_status(TaskStatus.STARTED), counts[TaskStatus.STARTED])
        done = self._by_status(TaskStatus.DONE)
        if include_done and done:
            columns += round_robin(done, counts[TaskStatus.DONE])
        return columns

    def _fit_plan(self):
        """Колонки, их границы и размер шрифта, при которых список помещается на экран.

        Сначала шрифт уменьшается до минимального (как раньше). Если дела не влезают и так
        (issue #1), то по очереди: скрываются выполненные, затем статусам с самыми длинными
        колонками добавляются колонки (всего не больше MAX_TOTAL_COLUMNS). Если не помогло
        и это — берётся вариант, скрывающий меньше всего активных дел, а не влезающие дела
        сворачиваются в «… и ещё N».

        Эскалация запускается только нехваткой ВЫСОТЫ: слишком длинное слово (ссылка и т.п.)
        лишь уменьшает шрифт, как и раньше, — лишние колонки его только сужают.
        Выполненные скрываются, только если есть активные дела.

        Возвращает (колонки, границы, размер шрифта, сколько выполненных убрано с экрана) —
        последнее число показывается пометкой, чтобы Done не исчезали незаметно.
        """
        s = self._settings
        counts = self._configured_counts()
        done_tasks = self._by_status(TaskStatus.DONE)
        include_done = s.show_done_in_fullscreen and bool(done_tasks)
        has_active = any(t.status.is_active for t in self._tasks)
        attempts = []

        def attempt(cnts, with_done):
            cols = self._columns(cnts, with_done)
            bounds = self._col_bounds(len(cols))
            dropped = len(done_tasks) if (include_done and not with_done) else 0
            # когда Done убраны, внизу резервируется место под «Скрыто выполненных: N»
            self._note = self._dropped_note(dropped) if dropped else None
            try:
                size = self._adaptive_font_size(cols, bounds)
                hidden_active, hidden_total = self._hidden_counts(cols, bounds, size)
            finally:
                self._note = None
            words_ok = self._fits(cols, bounds, size, height=False)
            shows_done = include_done and with_done
            attempts.append(((hidden_active, hidden_total + dropped), words_ok, shows_done,
                             (cols, bounds, size, dropped)))
            return hidden_total == 0

        def with_done_back(cnts):
            # активным хватило места без Done — вдруг Done теперь помещаются в оставшиеся колонки
            total = cnts[TaskStatus.TO_DO] + cnts[TaskStatus.STARTED] + cnts[TaskStatus.DONE]
            if total <= MAX_TOTAL_COLUMNS and attempt(cnts, True) and (attempts[-1][1] or not base_words_ok):
                return attempts[-1][3]
            return None

        if attempt(counts, include_done):
            return attempts[-1][3]
        base_words_ok = attempts[0][1]

        # без активных дел скрывать Done бессмысленно — экран остался бы пустым
        drop_done = include_done and has_active
        if drop_done:
            if attempt(counts, False):
                return attempts[-1][3]

        with_done = include_done and not drop_done
        statuses = [st for st in (TaskStatus.TO_DO, TaskStatus.STARTED) if self._by_status(st)]
        if with_done:
            statuses.append(TaskStatus.DONE)  # одни Done: расширяется их собственный блок
        counts = dict(counts)

        def rendered_total():
            return counts[TaskStatus.TO_DO] + counts[TaskStatus.STARTED] + (counts[TaskStatus.DONE] if with_done else 0)

        while statuses and rendered_total() < MAX_TOTAL_COLUMNS:
            # колонку получает статус, у которого больше всего дел на одну колонку;
            # если дел уже не больше, чем колонок, новая колонка лишь сузила бы их
            busiest = max(statuses, key=lambda st: len(self._by_status(st)) / counts[st])
            if counts[busiest] >= len(self._by_status(busiest)):
                break
            counts[busiest] += 1
            if attempt(counts, with_done) and (attempts[-1][1] or not base_words_ok):
                plan = attempts[-1][3]
                if drop_done:
                    return with_done_back(counts) or plan
                return plan

        # целиком не влезает: из вариантов, где слова не стали вылезать за колонку сильнее
        # исходного, — тот, что скрывает меньше всего активных дел (при равенстве — более ранний).
        # Вариант, где Done на экране, а активные скрыты, недопустим, если Done можно убрать.
        valid = [a for a in attempts
                 if (a[1] or not base_words_ok) and not (drop_done and a[2] and a[0][0] > 0)]
        best = min(valid or attempts, key=lambda a: a[0])
        return best[3]

    def _note_reserve(self, size: int, bounds) -> int:
        """Высота служебной строки под пометку (с переносом по самой узкой колонке, тем же
        шрифтом, которым она рисуется) плюс отступ перед ней. 0 — пометки нет."""
        if not self._note:
            return 0
        narrow = min(iw for _, iw in bounds)
        fm = QFontMetrics(self._base_font(size))
        flags = self._align_flags() | Qt.TextWordWrap
        return fm.boundingRect(QRect(0, 0, narrow, MEASURE_HEIGHT), flags, self._note).height() + max(8, size // 3)

    @staticmethod
    def _dropped_note(n: int) -> str:
        return f"Скрыто выполненных: {n}"

    def _hidden_counts(self, columns, bounds, size: int) -> tuple[int, int]:
        """Сколько дел не помещается по высоте: (активных, всего)."""
        metrics = {kind: QFontMetrics(f) for kind, f in self._fonts_for(size).items()}
        flags = self._align_flags() | Qt.TextWordWrap
        gap = max(8, size // 3)
        h = self.height() - self._note_reserve(size, bounds)
        active = total = 0
        for col, (_, inner_w) in zip(columns, bounds):
            y = int(size * 0.5)
            for i, task in enumerate(col):
                fm = metrics[self._font_kind(task)]
                y += fm.boundingRect(QRect(0, 0, inner_w, MEASURE_HEIGHT), flags, _title(task)).height()
                if y > h:
                    rest = col[max(i, 1):]   # первое дело колонки показывается всегда
                    total += len(rest)
                    active += sum(1 for t in rest if t.status.is_active)
                    break
                y += gap
        return active, total

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

    def _fits(self, columns, bounds, size: int, height: bool = True) -> bool:
        """Влезают ли все колонки при данном размере шрифта: ни одно слово не шире
        колонки и (если height) суммарная высота с переносами не выше экрана."""
        metrics = {kind: QFontMetrics(f) for kind, f in self._fonts_for(size).items()}
        flags = self._align_flags() | Qt.TextWordWrap
        gap = max(8, size // 3)
        h = self.height() - self._note_reserve(size, bounds)
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
                if not height:
                    continue
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
        if not any(self._columns()):
            return None
        s = self._settings
        columns, bounds, size, dropped_done = self._fit_plan()
        n_cols = len(columns)
        # с убранными Done дела раскладываются выше на тот же резерв, что и при подборе,
        # поэтому пометка «Скрыто выполненных» всегда помещается
        self._note = self._dropped_note(dropped_done) if dropped_done else None
        try:
            h = self.height() - self._note_reserve(size, bounds)
        finally:
            self._note = None
        fonts = self._fonts_for(size)
        metrics = {kind: QFontMetrics(f) for kind, f in fonts.items()}
        flags = self._align_flags() | Qt.TextWordWrap
        text_color = QColor(s.text_color)
        urgent_color = QColor(s.urgent_fullscreen_color)
        markers = {st: QColor(status_color(st, s)) for st in TaskStatus}
        gap = max(8, size // 3)

        more_font = fonts["base"]
        more_color = QColor(text_color)
        more_color.setAlphaF(0.65)

        def text_height(text, inner_w):
            # с переносом: в узкой колонке служебная строка может занять две
            return metrics["base"].boundingRect(QRect(0, 0, inner_w, MEASURE_HEIGHT), flags, text).height()

        items = []
        col_ends = []   # (y конца колонки, x0, inner_w) — место под пометку о скрытых Done
        for col, (x0, inner_w) in zip(columns, bounds):
            y = int(size * 0.5)
            col_items = []
            hidden = 0
            for i, task in enumerate(col):
                kind = self._font_kind(task)
                title = _title(task)
                height = metrics[kind].boundingRect(QRect(x0 + TEXT_LEFT, y, inner_w, MEASURE_HEIGHT), flags, title).height()
                if y + height > h:
                    if i > 0:
                        hidden = len(col) - i
                        break
                    # первое дело колонки рисуется всегда, даже если оно выше экрана: лучше
                    # видеть его начало, чем одну строку «… и ещё 1». Оно обрезается по
                    # видимой области (оставляя место под «… и ещё N» для остальных дел)
                    rest = len(col) - 1
                    below = text_height(f"… и ещё {rest}", inner_w) + gap if rest else 0
                    height = max(1, h - below - y)
                    clip = True
                else:
                    clip = False
                if kind == "done":
                    color = text_color.darker(160)
                elif kind == "urgent":
                    color = urgent_color
                else:
                    color = text_color
                # высота прямоугольника = высота обрезки: drawText не выходит за него
                rect_h = height if clip else MEASURE_HEIGHT
                col_items.append((_Item(QRectF(x0 + TEXT_LEFT, y, inner_w, rect_h), height,
                                        fonts[kind], color, markers[task.status], title), y))
                y += height + gap
            if hidden:
                # не влезающие дела не обрезаются молча: строка «… и ещё N» (issue #1);
                # если и ей нет места — освобождаем его, убирая последние дела колонки
                while len(col_items) > 1 and y + text_height(f"… и ещё {hidden}", inner_w) > h:
                    _, y = col_items.pop()
                    hidden += 1
                text = f"… и ещё {hidden}"
                more_h = text_height(text, inner_w)
                if y + more_h > h and col_items:
                    # осталось одно первое дело и под строку места нет — подрезаем его
                    first, fy = col_items[0]
                    first.height = max(1, h - more_h - gap - fy)
                    first.rect = QRectF(first.rect.x(), fy, first.rect.width(), first.height)
                    y = fy + first.height + gap
                col_items.append((_Item(QRectF(x0 + TEXT_LEFT, y, inner_w, MEASURE_HEIGHT), more_h,
                                        more_font, more_color, None, text), y))
                y += more_h + gap
            items.extend(item for item, _ in col_items)
            col_ends.append((y, x0, inner_w))

        if dropped_done:
            # Done убраны ради активных дел — сказать об этом в самой короткой колонке.
            # Колонки кончаются не ниже h + gap (высокое первое дело обрезается), а резерв =
            # высота пометки + gap, так что пометка помещается в экран.
            text = self._dropped_note(dropped_done)
            y, x0, inner_w = min(col_ends, key=lambda c: c[0])
            items.append(_Item(QRectF(x0 + TEXT_LEFT, y, inner_w, MEASURE_HEIGHT), text_height(text, inner_w),
                               more_font, more_color, None, text))
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

            # Визуальный статус — цветной маркер слева от названия (у строки «… и ещё N» его нет)
            if item.marker is None:
                continue
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
