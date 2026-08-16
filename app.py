from __future__ import annotations

import sys
from datetime import date

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from main_window import MainWindow
from models import Task, TaskStatus, TaskStore
from reminder_window import ReminderWindow
from settings import SETTINGS_PATH, TASKS_PATH, SettingsManager
from storage import JsonFile
from system_tray import SystemTray, make_app_icon
from theme import TitlebarFilter


def preview_tasks() -> list:
    """Тестовый набор для предпросмотра (не реальные задачи).

    Подобран так, чтобы показать все возможные варианты заполнения колонок
    с делами: короткие и длинные однострочные названия, многострочные,
    односложные слова, длинные слова, цифры и даты.
    """
    samples = [
        ("Выпить кофе", TaskStatus.TO_DO, False),
        ("Купить продукты", TaskStatus.TO_DO, True),
        ("Хлеб, сок, чай, суп", TaskStatus.TO_DO, False),
        ("Бег\nСон\nДуш", TaskStatus.TO_DO, False),
        ("Подготовиться к экзамену\nПовторить интегралы и производные\nРешить 20 задач", TaskStatus.STARTED, True),
        ("Сдать отчёт до 01.09.2026", TaskStatus.STARTED, False),
        ("Изучить электроэнцефалографию", TaskStatus.STARTED, False),
        ("Пройти высококвалифицированное переосвидетельствование", TaskStatus.STARTED, False),
        ("Написать курсовую работу по истории информатики и подготовить презентацию на двадцать слайдов с иллюстрациями, диаграммами и примерами кода", TaskStatus.DONE, True),
        ("Сделать зарядку\nПрогулка на свежем воздухе\nМедитация 10 минут", TaskStatus.DONE, False),
        ("Дочитать главу", TaskStatus.DONE, False),
    ]
    result = []
    for title, status, urgent in samples:
        task = Task.create(title)
        task.status = status
        task.urgent = urgent
        result.append(task)
    return result


class ReminderManager(QObject):
    """РўР°Р№РјРµСЂ РЅР°РїРѕРјРёРЅР°РЅРёР№: РїРѕР»РЅС‹Р№ РѕС‚СЃС‡С‘С‚ РїРѕСЃР»Рµ Р·Р°РїСѓСЃРєР°, СЃРєСЂС‹С‚РёСЏ, СЃРјРµРЅС‹ РёРЅС‚РµСЂРІР°Р»Р°."""

    def __init__(self, ctx) -> None:
        super().__init__()
        self._ctx = ctx
        self._interval = ctx.settings_manager.s.reminder_interval_seconds
        self._remaining = self._interval
        self._reminder = None
        self._one_second = QTimer(self)
        self._one_second.setInterval(1000)
        self._one_second.timeout.connect(self._tick)
        self._one_second.start()
        self._update_label()

    # ------------------------------------------------------------------ timer

    def _tick(self) -> None:
        if self._reminder is not None and self._reminder.isVisible():
            return
        self._remaining -= 1
        self._update_label()
        if self._remaining <= 0:
            self._fire()

    def _fmt(self) -> str:
        s = max(0, self._remaining)
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    def _update_label(self) -> None:
        self._ctx.main_window.set_timer_text(self._fmt())

    # ------------------------------------------------------------------ reminder

    def _fire(self) -> None:
        if self._reminder is not None and self._reminder.isVisible():
            # РЅРµ СЃРѕР·РґР°РІР°С‚СЊ РІС‚РѕСЂРѕРµ РѕРєРЅРѕ вЂ” РѕР±РЅРѕРІРёС‚СЊ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РµРµ
            self._reminder.set_tasks(self._collect_tasks())
            return
        screen = self._selected_screen()
        win = ReminderWindow(self._ctx.settings_manager.s, self._collect_tasks())
        win.hiddenRequested.connect(lambda w=win: self._on_reminder_hidden(w))
        win.attach_to_screen(screen)
        self._reminder = win
        self._one_second.stop()

    def _collect_tasks(self):
        s = self._ctx.settings_manager.s
        if s.show_done_in_fullscreen:
            return list(self._ctx.store.tasks)
        return self._ctx.store.active_tasks()

    def _on_reminder_hidden(self, win) -> None:
        if self._reminder is win:
            self._reminder = None
        self.restart_full()

    def _selected_screen(self):
        name = self._ctx.settings_manager.s.monitor_name
        if name:
            for scr in QGuiApplication.screens():
                if scr.name() == name:
                    return scr
        return QGuiApplication.primaryScreen()

    # ------------------------------------------------------------------ lifecycle

    def restart_full(self) -> None:
        self._remaining = self._interval
        self._one_second.start()
        self._update_label()

    def on_settings_changed(self) -> None:
        new_interval = self._ctx.settings_manager.s.reminder_interval_seconds
        if new_interval != self._interval:
            self._interval = new_interval
            self.restart_full()
        self._update_label()

    def shutdown(self) -> None:
        self._one_second.stop()


class AppContext:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.settings_manager = SettingsManager()
        self.store = TaskStore()
        self.task_file = JsonFile(TASKS_PATH)
        self._load_tasks()

        self.main_window: MainWindow = None
        self.tray: SystemTray = None
        self.reminders: ReminderManager = None
        self.settings_dialog = None
        self.preview_window = None
        self.show_list_win = None

        # ежедневный сброс статусов регулярных задач (проверка раз в час)
        self._daily_timer = QTimer()
        self._daily_timer.setInterval(3600000)
        self._daily_timer.timeout.connect(self._daily_check)
        self._daily_timer.start()
        self._daily_check()

    def _daily_check(self) -> None:
        """Новое календарное число → статусы регулярных задач сбрасываются в To Do, Done удаляются."""
        today = date.today().isoformat()
        stored = self.settings_manager.s.regular_reset_date
        if stored == today:
            return
        changed = self.store.reset_regular_to_todo()
        removed = self.store.remove_done()
        self.settings_manager.s.regular_reset_date = today
        self.settings_manager.save()
        if changed or removed:
            self.save_data()
            if self.main_window is not None:
                self.main_window.refresh()
        self.show_list_win = None

    def _startup_cleanup(self) -> None:
        """При запуске приложения удаляет все Done-задачи."""
        removed = self.store.remove_done()
        if removed:
            self.save_data()
            if self.main_window is not None:
                self.main_window.refresh()

    def _load_tasks(self) -> None:
        self.store.load_dict(self.task_file.load({}))

    def save_data(self) -> None:
        self.task_file.save(self.store.to_dict())

    def save_settings(self) -> None:
        self.settings_manager.save()

    def open_main_window(self) -> None:
        self.main_window.focus_input()

    def move_to_primary_screen(self) -> None:
        self.main_window.move_to_primary_screen()

    def open_settings(self, parent=None) -> None:
        from settings_window import SettingsDialog

        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        screens = QGuiApplication.screens()
        dlg = SettingsDialog(self.settings_manager, screens, parent)
        dlg.set_preview_callback(self.open_preview)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.finished.connect(lambda _: setattr(self, "settings_dialog", None))
        self.settings_dialog = dlg
        dlg.show()

    def open_preview(self) -> None:
        screen = self.reminders._selected_screen()
        if self.preview_window is not None:
            self.preview_window.close()
            self.preview_window = None
        win = ReminderWindow(self.settings_manager.s, preview_tasks(), is_preview=True)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.hiddenRequested.connect(lambda w=win: self._clear_preview(w))
        win.attach_to_screen(screen)
        self.preview_window = win

    def _clear_preview(self, win) -> None:
        if self.preview_window is win:
            self.preview_window = None

    def show_task_list(self) -> None:
        """РљРЅРѕРїРєР° В«РџРѕРєР°Р·Р°С‚СЊ СЃРїРёСЃРѕРєВ»: РїРѕР»РЅРѕСЌРєСЂР°РЅРЅС‹Р№ СЃРїРёСЃРѕРє Р·Р°РґР°С‡ РЅР° РІС‹Р±СЂР°РЅРЅРѕРј РјРѕРЅРёС‚РѕСЂРµ."""
        if self.show_list_win is not None:
            self.show_list_win.close()
            self.show_list_win = None
        screen = self.reminders._selected_screen()
        win = ReminderWindow(self.settings_manager.s, self.reminders._collect_tasks())
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        win.hiddenRequested.connect(lambda w=win: self._clear_show_list(w))
        win.attach_to_screen(screen)
        self.show_list_win = win

    def _clear_show_list(self, win) -> None:
        if self.show_list_win is win:
            self.show_list_win = None

    def quit(self) -> None:
        if self.main_window is not None:
            self.main_window._quitting = True
            self.main_window._save_position()
        if self.reminders is not None:
            self.reminders.shutdown()
        self.settings_manager.save()
        if self.tray is not None:
            self.tray.hide()
            self.app.processEvents()
        self.app.quit()


def run(argv=None) -> None:
    if argv is None:
        argv = sys.argv
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationDisplayName("ToDo Reminder")
    app.setApplicationName("ToDoReminder")
    app.setOrganizationName("ToDoReminder")
    app.setWindowIcon(make_app_icon())
    app._titlebar_filter = TitlebarFilter()
    app.installEventFilter(app._titlebar_filter)

    ctx = AppContext(app)

    ctx._startup_cleanup()

    main_window = MainWindow(ctx)
    ctx.main_window = main_window

    tray = SystemTray(ctx.settings_manager, ctx)
    ctx.tray = tray

    reminders = ReminderManager(ctx)
    ctx.reminders = reminders
    ctx.settings_manager.changed.connect(reminders.on_settings_changed)
    ctx.settings_manager.changed.connect(ctx.main_window.sync_interval_spin)
    ctx.settings_manager.changed.connect(ctx.main_window.sync_on_top_cb)
    ctx.settings_manager.changed.connect(ctx.main_window.sync_status_colors)
    ctx.settings_manager.changed.connect(ctx.main_window.sync_theme)

    tray.show()
    if "--hide" in sys.argv:
        main_window.hide()
    else:
        main_window.show()

    sys.exit(app.exec())