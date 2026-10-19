from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reminder_window import MAX_TOTAL_COLUMNS
from settings import Settings
from theme import build_stylesheet, fix_spin_inset
from update_manager import CHECK_INTERVAL_CHOICES, DEFAULT_CHECK_HOURS

UPDATE_INTERVAL_NAMES = {1: "раз в час", 3: "раз в 3 часа", 6: "раз в 6 часов",
                         12: "раз в 12 часов", 24: "раз в сутки"}
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
STYLE_NAMES = ["Обычный", "Жирный", "Курсив", "Жирный курсив"]


class FontComboBox(QComboBox):
    """Поле узкое, а раскрывающийся список — по ширине названий (каждое своим шрифтом).
    Ширина считается при первом раскрытии: перебор сотен шрифтов при каждом открытии
    окна настроек заметно его замедлял."""

    _popup_sized = False

    def showPopup(self) -> None:
        if not self._popup_sized:
            view = self.view()
            view.setMinimumWidth(view.sizeHintForColumn(0) + 24)
            self._popup_sized = True
        super().showPopup()


class SettingsDialog(QDialog):
    """Окно настроек. Каждое изменение сразу применяется и сохраняется."""

    def __init__(self, settings_manager, screens, parent=None) -> None:
        super().__init__(parent)
        self.sm = settings_manager
        self.s: Settings = settings_manager.s
        self._preview_callback = None
        self._update_callback = None
        self._color_refs = {}  # field -> (кнопка-образец, on_change)
        self.setWindowTitle("Настройки")
        self.setWindowModality(Qt.WindowModal)
        self.setStyleSheet(build_stylesheet(self.s.theme))

        # Всё содержимое — в области прокрутки: на экране с масштабом 125–150 % окно
        # не помещалось по высоте, а его минимальная высота была больше экрана, и при
        # попытке растянуть его Windows уводила окно за край. Кнопки внизу — вне прокрутки.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.setSpacing(8)
        self._scroll = QScrollArea()
        self._scroll.setProperty("settingsScroll", True)
        self._scroll.setWidgetResizable(True)
        # горизонтальная прокрутка появляется только на очень узком экране, где окно не может
        # стать шире минимальной ширины содержимого — лучше прокрутка, чем обрезанные поля
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(12, 10, 12, 4)
        root.setSpacing(8)
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll, 1)

        # ---- напоминание
        root.addWidget(self._section("Напоминание"))
        form = QFormLayout()
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        root.addLayout(form)

        # интервал напоминаний, минуты (хранится в секундах)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setSuffix(" мин")
        self.interval_spin.setValue(self.s.reminder_interval_seconds // 60)
        self.interval_spin.valueChanged.connect(self._on_interval)
        form.addRow("Интервал напоминаний", self.interval_spin)

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

        # вывод выполненных дел
        self.done_combo = QComboBox()
        self.done_combo.addItems(["Нет", "Да"])
        self.done_combo.setCurrentIndex(1 if self.s.show_done_in_fullscreen else 0)
        self.done_combo.currentIndexChanged.connect(self._on_done)
        form.addRow("Показывать выполненные дела", self.done_combo)

        # прозрачность 0–100%
        opacity_box = QWidget()
        opacity_lay = QHBoxLayout(opacity_box)
        opacity_lay.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(self.s.opacity_percent)
        self.opacity_label = QLabel(f"{self.s.opacity_percent}%")
        self.opacity_label.setMinimumWidth(36)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        opacity_lay.addWidget(self.opacity_slider, 1)
        opacity_lay.addWidget(self.opacity_label)
        form.addRow("Прозрачность (0% — непрозрачно)", opacity_box)

        # автоудаление выполненных (issue #1)
        self.auto_remove_cb = QCheckBox("Удалять выполненные дела в начале нового дня и при запуске")
        self.auto_remove_cb.setChecked(self.s.auto_remove_done)
        self.auto_remove_cb.toggled.connect(self._on_auto_remove)
        root.addWidget(self.auto_remove_cb)

        # ---- число колонок по статусам: To Do (n) | Started (n) | Done (n) в одну строку
        root.addWidget(self._section("Колонки в полноэкранном уведомлении"))
        cols_row = QHBoxLayout()
        cols_row.setSpacing(14)
        self.cols_todo_spin = self._pill_spin(self.s.fullscreen_columns_todo, self._on_cols_todo)
        self.cols_started_spin = self._pill_spin(self.s.fullscreen_columns_started, self._on_cols_started)
        self.cols_done_spin = self._pill_spin(self.s.fullscreen_columns_done, self._on_cols_done)
        self._cols_done_box = None
        for title, spin in (("To Do", self.cols_todo_spin), ("Started", self.cols_started_spin),
                            ("Done", self.cols_done_spin)):
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            lay.addWidget(QLabel(title))
            lay.addWidget(spin)
            cols_row.addWidget(box)
            if spin is self.cols_done_spin:
                self._cols_done_box = box
        cols_row.addStretch(1)
        root.addLayout(cols_row)
        self._sync_done_cols_visibility()

        # ---- текст: Размер | Шрифт | Начертание | Выравнивание в одну строку
        root.addWidget(self._section("Текст напоминания"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(12, 100)
        self.size_spin.setSingleStep(1)
        self.size_spin.setSuffix(" px")
        self.size_spin.setValue(self.s.text_size)
        self.size_spin.valueChanged.connect(self._on_text_size)

        from PySide6.QtGui import QFontDatabase

        self.font_combo = FontComboBox()
        # длинные названия шрифтов не должны растягивать строку из четырёх полей
        self.font_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.font_combo.setMinimumContentsLength(8)
        for fam in QFontDatabase.families():
            self.font_combo.addItem(fam)
            self.font_combo.setItemData(self.font_combo.count() - 1, QFont(fam), Qt.FontRole)
        idx = self.font_combo.findText(self.s.font_family)
        self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.font_combo.currentIndexChanged.connect(self._on_font)

        self.style_combo = QComboBox()
        self.style_combo.addItems(STYLE_NAMES)
        self.style_combo.setCurrentIndex(self.s.font_style_index)
        self.style_combo.currentIndexChanged.connect(self._on_style)

        self.align_combo = QComboBox()
        self.align_combo.addItems(["Слева", "По центру", "Справа"])
        self.align_combo.setCurrentIndex(self.s.alignment_index)
        self.align_combo.currentIndexChanged.connect(self._on_align)

        root.addLayout(self._captioned_row([
            ("Размер", self.size_spin, 0),
            ("Шрифт", self.font_combo, 2),
            ("Начертание", self.style_combo, 1),
            ("Выравнивание", self.align_combo, 1),
        ]))

        # ---- цвета — все в одну строку, с подписью над каждым образцом
        root.addWidget(self._section("Цвета"))
        colors_row = QHBoxLayout()
        colors_row.setSpacing(8)
        for caption, field, handler in (
            ("Фон", "bg_color", self._on_bg),
            ("Текст", "text_color", self._on_fg),
            ("To Do", "color_status_todo", self._on_todo_color),
            ("Started", "color_status_started", self._on_started_color),
            ("Done", "color_status_done", self._on_done_color),
        ):
            colors_row.addWidget(self._captioned(caption, self._color_button(field, handler)), 1)
        root.addLayout(colors_row)

        # ---- срочные дела: Увеличение | Цвет | Начертание
        root.addWidget(self._section("Срочные дела в напоминании"))
        self.urgent_size_spin = QSpinBox()
        self.urgent_size_spin.setRange(0, 30)
        self.urgent_size_spin.setPrefix("+")
        self.urgent_size_spin.setSuffix(" px")
        self.urgent_size_spin.setValue(self.s.urgent_fullscreen_size_delta)
        self.urgent_size_spin.valueChanged.connect(self._on_urgent_size)

        urgent_color_btn = self._color_button("urgent_fullscreen_color", self._on_urgent_color)

        self.urgent_style_combo = QComboBox()
        self.urgent_style_combo.addItems(STYLE_NAMES)
        self.urgent_style_combo.setCurrentIndex(self.s.urgent_fullscreen_style_index)
        self.urgent_style_combo.currentIndexChanged.connect(self._on_urgent_style)

        root.addLayout(self._captioned_row([
            ("Увеличение размера", self.urgent_size_spin, 1),
            ("Цвет", urgent_color_btn, 1),
            ("Начертание", self.urgent_style_combo, 1),
        ]))

        # ---- программа
        root.addWidget(self._section("Программа"))
        form2 = QFormLayout()
        form2.setSpacing(8)
        form2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        root.addLayout(form2)
        self.tray_combo = QComboBox()
        self.tray_combo.addItems(["Открывать основное окно", "Ничего"])
        self.tray_combo.setCurrentIndex(self.s.tray_action_index)
        self.tray_combo.currentIndexChanged.connect(self._on_tray_action)
        form2.addRow("Клик по иконке в трее", self.tray_combo)

        self.autostart_cb = QCheckBox("Запускать вместе с Windows (в трей)")
        self.autostart_cb.setChecked(self.s.autostart)
        self.autostart_cb.toggled.connect(self._on_autostart)
        root.addWidget(self.autostart_cb)

        update_row = QHBoxLayout()
        self.auto_update_cb = QCheckBox("Проверять обновления")
        self.auto_update_cb.setChecked(self.s.auto_update_check)
        self.auto_update_cb.toggled.connect(self._on_auto_update)
        self.update_interval_combo = QComboBox()
        for hours in CHECK_INTERVAL_CHOICES:
            self.update_interval_combo.addItem(UPDATE_INTERVAL_NAMES[hours], hours)
        self._select_update_interval(self.s.update_check_hours)
        self.update_interval_combo.setEnabled(self.s.auto_update_check)
        self.update_interval_combo.currentIndexChanged.connect(self._on_update_interval)
        check_btn = QPushButton("Проверить сейчас")
        check_btn.clicked.connect(self._on_check_updates)
        update_row.addWidget(self.auto_update_cb)
        update_row.addWidget(self.update_interval_combo, 1)
        update_row.addWidget(check_btn)
        root.addLayout(update_row)
        root.addStretch(1)

        # ---- кнопки — вне прокрутки, всегда видны
        footer = QVBoxLayout()
        footer.setContentsMargins(12, 0, 12, 0)
        footer.setSpacing(6)
        buttons = QHBoxLayout()
        preview_btn = QPushButton("Предпросмотр")
        preview_btn.setProperty("accent", True)
        preview_btn.clicked.connect(self._on_preview)
        reset_btn = QPushButton("Сбросить к настройкам по умолчанию")
        reset_btn.clicked.connect(self._reset_defaults)
        buttons.addWidget(preview_btn, 1)
        buttons.addWidget(reset_btn, 1)
        footer.addLayout(buttons)
        hint = QLabel("Все изменения сохраняются сразу.")
        hint.setProperty("caption", True)
        footer.addWidget(hint)
        outer.addLayout(footer)

        # Qt 6.12 потерял отступ текста в счётчиках — возвращаем (см. theme.SpinInsetFilter)
        for spin in self.findChildren(QSpinBox):
            fix_spin_inset(spin)
        self._fit_to_screen()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _section(title: str) -> QLabel:
        label = QLabel(title)
        label.setProperty("section", True)
        return label

    @staticmethod
    def _captioned(caption: str, widget: QWidget) -> QWidget:
        """Поле с маленькой подписью над ним."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        label = QLabel(caption)
        label.setProperty("caption", True)
        lay.addWidget(label)
        lay.addWidget(widget)
        return box

    def _captioned_row(self, items) -> QHBoxLayout:
        """Несколько полей с подписями в одну строку; третий элемент — доля ширины."""
        row = QHBoxLayout()
        row.setSpacing(8)
        for caption, widget, stretch in items:
            row.addWidget(self._captioned(caption, widget), stretch)
        return row

    @staticmethod
    def _pill_spin(value: int, handler) -> QSpinBox:
        spin = QSpinBox()
        spin.setProperty("spinPill", True)
        spin.setRange(1, 8)
        spin.setValue(value)
        spin.setAlignment(Qt.AlignCenter)
        spin.setFixedSize(64, 30)
        spin.valueChanged.connect(handler)
        return spin

    def _color_button(self, field: str, on_change) -> QPushButton:
        """Образец цвета с HEX-кодом; щелчок открывает выбор цвета (там же ввод HEX)."""
        hexv = str(getattr(self.s, field))
        btn = QPushButton()
        btn.setProperty("colorSwatch", True)
        btn.setFixedHeight(30)
        btn.setMinimumWidth(64)
        btn.setCursor(Qt.PointingHandCursor)
        self._refresh_color_btn(btn, hexv)
        self._color_refs[field] = (btn, on_change)

        def pick():
            current = QColor(str(getattr(self.s, field)))
            color = QColorDialog.getColor(current if current.isValid() else QColor("#FFFFFF"), self, "Выбор цвета")
            if color.isValid():
                new = color.name().upper()
                on_change(new)
                self._refresh_color_btn(btn, new)

        btn.clicked.connect(pick)
        return btn

    @staticmethod
    def _text_color_for(hexv: str) -> str:
        """Чёрный или белый — что контрастнее на этом фоне (относительная яркость WCAG)."""
        c = QColor(hexv)

        def lin(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        lum = 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())
        # контраст с белым (1.05/(L+0.05)) против контраста с чёрным ((L+0.05)/0.05)
        return "#000000" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#FFFFFF"

    @classmethod
    def _refresh_color_btn(cls, btn, hexv):
        hexv = (hexv or "").strip()
        text = hexv.upper() if HEX_RE.match(hexv) else hexv  # нестандартное значение показываем как есть
        fill = QColor(hexv)
        fill_name = fill.name().upper() if fill.isValid() else "#FFFFFF"
        btn.setText(text or fill_name)
        btn.setToolTip(f"{text or fill_name} — нажмите, чтобы выбрать цвет")
        btn.setStyleSheet(f"QPushButton {{ background-color: {fill_name}; color: {cls._text_color_for(fill_name)}; }}")

    def _fit_to_screen(self) -> None:
        """Размер по содержимому, но не выше доступной области экрана; минимальная
        высота маленькая — остальное прокручивается."""
        content = self._scroll.widget()
        hint = content.sizeHint()
        scrollbar = self._scroll.verticalScrollBar().sizeHint().width()
        footer_h = self.layout().sizeHint().height() - self._scroll.sizeHint().height()
        margins = self.layout().contentsMargins()
        # минимальная ширина — чтобы содержимое не обрезалось справа (горизонтальная прокрутка
        # появляется, только если экран уже этой ширины)
        min_width = content.minimumSizeHint().width() + scrollbar + margins.left() + margins.right() + 2
        width = max(560, hint.width() + scrollbar, min_width)
        height = hint.height() + max(0, footer_h)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            width = min(width, avail.width() - 40)
            height = min(height, avail.height() - 60)
        self.setMinimumSize(min(min_width, width), 320)
        self.resize(width, height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # окно целиком в пределах экрана (заголовок не уходит за край); экран — тот,
        # на котором окно сейчас, а не запомненный (важно для мониторов с x < 0)
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        x = min(max(frame.x(), avail.left()), max(avail.left(), avail.right() - frame.width() + 1))
        y = min(max(frame.y(), avail.top()), max(avail.top(), avail.bottom() - frame.height() + 1))
        if (x, y) != (frame.x(), frame.y()):
            self.move(x, y)

    # ------------------------------------------------------------------ handlers

    def _on_interval(self, value: int) -> None:
        self.s.reminder_interval_seconds = value * 60
        self.sm.save()

    def _on_done(self, index: int) -> None:
        self.s.show_done_in_fullscreen = index == 1
        self._sync_done_cols_visibility()
        self.sm.save()

    MAX_TOTAL_COLUMNS = MAX_TOTAL_COLUMNS

    def _max_allowed(self, key: str) -> int:
        """Максимум для колонки `key` при текущих значениях остальных."""
        done_visible = self.done_combo.currentIndex() == 1
        others = {
            "todo": self.s.fullscreen_columns_started + (self.s.fullscreen_columns_done if done_visible else 0),
            "started": self.s.fullscreen_columns_todo + (self.s.fullscreen_columns_done if done_visible else 0),
            "done": self.s.fullscreen_columns_todo + self.s.fullscreen_columns_started,
        }[key]
        return max(1, self.MAX_TOTAL_COLUMNS - others)

    def _on_cols_todo(self, value: int) -> None:
        clamped = min(value, self._max_allowed("todo"))
        self.s.fullscreen_columns_todo = clamped
        if self.cols_todo_spin.value() != clamped:
            self.cols_todo_spin.blockSignals(True)
            self.cols_todo_spin.setValue(clamped)
            self.cols_todo_spin.blockSignals(False)
        self.sm.save()

    def _on_cols_started(self, value: int) -> None:
        clamped = min(value, self._max_allowed("started"))
        self.s.fullscreen_columns_started = clamped
        if self.cols_started_spin.value() != clamped:
            self.cols_started_spin.blockSignals(True)
            self.cols_started_spin.setValue(clamped)
            self.cols_started_spin.blockSignals(False)
        self.sm.save()

    def _on_cols_done(self, value: int) -> None:
        clamped = min(value, self._max_allowed("done"))
        self.s.fullscreen_columns_done = clamped
        if self.cols_done_spin.value() != clamped:
            self.cols_done_spin.blockSignals(True)
            self.cols_done_spin.setValue(clamped)
            self.cols_done_spin.blockSignals(False)
        self.sm.save()

    def _sync_done_cols_visibility(self) -> None:
        visible = self.done_combo.currentIndex() == 1
        # прячется вся пара «Done (n)», а не только поле — иначе остаётся висящая подпись
        (self._cols_done_box or self.cols_done_spin).setVisible(visible)

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

    def _on_auto_remove(self, checked: bool) -> None:
        self.s.auto_remove_done = checked
        self.sm.save()

    def _on_auto_update(self, checked: bool) -> None:
        self.s.auto_update_check = checked
        self.update_interval_combo.setEnabled(checked)
        self.sm.save()

    def _on_update_interval(self, index: int) -> None:
        hours = self.update_interval_combo.itemData(index)
        if hours:
            self.s.update_check_hours = int(hours)
            self.sm.save()

    def _select_update_interval(self, hours) -> None:
        idx = self.update_interval_combo.findData(int(hours) if str(hours).isdigit() else DEFAULT_CHECK_HOURS)
        if idx < 0:
            idx = self.update_interval_combo.findData(DEFAULT_CHECK_HOURS)
        self.update_interval_combo.setCurrentIndex(idx)

    def _on_check_updates(self) -> None:
        if self._update_callback is not None:
            self._update_callback()

    def _on_preview(self) -> None:
        self._preview_callback()

    def set_preview_callback(self, callback) -> None:
        self._preview_callback = callback

    def set_update_callback(self, callback) -> None:
        self._update_callback = callback

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
        # служебная дата ежедневного сброса — не пользовательская настройка: если её обнулить,
        # ежедневная проверка посреди дня удалит Done и сбросит регулярные задачи
        reset_date = self.s.regular_reset_date
        self.s = Settings()
        self.s.regular_reset_date = reset_date
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
            self.cols_done_spin,
            self.monitor_combo,
            self.size_spin,
            self.font_combo,
            self.style_combo,
            self.align_combo,
            self.urgent_size_spin,
            self.urgent_style_combo,
            self.opacity_slider,
            self.autostart_cb,
            self.auto_remove_cb,
            self.auto_update_cb,
            self.update_interval_combo,
            self.tray_combo,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.interval_spin.setValue(s.reminder_interval_seconds // 60)
            self.done_combo.setCurrentIndex(1 if s.show_done_in_fullscreen else 0)
            self.cols_todo_spin.setValue(s.fullscreen_columns_todo)
            self.cols_started_spin.setValue(s.fullscreen_columns_started)
            self.cols_done_spin.setValue(s.fullscreen_columns_done)
            self._sync_done_cols_visibility()
            self._select_monitor(s.monitor_name)
            self.size_spin.setValue(s.text_size)
            idx = self.font_combo.findText(s.font_family)
            self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.style_combo.setCurrentIndex(s.font_style_index)
            self.align_combo.setCurrentIndex(s.alignment_index)
            self.urgent_size_spin.setValue(s.urgent_fullscreen_size_delta)
            self.urgent_style_combo.setCurrentIndex(s.urgent_fullscreen_style_index)
            self.opacity_slider.setValue(s.opacity_percent)
            self.opacity_label.setText(f"{s.opacity_percent}%")
            self.autostart_cb.setChecked(s.autostart)
            self.auto_remove_cb.setChecked(s.auto_remove_done)
            self.auto_update_cb.setChecked(s.auto_update_check)
            self._select_update_interval(s.update_check_hours)
            self.update_interval_combo.setEnabled(s.auto_update_check)
            self.tray_combo.setCurrentIndex(s.tray_action_index)
        finally:
            for w in widgets:
                w.blockSignals(False)
        # образцы цветов
        for field, (btn, _) in self._color_refs.items():
            self._refresh_color_btn(btn, str(getattr(s, field, "#FFFFFF")))
        # тема
        self.setStyleSheet(build_stylesheet(s.theme))