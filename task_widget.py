from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QWidget,
)

from models import TaskStatus

WIDGET_HEIGHT = 44
DELETE_BTN_SIZE = 22


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", color: str | None = None) -> None:
        super().__init__(text)
        self._color = color

    def set_color(self, color: str | None) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        pen_color = QColor(self._color) if self._color else self.palette().color(self.foregroundRole())
        painter.setPen(pen_color)
        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect().adjusted(1, 0, -1, 0), Qt.AlignVCenter | Qt.AlignLeft, elided)


class StatusButton(QPushButton):
    """Цветная плашка статуса. Рисуется вручную: собственный stylesheet у каждой
    из сотни кнопок делал пересборку списка и смену темы очень медленными."""

    reverseRequested = Signal()

    PAD_X = 6
    RADIUS = 4

    def __init__(self):
        super().__init__()
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._color = QColor()

    def _label_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.DemiBold)
        return font

    def refresh(self, task, colors=None) -> None:
        color = QColor(colors.get(task.status) if colors else task.status.color)
        text = task.status.value
        if text == self.text() and color == self._color:
            return
        self._color = color
        self.setText(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._label_font())
        return QSize(fm.horizontalAdvance(self.text()) + 2 * self.PAD_X, 24)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawRoundedRect(QRectF(self.rect()), self.RADIUS, self.RADIUS)
        painter.setPen(QColor("white"))
        painter.setFont(self._label_font())
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self.reverseRequested.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TaskWidget(QWidget):
    """Одна задача в списке: кнопка статуса + название. Передвигается через список-родитель."""

    statusRequested = Signal(object)          # task — прямой цикл (ЛКМ)
    statusReverseRequested = Signal(object)   # task — обратный цикл (ПКМ)
    beginEditRequested = Signal(object)       # task

    def __init__(self, task, list_view) -> None:
        super().__init__()
        self.task = task
        self.list_view = list_view
        self._edit = None
        self._dragging = False
        self.setFixedHeight(WIDGET_HEIGHT)
        self.setProperty("card", True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self.btn = StatusButton()
        self.btn.refresh(task, self.list_view.status_colors)
        self.btn.clicked.connect(lambda: self.statusRequested.emit(self.task))
        self.btn.reverseRequested.connect(lambda: self.statusReverseRequested.emit(self.task))
        layout.addWidget(self.btn)

        self.label = ElidedLabel(self._display_title())
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        if task.status is TaskStatus.DONE:
            font = self.label.font()
            font.setStrikeOut(True)
            self.label.setFont(font)
            self.label.set_color("#9CA3AF")
        if task.urgent:
            self.apply_urgent_style()
        layout.addWidget(self.label, 1)

        # удаление в один клик (issue #1); пункт «Удалить» в меню ПКМ остаётся
        self.del_btn = QPushButton("✕")
        self.del_btn.setProperty("deleteBtn", True)
        self.del_btn.setFixedSize(DELETE_BTN_SIZE, DELETE_BTN_SIZE)
        self.del_btn.setToolTip("Удалить")
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setFocusPolicy(Qt.NoFocus)
        self.del_btn.clicked.connect(lambda: self.list_view.delete_handler(self.task))
        layout.addWidget(self.del_btn)

    def _display_title(self) -> str:
        prefix = ""
        if self.task.urgent:
            prefix += "⚡ "
        if self.task.regular:
            prefix += "⟳ "
        return prefix + self.task.title

    def apply_urgent_style(self) -> None:
        font = self.label.font()
        if self.task.urgent:
            font.setBold(True)
            font.setPointSize(font.pointSize() + 5)
        else:
            font.setBold(False)
            font.setPointSize(max(1, font.pointSize() - 5))
        self.label.setFont(font)

    # ---- drag-события (делегируются списку) ----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not event.modifiers():
            if self._edit is None:
                self.list_view.cancel_edit()  # клик по другой карточке выходит из переименования
            self.list_view.on_task_press(self, event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.list_view.on_task_move(event.globalPosition().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.list_view.on_task_release(event.globalPosition().toPoint())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.beginEditRequested.emit(self.task)
        event.accept()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_rename = menu.addAction("Переименовать")
        act_delete = menu.addAction("Удалить")
        menu.addSeparator()
        act_urgent = menu.addAction("Срочное" if not self.task.urgent else "Убрать срочность")
        act_urgent.setCheckable(True)
        act_urgent.setChecked(self.task.urgent)
        act_regular = menu.addAction("Регулярное")
        act_regular.setCheckable(True)
        act_regular.setChecked(self.task.regular)
        chosen = menu.exec(event.globalPos())
        if chosen is act_rename:
            self.beginEditRequested.emit(self.task)
        elif chosen is act_delete:
            self.list_view.delete_handler(self.task)
        elif chosen is act_urgent:
            self.list_view.urgent_toggle_handler(self.task)
        elif chosen is act_regular:
            self.list_view.regular_toggle_handler(self.task)

    # ---- inline-редактирование ----
    def start_edit(self) -> None:
        if self._edit is not None:
            return
        self.list_view.cancel_edit(except_widget=self)
        # label НЕ скрываем: при скрытии макет переносится и центрирует кнопку статуса.
        # Поле ввода накладывается ПОВЕРХ label, закрывая его текст своим непрозрачным фоном.
        self._edit = QLineEdit(self)
        self._edit.setProperty("inlineEdit", True)
        self._edit.setText(self.task.title)
        self._edit.setMaxLength(255)
        self._edit.setFrame(False)
        x0 = self.btn.x() + self.btn.width() + 6
        width = max(40, self.del_btn.x() - x0 - 6)  # поле не наезжает на крестик удаления
        self._edit.setGeometry(x0, 9, width, 26)
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()
        self._edit.installEventFilter(self)
        self._edit.returnPressed.connect(self._commit_edit)
        self.list_view.edit_started()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._cancel_edit()
            return True
        return super().eventFilter(obj, event)

    def _commit_edit(self) -> None:
        if self._edit is None:
            return
        text = self._edit.text()
        if self.list_view.rename_handler is not None and not self.list_view.rename_handler(self.task, text):
            # невалидное имя — оставить редактирование
            self._edit.setFocus()
            return
        self._cancel_edit()

    def commit_edit(self) -> None:
        """Сохранить изменения и выйти из режима переименования (клик вне поля, Enter)."""
        if self._edit is None:
            return
        self._commit_edit()

    def _cancel_edit(self) -> None:
        if self._edit is None:
            return
        self._edit.deleteLater()
        self._edit = None
        self.label.setText(self._display_title())
        self.list_view.edit_finished()