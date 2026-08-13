from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
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
    reverseRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(
            """
            QPushButton {
                color: white; font-weight: 600; border: none; border-radius: 4px;
                padding: 0 6px; font-size: 11px;
            }
            QPushButton:hover { opacity: 0.9; }
            """
        )

    def refresh(self, task, colors=None) -> None:
        color = colors.get(task.status) if colors else task.status.color
        self.setText(task.status.value)
        self.setStyleSheet(
            "QPushButton { color: white; font-weight: 600; border: none; border-radius: 4px;"
            " background-color: " + color + "; padding: 0 6px; font-size: 11px; }"
        )

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
        layout.addWidget(self.label, 1)

    def _display_title(self) -> str:
        return ("⟳ " if self.task.regular else "") + self.task.title

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
        act_regular = menu.addAction("Регулярное")
        act_regular.setCheckable(True)
        act_regular.setChecked(self.task.regular)
        chosen = menu.exec(event.globalPos())
        if chosen is act_rename:
            self.beginEditRequested.emit(self.task)
        elif chosen is act_delete:
            self.list_view.delete_handler(self.task)
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
        width = max(40, self.width() - x0 - 8)
        self._edit.setGeometry(x0, 9, width, 26)
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()
        self._edit.installEventFilter(self)
        self._edit.returnPressed.connect(self._commit_edit)

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