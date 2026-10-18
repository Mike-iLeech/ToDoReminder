from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from task_widget import TaskWidget, WIDGET_HEIGHT

SPACING = 6
STEP = WIDGET_HEIGHT + SPACING
EDGE_ZONE = 56
FRAME_MS = 30


class DragRepresentation(QLabel):
    """Полноценное представление перетаскиваемой задачи, следующее за курсором."""

    def __init__(self, task):
        super().__init__()
        self.setText(task.title)
        self.setProperty("dragRep", True)
        self.setFixedSize(280, WIDGET_HEIGHT)


class _OutsideClickFilter(QObject):
    """Клик вне переименовываемой карточки завершает переименование.

    Фильтр ставится на приложение только на время редактирования: постоянный
    фильтр уровня приложения гонял через Python каждое событие Qt.
    """

    def __init__(self, list_view) -> None:
        super().__init__(list_view)
        self._list = list_view

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.MouseButtonPress:
            edited = self._list.active_edit_widget()
            if edited is None:
                self._list.edit_finished()
            else:
                w = QApplication.widgetAt(event.globalPosition().toPoint())
                if w is not edited and w is not edited._edit:
                    self._list.cancel_edit()
        return False


class TaskListWidget(QWidget):
    """Вертикальный список задач с полноценным визуальным drag-and-drop.

    - перетаскиваемое представление следует за курсором;
    - исходная карточка во время перетаскивания скрывается;
    - соседи плавно раздвигаются (компактная раскладка) и плавно возвращаются;
    - пустой слот показывает место вставки (без разделительной линии);
    - позиция вставки пересчитывается непрерывно;
    - автопрокрутка по краям всего окна с комбинированной скоростью.
    """

    taskMoved = Signal(int, int)           # (from_index, to_slot)
    statusCycleRequested = Signal(object)  # task — прямой цикл
    statusReverseRequested = Signal(object)  # task — обратный цикл

    def __init__(self, scroll_area=None) -> None:
        super().__init__()
        self._scroll = scroll_area
        self._widgets: list[TaskWidget] = []
        self._drag = None          # (drag_index, target_slot)
        self._pressed = None
        self._press_global = None
        self._dragging = False
        self._rep = None
        self._edge_ms = 0

        self._anim = QTimer(self)
        self._anim.setInterval(FRAME_MS)
        self._anim.timeout.connect(self._tick)

        self.rename_handler = None
        self.delete_handler = None
        self.regular_toggle_handler = None
        self.urgent_toggle_handler = None

        self.status_colors = None  # dict {TaskStatus: hex} из настроек
        self._app_filter_active = False
        self._click_filter = _OutsideClickFilter(self)
        self._click_filter_active = False
        self._deleted_at = float("-inf")

    # ------------------------------------------------------------------ API

    @property
    def dragging(self) -> bool:
        return self._dragging

    def active_edit_widget(self):
        for w in self._widgets:
            if w._edit is not None:
                return w
        return None

    def widget_by_task(self, task):
        for w in self._widgets:
            if w.task.id == task.id:
                return w
        return None

    def cancel_edit(self, except_widget=None) -> None:
        """Выход из переименования с сохранением введённого текста (клик мышью, Enter)."""
        for w in self._widgets:
            if w is not except_widget and w._edit is not None:
                w.commit_edit()

    def request_delete(self, task) -> None:
        """Удаление крестиком. После удаления под курсор подъезжает соседняя карточка, и второй
        щелчок двойного клика удалил бы и её — поэтому в пределах интервала двойного щелчка
        повторное удаление (и переименование двойным кликом) игнорируется."""
        if self.recently_deleted():
            return
        self._deleted_at = time.monotonic()
        if self.delete_handler is not None:
            self.delete_handler(task)

    def recently_deleted(self) -> bool:
        return time.monotonic() - self._deleted_at < QApplication.doubleClickInterval() / 1000

    def edit_started(self) -> None:
        if not self._click_filter_active:
            QApplication.instance().installEventFilter(self._click_filter)
            self._click_filter_active = True

    def edit_finished(self) -> None:
        if self._click_filter_active and self.active_edit_widget() is None:
            QApplication.instance().removeEventFilter(self._click_filter)
            self._click_filter_active = False

    def _visual_key(self, task) -> tuple:
        """Всё, от чего зависит вид карточки. Совпал ключ — карточку можно переиспользовать."""
        color = self.status_colors.get(task.status) if self.status_colors else None
        return (task.title, task.status, task.regular, task.urgent, color)

    def _create_widget(self, task) -> TaskWidget:
        w = TaskWidget(task, self)
        w.visual_key = self._visual_key(task)
        w.statusRequested.connect(self.statusCycleRequested.emit)
        w.statusReverseRequested.connect(self.statusReverseRequested.emit)
        w.beginEditRequested.connect(w.start_edit)
        w.setParent(self)
        return w

    def rebuild(self, tasks, animate: bool = True) -> None:
        """Синхронизирует карточки со списком задач.

        Карточки неизменившихся задач переиспользуются (раньше пересоздавался весь
        список на каждый клик); заново создаются только новые и изменившиеся.
        """
        old = {w.task.id: w for w in self._widgets}
        if self._rep is not None:
            self._remove_rep()
        self._pressed = None
        self._press_global = None

        widgets: list[TaskWidget] = []
        fresh: list[TaskWidget] = []
        for task in tasks:
            w = old.pop(task.id, None)
            if w is not None and w.visual_key == self._visual_key(task):
                w.task = task
            else:
                prev_y = w.y() if w is not None else None
                if w is not None:
                    w.hide()
                    w.deleteLater()
                w = self._create_widget(task)
                if prev_y is not None:
                    w.move(0, prev_y)
                fresh.append(w)
            widgets.append(w)
        had_widgets = bool(self._widgets)
        for w in old.values():
            w.hide()
            w.deleteLater()
        self._widgets = widgets

        self.setFixedHeight(max(1, len(tasks) * STEP))
        self._apply_child_widths()
        for w in fresh:
            w.show()

        if animate and had_widgets and not self._dragging:
            self._start_anim()
        else:
            self._place_standard()

    def _place_standard(self) -> None:
        for i, w in enumerate(self._widgets):
            w.move(0, i * STEP)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_child_widths()

    def _apply_child_widths(self) -> None:
        width = max(10, self.width())
        for w in self._widgets:
            w.setFixedWidth(width)
        if self._rep is not None:
            self._rep.setFixedWidth(width)

    # ------------------------------------------------------------------ drag

    def on_task_press(self, widget: TaskWidget, global_pos: QPoint) -> None:
        if self._dragging:
            return
        self._pressed = widget
        self._press_global = global_pos

    def on_task_move(self, global_pos: QPoint) -> None:
        if self._dragging:
            self._update_drag(global_pos)
            return
        if self._pressed is None or self._press_global is None:
            return
        if (global_pos - self._press_global).manhattanLength() >= QApplication.startDragDistance():
            self._begin_drag()

    def on_task_release(self, global_pos: QPoint) -> None:
        self._pressed = None
        self._press_global = None
        if self._dragging:
            self._end_drag(global_pos)

    def cancel_drag(self) -> None:
        if not self._dragging:
            return
        self._drag = None
        self._dragging = False
        self._remove_rep()
        self._restore_widgets()
        self._remove_app_filter()

    def _begin_drag(self) -> None:
        if self._pressed is None:
            return
        self.cancel_edit()  # начатое перетаскивание закрывает переименование с сохранением
        idx = self._widgets.index(self._pressed)
        if not self._pressed.task.status.is_active:
            # порядок активных задач свободный; Done блок не перетаскиваем
            self._pressed = None
            self._press_global = None
            return
        if self._pressed.task.urgent:
            # срочные задачи закреплены вверху и не перетаскиваются
            self._pressed = None
            self._press_global = None
            return
        self._drag = [idx, idx]
        self._dragging = True
        self._pressed.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._pressed.hide()
        self._rep = DragRepresentation(self._pressed.task)
        self._rep.setParent(self)
        self._rep.show()
        self._rep.raise_()
        self._apply_child_widths()
        self._install_app_filter()
        self._update_drag(QCursor.pos())
        self._start_anim()

    def _update_drag(self, global_pos: QPoint) -> None:
        if self._drag is None:
            return
        d, _ = self._drag
        content_y = self._content_y(global_pos)
        t = int(round(content_y / STEP))
        t = self._clamp_slot(t)
        if t != self._drag[1]:
            self._drag[1] = t
        cy = max(0, min(content_y, len(self._widgets) * STEP))
        if self._rep is not None:
            self._rep.move(0, int(cy - WIDGET_HEIGHT / 2))

    def _clamp_slot(self, t: int) -> int:
        n = len(self._widgets)
        t = max(0, min(t, n - 1))
        active_count = sum(1 for w in self._widgets if w.task.status.is_active)
        if active_count < n:
            # активные задачи не могут вставляться в блок Done:
            # после удаления перетаскиваемой активной задачи блок Done смещается
            # на активность меньше, поэтому слот вставки ограничен (active_count - 1)
            t = max(0, min(t, active_count - 1))
        return t

    def _content_y(self, global_pos: QPoint) -> int:
        if self._scroll is None:
            return self.mapFromGlobal(global_pos).y()
        vp = self._scroll.viewport()
        top = vp.mapToGlobal(QPoint(0, 0)).y()
        scroll = self._scroll.verticalScrollBar().value()
        return global_pos.y() - top + scroll

    def _end_drag(self, global_pos: QPoint) -> None:
        self._update_drag(global_pos)
        d, t = self._drag
        self._restore_widgets()
        self._drag = None
        self._dragging = False
        self._edge_ms = 0
        self._remove_rep()
        self._remove_app_filter()
        if d != t:
            self.taskMoved.emit(d, t)
        else:
            self._start_anim()

    def _restore_widgets(self) -> None:
        for w in self._widgets:
            w.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            w.show()

    # ------------------------------------------------------------------ layout

    def _targets(self) -> dict:
        targets = {}
        n = len(self._widgets)
        if self._drag is None:
            for i, w in enumerate(self._widgets):
                targets[w] = i * STEP
            return targets
        d, t = self._drag
        for i, w in enumerate(self._widgets):
            if i == d:
                targets[w] = d * STEP          # скрытая карточка остаётся на исходном месте
            else:
                slot = i if i < d else i - 1
                if slot >= t:
                    slot += 1
                targets[w] = slot * STEP
        return targets

    def _tick(self) -> None:
        if self._dragging:
            self._handle_autoscroll()
            self._update_drag(QCursor.pos())
        targets = self._targets()
        moved = False
        for w, ty in targets.items():
            y = w.y()
            dy = ty - y
            if abs(dy) > 0.5:
                step = dy * 0.35
                w.move(0, ty if abs(step) < 1 else round(y + step))
                moved = True
            elif dy != 0:
                w.move(0, ty)
        if not self._dragging and not moved:
            self._anim.stop()

    def _start_anim(self) -> None:
        if not self._anim.isActive():
            self._anim.start()

    # ------------------------------------------------------------------ autoscroll

    def _handle_autoscroll(self) -> None:
        if self._scroll is None:
            return
        global_pos = QCursor.pos()
        main = self.window()
        if main is None:
            return
        mpos = main.mapFromGlobal(global_pos)
        mh = main.height()
        top_prox = mpos.y()
        bot_prox = mh - mpos.y()
        direction = 0
        if top_prox < EDGE_ZONE:
            direction = -1
        elif bot_prox < EDGE_ZONE:
            direction = 1
        if direction == 0:
            self._edge_ms = 0
            return
        dist = top_prox if direction < 0 else bot_prox
        self._edge_ms += FRAME_MS
        depth = max(0, EDGE_ZONE - dist)
        proximity = depth / EDGE_ZONE
        hold = min(self._edge_ms, 3000) / 3000
        # комбинированная скорость: расстояние до края + время удержания
        speed = int(2 + 26 * proximity * (0.5 + 0.5 * hold))
        sb = self._scroll.verticalScrollBar()
        dv = direction * speed
        if direction < 0 and sb.value() <= 0:
            dv = 0
        if direction > 0 and sb.value() >= sb.maximum():
            dv = 0
        if dv:
            sb.setValue(sb.value() + dv)

    # ------------------------------------------------------------------ rep / filter

    def _remove_rep(self) -> None:
        if self._rep is not None:
            self._rep.deleteLater()
            self._rep = None

    def _install_app_filter(self) -> None:
        if not self._app_filter_active:
            QApplication.instance().installEventFilter(self)
            self._app_filter_active = True

    def _remove_app_filter(self) -> None:
        if self._app_filter_active:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_active = False

    def eventFilter(self, obj, event) -> bool:
        if self._dragging and event.type() in (QEvent.MouseMove, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            global_pos = event.globalPosition().toPoint()
            if event.type() in (QEvent.MouseMove, QEvent.MouseButtonDblClick):
                self.on_task_move(global_pos)
            else:
                self.on_task_release(global_pos)
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        self.cancel_edit()
        event.accept()