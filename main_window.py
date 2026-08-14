from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from drag_manager import TaskListWidget
from import_export import apply_import, export_tasks, load_tasks
from models import TaskLimitError, TaskStatus, TaskStore, next_status, prev_status, status_color
from theme import DARK, LIGHT, apply_titlebars, build_stylesheet, clear_icon, theme_icon
from version import APP_NAME, APP_RELEASE_DATE, APP_VERSION

EXPORT_FILTERS = [
    ("JSON (*.json)", "json"),
    ("TXT (*.txt)", "txt"),
    ("CSV (*.csv)", "csv"),
]
IMPORT_FILTERS = "Все поддерживаемые (*.json *.txt *.csv);;JSON (*.json);;TXT (*.txt);;CSV (*.csv)"


def build_help_html(theme: str) -> str:
    """HTML справки, стилизованный под текущую тему (прозрачный фон, без подложек)."""
    c = LIGHT if theme != "dark" else DARK
    accent = c["accent"] if theme != "dark" else "#6B9AFF"
    text = c["text"]
    muted = c["muted"]
    return f"""<html><body style="font-family:'Segoe UI','Arial'; font-size:14px; color:{text}; margin:0;">
<h2 style="font-size:22px; color:{accent}; border-bottom:2px solid {accent}; padding-bottom:6px; margin:0 0 14px 0;">ToDo Reminder — Справка</h2>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">1. Главное окно</h3>
<ul style="margin:0; padding-left:20px;">
<li>Поле ввода (сверху): напишите название дела и нажмите кнопку <b>✓</b> или клавишу <b>Enter</b>. Новые дела появляются <b>в самом верху</b> списка.</li>
<li>Ряд кнопок под полем ввода:
<ul style="margin:4px 0;">
<li><b>Импорт</b> — значок папки. Загрузка дел из <b>JSON / TXT / CSV</b>. Спросит: «Заменить» список или «Добавить» к текущему.</li>
<li><b>Экспорт</b> — значок дискеты. Сохраняет список в <b>JSON / TXT / CSV</b>.</li>
<li><b>«Настройки»</b> — окно настроек (пока открыто, главное окно недоступно).</li>
<li><b>Тема</b> — значок <b>луны/солнца</b>. Тёмная / светлая тема; шапки всех окон тоже меняются.</li>
<li><b>Очистить список</b> — красный крестик <b>✕</b>. Удаляет весь список только после подтверждения.</li>
<li><b>Справка</b> — значок «?», и <b>О программе</b> — значок «i».</li>
</ul></li>
</ul>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">2. Список задач</h3>
<ul style="margin:0; padding-left:20px;">
<li>Каждая карточка = <b>цветная кнопка статуса</b> + название.</li>
<li>Цвета статусов: <b>To Do — синий</b>, <b>Started — оранжевый</b>, <b>Done — зелёный</b> (меняются в настройках).</li>
<li>Выполненные дела (Done) <b>зачёркиваются</b>.</li>
<li><b>Перетаскивание:</b> зажмите карточку и перенесите вверх/вниз.</li>
<li><b>Переименование:</b> двойной клик по названию. <b>Enter</b> или <b>клик мышкой вне поля</b> — сохранить, <b>Esc</b> — отмена.</li>
<li><b>Правый клик</b> по карточке: «Переименовать», «Удалить», «Регулярное».</li>
</ul>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">3. Круговая схема статусов</h3>
<p style="margin:4px 0;">Клик по кнопке статуса меняет его <b>по кругу</b>. <b>ЛКМ</b> — вперёд, <b>ПКМ</b> — назад:</p>
<pre style="font-family:'Consolas','Courier New',monospace; font-size:13px; margin:6px 0; color:{text};">
ЛКМ:  To Do → Started → Done → To Do → …
ПКМ:  Done → Started → To Do → Done → …

 ┌───────┐   ┌──────────┐   ┌───────┐
 │ To Do │──▶│ Started  │──▶│ Done  │
 └───────┘   └──────────┘   └───────┘
   ▲                              │
   └────────────── ПКМ ────────────┘
</pre>
<p style="margin:4px 0; color:{muted}">Пример: дело «To Do» + ЛКМ → «Started»; ещё ЛКМ → «Done». Дело «Done» + ПКМ → «Started».</p>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">4. Регулярные задачи</h3>
<ul style="margin:0; padding-left:20px;">
<li><b>ПКМ</b> по карточке → пункт <b>«Регулярное»</b> (отмечается галочкой). Такие дела помечены значком <b>⟳</b>.</li>
<li>С наступлением <b>нового календарного дня</b> статус регулярного дела автоматически сбрасывается в <b>To Do</b> и оно поднимается в <b>самый верх</b> списка — даже если приложение было закрыто.</li>
</ul>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">5. Таймер и полноэкранное напоминание</h3>
<ul style="margin:0; padding-left:20px;">
<li>Слева внизу <b>большой таймер</b> — обратный отсчёт до напоминания.</li>
<li><b>Интервал:</b> круглые кнопки <b>−</b> и <b>+</b>, поле «мин», или ввод числа напрямую.</li>
<li><b>«Показать список»</b> (синяя кнопка) — мгновенно открыть полноэкранный список.</li>
<li><b>Чекбокс «Поверх всех окон»</b> — напоминание поверх остальных окон.</li>
<li>Напоминание — полноэкранный список по колонкам статусов, слева <b>от дела</b> цветная полоска-маркер. Закрыть: <b>клик мышкой</b> или <b>Enter / Space / Esc</b>.</li>
<li>Выполненные дела в напоминании по умолчанию скрыты (включается в настройках).</li>
</ul>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">6. Настройки</h3>
<ul style="margin:0; padding-left:20px;">
<li><b>Интервал напоминаний</b> (в минутах).</li>
<li><b>Выводить выполненные дела</b> в уведомлении.</li>
<li><b>Экран для уведомления</b> (если мониторов несколько).</li>
<li><b>Размер текста, шрифт, начертание, выравнивание</b> напоминания.</li>
<li><b>Фон</b> и <b>цвет текста</b> напоминания — работают в обеих темах.</li>
<li><b>Цвета статусов</b> To Do / Started / Done (карточки и маркеры).</li>
<li><b>Прозрачность</b> напоминания (0 % — непрозрачно).</li>
<li><b>Автозапуск</b> вместе с Windows (в трей).</li>
<li><b>Действие по клику в трее</b>: открыть окно / ничего.</li>
<li><b>«Предпросмотр»</b> и <b>«Сбросить к настройкам по-умолчанию»</b>.</li>
<li>Все изменения <b>сохраняются сразу</b>.</li>
</ul>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">7. Системный трей</h3>
<ul style="margin:0; padding-left:20px;">
<li>Закрытие главного окна <b>сворачивает приложение в трей</b> — оно продолжает работать.</li>
<li><b>ЛКМ</b> по значку в трее — вернуть окно (или ничего — по настройке).</li>
<li><b>ПКМ</b> по значку — меню: «Открыть основное окно», «Переместить окно на основной экран», «Выход».</li>
</ul>

<h3 style="color:{accent}; font-size:16px; margin:14px 0 6px 0;">8. Прочее</h3>
<ul style="margin:0; padding-left:20px;">
<li>Максимум — <b>100 дел</b>.</li>
<li>Позиция главного окна и настройки запоминаются.</li>
<li>Приложение <b>портативное</b>: данные хранятся в папке <b>data</b> рядом с EXE.</li>
</ul>
</body></html>"""


class MainWindow(QWidget):
    """Главное окно 300×700: ввод, один вертикальный список, кнопки и таймер внизу слева."""

    def __init__(self, ctx) -> None:
        super().__init__(None)
        self._ctx = ctx
        self._quitting = False
        self._pos_save_timer = QTimer(self)
        self._pos_save_timer.setSingleShot(True)
        self._pos_save_timer.setInterval(300)
        self._pos_save_timer.timeout.connect(self._save_position)

        self.setWindowTitle("ToDo Reminder")
        self.setFixedSize(300, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 4)
        root.setSpacing(6)

        # строка ввода
        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Название задачи")
        self.input_field.setMaxLength(TaskStore.MAX_TITLE)
        self.input_field.returnPressed.connect(self._add_task)
        add_btn = self._icon_btn(QStyle.StandardPixmap.SP_DialogApplyButton, "Добавить дело", self._add_task)
        input_row.addWidget(self.input_field, 1)
        input_row.addWidget(add_btn)
        root.addLayout(input_row)

        # кнопки: импорт/экспорт — иконки, настройки, тема, справка, о программе
        btn_row = QHBoxLayout()
        import_btn = self._icon_btn(QStyle.StandardPixmap.SP_DialogOpenButton, "Импорт задач (JSON / TXT / CSV)", self._import_dialog)
        export_btn = self._icon_btn(QStyle.StandardPixmap.SP_DialogSaveButton, "Экспорт задач (JSON / TXT / CSV)", self._export_dialog)
        settings_btn = QPushButton("Настройки")
        settings_btn.setFixedHeight(26)
        settings_btn.clicked.connect(self._open_settings)
        self.theme_btn = QPushButton()
        self.theme_btn.setProperty("iconBtn", True)
        self.theme_btn.setFixedSize(26, 26)
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setFocusPolicy(Qt.NoFocus)
        self.theme_btn.clicked.connect(self._toggle_theme)
        help_btn = self._icon_btn(QStyle.StandardPixmap.SP_MessageBoxQuestion, "Справка", self._show_help)
        clear_btn = self._icon_btn(QStyle.StandardPixmap.SP_TrashIcon, "Очистка списка дел", self._clear_tasks)
        clear_btn.setIcon(clear_icon())
        about_btn = self._icon_btn(QStyle.StandardPixmap.SP_MessageBoxInformation, "О программе", self._show_about)
        for b in (import_btn, export_btn, settings_btn, self.theme_btn, clear_btn, help_btn, about_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # список
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list = TaskListWidget(self._scroll)
        self._scroll.setWidget(self._list)
        root.addWidget(self._scroll, 1)

        # кнопка «Показать список» + чекбокс «Поверх всех окон»
        show_row = QHBoxLayout()
        self.show_list_btn = QPushButton("Показать список")
        self.show_list_btn.setProperty("accent", True)
        self.show_list_btn.setFixedHeight(26)
        self.show_list_btn.clicked.connect(self._show_task_list)
        self.on_top_cb = QCheckBox("Поверх всех окон")
        self.on_top_cb.setChecked(self._ctx.settings_manager.s.always_on_top)
        self.on_top_cb.toggled.connect(self._on_top_toggled)
        show_row.addWidget(self.show_list_btn)
        show_row.addWidget(self.on_top_cb)
        show_row.addStretch(1)
        root.addLayout(show_row)

        # таймер — большой по центру, поле минут с −/+ под ним
        bottom_box = QVBoxLayout()
        bottom_box.setSpacing(8)
        self.timer_label = QLabel("00:00")
        self.timer_label.setObjectName("timerLabel")
        self.timer_label.setAlignment(Qt.AlignCenter)
        bottom_box.addWidget(self.timer_label)

        interval_row = QHBoxLayout()
        interval_row.setSpacing(10)
        self.minus_btn = QPushButton("−")
        self.plus_btn = QPushButton("+")
        for b in (self.minus_btn, self.plus_btn):
            b.setProperty("roundBtn", True)
            b.setFixedSize(30, 30)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
        self.minus_btn.clicked.connect(self._minus_minute)
        self.plus_btn.clicked.connect(self._plus_minute)
        self.interval_spin = QSpinBox()
        self.interval_spin.setProperty("spinPill", True)
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.interval_spin.setAlignment(Qt.AlignCenter)
        self.interval_spin.setSuffix(" мин")
        self.interval_spin.setFixedSize(96, 30)
        self.interval_spin.setValue(max(1, self._ctx.settings_manager.s.reminder_interval_seconds // 60))
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        interval_row.addStretch(1)
        interval_row.addWidget(self.minus_btn)
        interval_row.addWidget(self.interval_spin)
        interval_row.addWidget(self.plus_btn)
        interval_row.addStretch(1)
        bottom_box.addLayout(interval_row)
        root.addLayout(bottom_box)

        # связи
        self._list.taskMoved.connect(self._on_task_moved)
        self._list.statusCycleRequested.connect(self._on_status_cycle)
        self._list.statusReverseRequested.connect(self._on_status_reverse)
        self._list.rename_handler = self._rename_task
        self._list.delete_handler = self._delete_task
        self._list.regular_toggle_handler = self._toggle_regular

        self.apply_theme()
        self.refresh(animate=False)
        self._restore_position()
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------ данные

    def store(self) -> TaskStore:
        return self._ctx.store

    def refresh(self, animate: bool = True) -> None:
        s = self._ctx.settings_manager.s
        self._list.status_colors = {st: status_color(st, s) for st in TaskStatus}
        self._list.rebuild(self.store().tasks, animate=animate)

    def save_data(self) -> None:
        self._ctx.save_data()

    def sync_status_colors(self) -> None:
        """Применяет изменённые в настройках цвета статусов к карточкам списка."""
        s = self._ctx.settings_manager.s
        new = {st: status_color(st, s) for st in TaskStatus}
        if new != getattr(self._list, "status_colors", None):
            self._list.status_colors = new
            self._list.rebuild(self.store().tasks, animate=False)

    # ------------------------------------------------------------------ задачи

    def _add_task(self) -> None:
        text = self.input_field.text()
        try:
            self.store().add(text)
        except TaskLimitError as e:
            QMessageBox.warning(self, "Ограничение", str(e))
            return
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self.input_field.clear()
        self.save_data()
        self.refresh()
        self.input_field.setFocus()

    def _rename_task(self, task, new_title: str) -> bool:
        index = self._index_of(task)
        if index < 0:
            return False
        try:
            self.store().rename(index, new_title)
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
            return False
        self.save_data()
        # обновляем карточку на месте, без пересборки списка:
        # пересборка внутри обработчика клика сломала бы активное редактирование
        tw = self._list.widget_by_task(task)
        if tw is not None:
            tw.label.setText(tw._display_title())
        return True

    def _delete_task(self, task) -> None:
        index = self._index_of(task)
        if index < 0:
            return
        self.store().remove(index)
        self.save_data()
        self.refresh()

    def _toggle_regular(self, task) -> None:
        index = self._index_of(task)
        if index < 0:
            return
        self.store().set_regular(index, not self.store().tasks[index].regular)
        self.save_data()
        self.refresh()

    def _clear_tasks(self) -> None:
        if not self.store().tasks:
            return
        answer = QMessageBox.question(
            self,
            "Очистка списка дел",
            "Вы действительно хотите очистить весь список дел?\n"
            "Удалятся все задачи без возможности восстановления.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.store().tasks.clear()
        self.save_data()
        self.refresh()

    def _index_of(self, task) -> int:
        for i, t in enumerate(self.store().tasks):
            if t.id == task.id:
                return i
        return -1

    def _on_status_cycle(self, task) -> None:
        if self._list.dragging:
            return
        index = self._index_of(task)
        if index < 0:
            return
        self.store().set_status(index, next_status(task.status))
        self.save_data()
        self.refresh()

    def _on_status_reverse(self, task) -> None:
        if self._list.dragging:
            return
        index = self._index_of(task)
        if index < 0:
            return
        self.store().set_status(index, prev_status(task.status))
        self.save_data()
        self.refresh()

    def _on_task_moved(self, from_index: int, to_slot: int) -> None:
        self.store().move_to_slot(from_index, to_slot)
        self.save_data()
        self.refresh()

    # ------------------------------------------------------------------ import/export

    def _export_dialog(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self, "Экспорт задач", "", ";;".join(f for f, _ in EXPORT_FILTERS)
        )
        if not path:
            return
        fmt = None
        for f, code in EXPORT_FILTERS:
            if f in selected:
                fmt = code
                break
        if fmt is None:
            lower = path.lower()
            for _, code in EXPORT_FILTERS:
                if path.endswith("." + code):
                    fmt = code
                    break
        if fmt is None:
            fmt = "json"
            path += ".json"
        try:
            export_tasks(path, fmt, self.store())
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))

    def _import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт задач", "", IMPORT_FILTERS)
        if not path:
            return
        lower = path.lower()
        fmt = "txt" if lower.endswith(".txt") else "csv" if lower.endswith(".csv") else "json"
        try:
            items = load_tasks(path, fmt)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))
            return
        if not items:
            QMessageBox.information(self, "Импорт", "В файле нет задач.")
            return
        answer = QMessageBox.question(
            self,
            "Режим импорта",
            f"Найдено задач: {len(items)}\nКак импортировать?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Cancel:
            return
        mode = "replace" if answer == QMessageBox.Yes else "add"
        added = apply_import(self.store(), items, mode)
        self.save_data()
        self.refresh()
        total = len(self.store())
        msg = f"Импортировано задач: {added}. Всего в списке: {total}."
        if added < len(items):
            msg += f"\nДостигнут лимит 100 — остальные пропущены."
        QMessageBox.information(self, "Импорт", msg)

    def _icon_btn(self, pixmap: QStyle.StandardPixmap, tooltip: str, slot) -> QPushButton:
        btn = QPushButton()
        btn.setIcon(self.style().standardIcon(pixmap))
        btn.setProperty("iconBtn", True)
        btn.setFixedSize(26, 26)
        btn.setToolTip(tooltip)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    # ------------------------------------------------------------------ тема

    def apply_theme(self) -> None:
        self._dark = self._ctx.settings_manager.s.theme == "dark"
        self.setStyleSheet(build_stylesheet(self._ctx.settings_manager.s.theme))
        for w in self.findChildren(QWidget):
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        apply_titlebars(QApplication.instance(), self._dark)
        self._update_theme_btn()

    def _update_theme_btn(self) -> None:
        if hasattr(self, "theme_btn"):
            theme = self._ctx.settings_manager.s.theme
            self.theme_btn.setIcon(theme_icon(theme))
            self.theme_btn.setToolTip("Тёмная тема" if theme == "light" else "Светлая тема")

    def _toggle_theme(self) -> None:
        from theme import DARK, LIGHT
        s = self._ctx.settings_manager.s
        target = "dark" if s.theme != "dark" else "light"
        c = DARK if target == "dark" else LIGHT
        # подставляем дефолтные цвета напоминания под новую тему, только если они
        # ещё не кастомизированы пользователем (равны какому-либо дефолту темы)
        if s.bg_color in (LIGHT["reminder_bg"], DARK["reminder_bg"]):
            s.bg_color = c["reminder_bg"]
        if s.text_color in (LIGHT["reminder_text"], DARK["reminder_text"]):
            s.text_color = c["reminder_text"]
        s.theme = target
        self._ctx.save_settings()
        self.apply_theme()

    def sync_theme(self) -> None:
        """Применяет тему главного окна, если она изменилась извне (например, из настроек)."""
        s = self._ctx.settings_manager.s
        if getattr(self, "_dark", None) != (s.theme == "dark"):
            self.apply_theme()

    def _open_settings(self) -> None:
        self._ctx.open_settings(self)

    def _show_help(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Справка — ToDo Reminder")
        dlg.setWindowModality(Qt.NonModal)
        dlg.resize(480, 600)
        dlg.setStyleSheet(build_stylesheet(self._ctx.settings_manager.s.theme))
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(build_help_html(self._ctx.settings_manager.s.theme))
        lay.addWidget(browser, 1)
        close_btn = QPushButton("Закрыть")
        close_btn.setProperty("accent", True)
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.show()

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("О программе")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<b>{APP_NAME}</b><br>Версия {APP_VERSION} ({APP_RELEASE_DATE}).<br><br>"
            "Это приложение сделал iLeech для своей любимой Twiggi Light.<br>"
            "Я потратил на эту приложуху все токены, которые у меня были, "
            "и сделал бы это для тебя еще тысячу раз не задумываясь ни на секунду &lt;3<br><br>"
            '<a href="https://github.com/Mike-iLeech/ToDoReminder">Проект на GitHub</a>'
        )
        for label in box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
            label.setTextFormat(Qt.RichText)
        box.exec()

    # ------------------------------------------------------------------ окно

    def focus_input(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus()

    def _restore_position(self) -> None:
        s = self._ctx.settings_manager.s
        if s.window_x != -9999 and s.window_y != -9999:
            self.move(s.window_x, s.window_y)
        else:
            self._center_on_screen(self.primary_screen())
        self._ensure_visible()

    def _center_on_screen(self, screen) -> None:
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def _ensure_visible(self) -> None:
        visible = False
        for screen in QGuiApplication.screens():
            if self.frameGeometry().intersects(screen.availableGeometry()):
                visible = True
                break
        if not visible:
            self._center_on_screen(self.primary_screen())

    @staticmethod
    def primary_screen():
        return QGuiApplication.primaryScreen()

    def move_to_primary_screen(self) -> None:
        self._center_on_screen(self.primary_screen())
        self._save_position()

    def _save_position(self) -> None:
        s = self._ctx.settings_manager.s
        pos = self.pos()
        s.window_x = pos.x()
        s.window_y = pos.y()
        self._ctx.save_settings()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._pos_save_timer.start()

    def eventFilter(self, obj, event) -> bool:
        # клик вне переименовываемой карточки — выйти из режима переименования
        if event.type() == QEvent.MouseButtonPress:
            edited = self._list.active_edit_widget()
            if edited is not None:
                w = QApplication.widgetAt(event.globalPosition().toPoint())
                if w is not edited and w is not edited._edit:
                    self._list.cancel_edit()
        return super().eventFilter(obj, event)

    def set_timer_text(self, text: str) -> None:
        self.timer_label.setText(text)

    def _on_interval_changed(self, value: int) -> None:
        self._ctx.settings_manager.s.reminder_interval_seconds = value * 60
        self._ctx.save_settings()

    def _minus_minute(self) -> None:
        self.interval_spin.stepDown()

    def _plus_minute(self) -> None:
        self.interval_spin.stepUp()

    def _show_task_list(self) -> None:
        self._ctx.show_task_list()

    def sync_on_top_cb(self) -> None:
        if hasattr(self, "on_top_cb"):
            wanted = self._ctx.settings_manager.s.always_on_top
            if self.on_top_cb.isChecked() != wanted:
                self.on_top_cb.setChecked(wanted)

    def _on_top_toggled(self, checked: bool) -> None:
        self._ctx.settings_manager.s.always_on_top = checked
        self._ctx.save_settings()
        if self._ctx.show_list_win is not None:
            self._ctx.show_list_win.set_always_on_top(checked)

    def sync_interval_spin(self) -> None:
        if hasattr(self, "interval_spin"):
            minutes = max(1, self._ctx.settings_manager.s.reminder_interval_seconds // 60)
            if self.interval_spin.value() != minutes:
                self.interval_spin.setValue(minutes)

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
            return
        # закрытие = сворачивание в трей; приложение продолжает работать
        self._save_position()
        self.hide()
        event.ignore()