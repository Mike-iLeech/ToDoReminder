from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from settings import Settings
from theme import build_stylesheet

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class SettingsDialog(QDialog):
    """Окно настроек. Каждое изменение сразу применяется и сохраняется."""

    def __init__(self, settings_manager, screens, parent=None) -> None:
        super().__init__(parent)
        self.sm = settings_manager
        self.s: Settings = settings_manager.s
        self._preview_callback = None
        self._color_refs = {}  # field -> (btn, edit, on_change)
        self.setWindowTitle("Настройки")
        self.setWindowModality(Qt.WindowModal)
        self.resize(420, 760)
        self.setStyleSheet(build_stylesheet(self.s.theme))

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        root.addLayout(form)

        # интервал напоминаний, минуты (хранится в секундах)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setSuffix(" мин")
        self.interval_spin.setValue(self.s.reminder_interval_seconds // 60)
        self.interval_spin.valueChanged.connect(self._on_interval)
        form.addRow("Интервал напоминаний", self.interval_spin)

        # вывод выполненных дел
        self.done_combo = QComboBox()
        self.done_combo.addItems(["Нет", "Да"])
        self.done_combo.setCurrentIndex(1 if self.s.show_done_in_fullscreen else 0)
        self.done_combo.currentIndexChanged.connect(self._on_done)
        form.addRow("Выводить выполненные дела\nв полноэкранном уведомлении?", self.done_combo)

        # число колонок по статусам в полноэкранном уведомлении
        cols_label = QLabel("Колонки в полноэкранном уведомлении")
        cols_label.setStyleSheet("font-weight: bold;")
        form.addRow(cols_label)

        self.cols_todo_spin = QSpinBox()
        self.cols_todo_spin.setRange(1, 8)
        self.cols_todo_spin.setValue(self.s.fullscreen_columns_todo)
        self.cols_todo_spin.valueChanged.connect(self._on_cols_todo)
        form.addRow("Колонки To Do", self.cols_todo_spin)

        self.cols_started_spin = QSpinBox()
        self.cols_started_spin.setRange(1, 8)
        self.cols_started_spin.setValue(self.s.fullscreen_columns_started)
        self.cols_started_spin.valueChanged.connect(self._on_cols_started)
        form.addRow("Колонки Started", self.cols_started_spin)

        # монитор
        self.monitor_combo = QComboBox()
        self._monitor_items = []  # (index, screen_name or None for primary)
        self.monitor_combo.addItem("Основной экран")
        self._monitor_items.append(None)
        for i, scr in enumerate(screens, start=1):
            geo = scr.geometry()
            label = f"Экран {i} — {geo.width()}×{geo.height()}"
            self.monitor_combo.addItem(label)
            self._monitor_items.append(scr.name())
        self._select_monitor(self.s.monitor_name)
        self.monitor_combo.currentIndexChanged.connect(self._on_monitor)
        form.addRow("Экран для уведомления", self.monitor_combo)

        # размер текста
        self.size_spin = QSpinBox()
        self.size_spin.setRange(12, 100)
        self.size_spin.setSingleStep(1)
        self.size_spin.setSuffix(" px")
        self.size_spin.setValue(self.s.text_size)
        self.size_spin.valueChanged.connect(self._on_text_size)
        form.addRow("Размер текста", self.size_spin)

        # шрифт
        from PySide6.QtGui import QFontDatabase

        self.font_combo = QComboBox()
        families = QFontDatabase().families()
        for fam in families:
            self.font_combo.addItem(fam)
            item_font = QFont(fam)
            self.font_combo.setItemData(self.font_combo.count() - 1, item_font, Qt.FontRole)
        idx = self.font_combo.findText(self.s.font_family)
        self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.font_combo.currentIndexChanged.connect(self._on_font)
        form.addRow("Шрифт", self.font_combo)

        # начертание
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Обычный", "Жирный", "Курсив", "Жирный курсив"])
        self.style_combo.setCurrentIndex(self.s.font_style_index)
        self.style_combo.currentIndexChanged.connect(self._on_style)
        form.addRow("Начертание", self.style_combo)

        # выравнивание
        self.align_combo = QComboBox()
        self.align_combo.addItems(["Слева", "По центру", "Справа"])
        self.align_combo.setCurrentIndex(self.s.alignment_index)
        self.align_combo.currentIndexChanged.connect(self._on_align)
        form.addRow("Выравнивание", self.align_combo)

        # фон
        self.bg_row = self._color_row(form, "Фон", "bg_color", self.s.bg_color, self._on_bg)
        # текст
        self.fg_row = self._color_row(form, "Текст", "text_color", self.s.text_color, self._on_fg)

        # цвета статусов
        self.todo_color_row = self._color_row(form, "Цвет статуса To Do", "color_status_todo", self.s.color_status_todo, self._on_todo_color)
        self.started_color_row = self._color_row(form, "Цвет статуса Started", "color_status_started", self.s.color_status_started, self._on_started_color)
        self.done_color_row = self._color_row(form, "Цвет статуса Done", "color_status_done", self.s.color_status_done, self._on_done_color)

        # срочные дела в полноэкранном уведомлении
        urgent_label = QLabel("Срочные дела (полноэкранное)")
        urgent_label.setStyleSheet("font-weight: bold;")
        form.addRow(urgent_label)

        self.urgent_size_spin = QSpinBox()
        self.urgent_size_spin.setRange(0, 30)
        self.urgent_size_spin.setSuffix(" px")
        self.urgent_size_spin.setValue(self.s.urgent_fullscreen_size_delta)
        self.urgent_size_spin.valueChanged.connect(self._on_urgent_size)
        form.addRow("Увеличение размера шрифта", self.urgent_size_spin)

        self.urgent_color_row = self._color_row(form, "Цвет срочных дел", "urgent_fullscreen_color", self.s.urgent_fullscreen_color, self._on_urgent_color)

        self.urgent_style_combo = QComboBox()
        self.urgent_style_combo.addItems(["Обычный", "Жирный", "Курсив", "Жирный курсив"])
        self.urgent_style_combo.setCurrentIndex(self.s.urgent_fullscreen_style_index)
        self.urgent_style_combo.currentIndexChanged.connect(self._on_urgent_style)
        form.addRow("Начертание срочных дел", self.urgent_style_combo)

        # прозрачность 0–100%
        opacity_box = QWidget()
        opacity_lay = QHBoxLayout(opacity_box)
        opacity_lay.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(self.s.opacity_percent)
        self.opacity_label = QLabel(f"{self.s.opacity_percent}%")
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        opacity_lay.addWidget(self.opacity_slider, 1)
        opacity_lay.addWidget(self.opacity_label)
        form.addRow("Прозрачность (0% непрозрачно)", opacity_box)

        # автозапуск
        self.autostart_cb = QCheckBox("Запускать вместе с Windows (в трей)")
        self.autostart_cb.setChecked(self.s.autostart)
        self.autostart_cb.toggled.connect(self._on_autostart)
        root.addWidget(self.autostart_cb)

        # поведение по клику в трее
        self.tray_combo = QComboBox()
        self.tray_combo.addItems(["Открывать основное окно", "Ничего"])
        self.tray_combo.setCurrentIndex(self.s.tray_action_index)
        self.tray_combo.currentIndexChanged.connect(self._on_tray_action)
        form.addRow("Действие при клике по иконке трея", self.tray_combo)

        # кнопка предпросмотра
        preview_btn = QPushButton("Предпросмотр")
        preview_btn.clicked.connect(self._on_preview)
        root.addWidget(preview_btn)

        # сброс к настройкам по умолчанию
        reset_btn = QPushButton("Сбросить к настройкам по-умолчанию")
        reset_btn.clicked.connect(self._reset_defaults)
        root.addWidget(reset_btn)

        hint = QLabel("Все изменения сохраняются сразу.")
        hint.setStyleSheet("color: #848b96; font-size: 11px;")
        root.addWidget(hint)

    # ------------------------------------------------------------------ helpers

    def _color_row(self, form, label, field, initial, on_change):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton(initial)
        btn.setFixedWidth(90)
        btn.setStyleSheet(
            "QPushButton { border: 1px solid #CBD0D8; border-radius: 4px;"
            " background-color: " + initial + "; color: "
            + ("#000" if QColor(initial).lightness() > 128 else "#fff") + " }"
        )
        edit = QLineEdit(initial)
        edit.setMaxLength(9)
        edit.setFixedWidth(110)
        lay.addWidget(btn)
        lay.addWidget(edit)
        form.addRow(label, row)
        self._color_refs[field] = (btn, edit, on_change)

        def pick():
            color = QColorDialog.getColor(QColor(edit.text()), self, "Выбор цвета")
            if color.isValid():
                hexv = color.name().upper()
                on_change(hexv)
                btn.setText(hexv)
                edit.setText(hexv)
                self._refresh_color_btn(btn, hexv)

        def typed():
            text = edit.text().strip()
            if not HEX_RE.match(text):
                edit.setText(btn.text())
                return
            on_change(text.upper())
            btn.setText(text.upper())
            edit.setText(text.upper())
            self._refresh_color_btn(btn, text.upper())

        btn.clicked.connect(pick)
        edit.editingFinished.connect(typed)
        return row

    def _refresh_color_btn(self, btn, hexv):
        color = QColor(hexv)
        fg = "#000" if color.lightness() > 128 else "#fff"
        btn.setStyleSheet(
            "QPushButton { border: 1px solid #CBD0D8; border-radius: 4px;"
            " background-color: " + hexv + "; color: " + fg + " }"
        )

    # ------------------------------------------------------------------ handlers

    def _on_interval(self, value: int) -> None:
        self.s.reminder_interval_seconds = value * 60
        self.sm.save()

    def _on_done(self, index: int) -> None:
        self.s.show_done_in_fullscreen = index == 1
        self.sm.save()

    def _on_cols_todo(self, value: int) -> None:
        self.s.fullscreen_columns_todo = value
        self.sm.save()

    def _on_cols_started(self, value: int) -> None:
        self.s.fullscreen_columns_started = value
        self.sm.save()

    def _on_monitor(self, index: int) -> None:
        name = self._monitor_items[index] if 0 <= index < len(self._monitor_items) else None
        self.s.monitor_name = name or ""
        self.sm.save()

    def _on_text_size(self, value: int) -> None:
        self.s.text_size = value
        self.sm.save()

    def _on_font(self, index: int) -> None:
        self.s.font_family = self.font_combo.currentText()
        self.sm.save()

    def _on_style(self, index: int) -> None:
        self.s.font_style_index = index
        self.sm.save()

    def _on_align(self, index: int) -> None:
        self.s.alignment_index = index
        self.sm.save()

    def _on_bg(self, hexv: str) -> None:
        self.s.bg_color = hexv
        self.sm.save()

    def _on_fg(self, hexv: str) -> None:
        self.s.text_color = hexv
        self.sm.save()

    def _on_todo_color(self, hexv: str) -> None:
        self.s.color_status_todo = hexv
        self.sm.save()

    def _on_started_color(self, hexv: str) -> None:
        self.s.color_status_started = hexv
        self.sm.save()

    def _on_done_color(self, hexv: str) -> None:
        self.s.color_status_done = hexv
        self.sm.save()

    def _on_urgent_size(self, value: int) -> None:
        self.s.urgent_fullscreen_size_delta = value
        self.sm.save()

    def _on_urgent_color(self, hexv: str) -> None:
        self.s.urgent_fullscreen_color = hexv
        self.sm.save()

    def _on_urgent_style(self, index: int) -> None:
        self.s.urgent_fullscreen_style_index = index
        self.sm.save()

    def _on_opacity(self, value: int) -> None:
        self.s.opacity_percent = value
        self.opacity_label.setText(f"{value}%")
        self.sm.save()

    def _on_autostart(self, checked: bool) -> None:
        self.s.autostart = checked
        self.sm.save()

    def _on_tray_action(self, index: int) -> None:
        self.s.tray_action_index = index
        self.sm.save()

    def _on_preview(self) -> None:
        self._preview_callback()

    def set_preview_callback(self, callback) -> None:
        self._preview_callback = callback

    def _select_monitor(self, name: str) -> None:
        if not name:
            self.monitor_combo.setCurrentIndex(0)
            return
        for i, item in enumerate(self._monitor_items):
            if item == name:
                self.monitor_combo.setCurrentIndex(i)
                return
        self.monitor_combo.setCurrentIndex(0)

    # ------------------------------------------------------------------ сброс

    def _reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Сброс настроек",
            "Сбросить все настройки к значениям по умолчанию?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.s = Settings()
        self.sm.s = self.s
        self.sm.save()
        self._apply_defaults_to_ui()

    def _apply_defaults_to_ui(self) -> None:
        s = self.s
        widgets = [
            self.interval_spin,
            self.done_combo,
            self.cols_todo_spin,
            self.cols_started_spin,
            self.monitor_combo,
            self.size_spin,
            self.font_combo,
            self.style_combo,
            self.align_combo,
            self.urgent_size_spin,
            self.urgent_style_combo,
            self.opacity_slider,
            self.autostart_cb,
            self.tray_combo,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.interval_spin.setValue(s.reminder_interval_seconds // 60)
            self.done_combo.setCurrentIndex(1 if s.show_done_in_fullscreen else 0)
            self.cols_todo_spin.setValue(s.fullscreen_columns_todo)
            self.cols_started_spin.setValue(s.fullscreen_columns_started)
            self._select_monitor(s.monitor_name)
            self.size_spin.setValue(s.text_size)
            idx = self.font_combo.findText(s.font_family)
            self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.style_combo.setCurrentIndex(s.font_style_index)
            self.align_combo.setCurrentIndex(s.alignment_index)
            self.opacity_slider.setValue(s.opacity_percent)
            self.opacity_label.setText(f"{s.opacity_percent}%")
            self.autostart_cb.setChecked(s.autostart)
            self.tray_combo.setCurrentIndex(s.tray_action_index)
        finally:
            for w in widgets:
                w.blockSignals(False)
        # цветовые строки
        for field, (btn, edit, _) in self._color_refs.items():
            hexv = str(getattr(s, field, "#FFFFFF"))
            edit.setText(hexv)
            btn.setText(hexv)
            self._refresh_color_btn(btn, hexv)
        # тема
        self.setStyleSheet(build_stylesheet(s.theme))