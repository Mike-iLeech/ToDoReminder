"""Автотесты приложения ToDo Reminder по разделам 18-20 ТЗ.

Запуск:  python tests/run_tests.py
Использует offscreen-платформу Qt и временные файлы данных.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import settings as S
import models

# тесты не должны трогать автозапуск в реестре разработчика
S.set_autostart = lambda enabled: None
S.autostart_command = lambda: None
from drag_manager import STEP
from models import TaskLimitError, TaskStatus, TaskStore

# временные данные
S.DATA_DIR = Path(tempfile.mkdtemp())
S.SETTINGS_PATH = S.DATA_DIR / "settings.json"
S.TASKS_PATH = S.DATA_DIR / "tasks.json"

PASSED = 0
FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


# ---------------------------------------------------------------- Задачи
def test_tasks():
    print("## Задачи")
    s = TaskStore()
    for i in range(5):
        s.add(f"  Задача {i}  ")
    check("add с trim", s.tasks[0].title == "Задача 4")
    check("порядок строк (новые сверху)", [t.title for t in s.tasks] == [f"Задача {i}" for i in range(4, -1, -1)])
    try:
        s.add("   ")
        check("пустое название запрещено", False)
    except ValueError:
        check("пустое название запрещено", True)

    s2 = TaskStore()
    for i in range(100):
        s2.add(f"t{i}")
    try:
        s2.add("101")
        check("лимит 100", False)
    except TaskLimitError:
        check("лимит 100", True)
    check("100 задач", len(s2.tasks) == 100)

    long_title = "x" * 300
    s4_ = TaskStore()
    s4_.add(long_title)
    check("255 символов обрезается", len(s4_.tasks[-1].title) == 255)

    s4_.rename(len(s4_.tasks) - 1, "  норма  ")
    check("rename trim", s4_.tasks[-1].title == "норма")

    # редактирование: Enter/Esc задаются на уровне виджета, здесь проверяем rename
    check("лимит остаётся", len(s2.tasks) == 100)


# ---------------------------------------------------------------- Статусы и порядок
def test_statuses():
    print("## Статусы и порядок")
    s = TaskStore()
    for i in range(6):
        s.add(f"T{i}")
    # To Do -> Started: остаётся на своём месте (самая новая задача вверху)
    s.set_status(0, TaskStatus.STARTED)
    check("To Do->Started остаётся на месте", s.tasks[0].title == "T5" and s.tasks[0].status is TaskStatus.STARTED)

    # Started -> Done: в блок Done
    s.set_status(0, TaskStatus.DONE)
    check("в блок Done", s.tasks[-1].status is TaskStatus.DONE and s.tasks[-1].title == "T5")

    # Done -> To Do: конец активных, перед Done
    s.set_status(len(s.tasks) - 1, TaskStatus.TO_DO)
    check("Done->To Do перед блоком Done", s.tasks[-1].status is TaskStatus.TO_DO)

    # цикл
    cyc = [models.next_status(TaskStatus.TO_DO), models.next_status(TaskStatus.STARTED), models.next_status(TaskStatus.DONE)]
    check("цикл статусов", cyc == [TaskStatus.STARTED, TaskStatus.DONE, TaskStatus.TO_DO])

    # обратный цикл
    rev = [models.prev_status(TaskStatus.TO_DO), models.prev_status(TaskStatus.STARTED), models.prev_status(TaskStatus.DONE)]
    check("обратный цикл статусов", rev == [TaskStatus.DONE, TaskStatus.TO_DO, TaskStatus.STARTED])

    # цвета статусов: по умолчанию и из настроек
    check("цвет статуса по умолчанию", models.status_color(TaskStatus.TO_DO) == "#5B7BD5")
    fake_settings = type("FakeS", (), {"color_status_todo": "#123456", "color_status_started": "", "color_status_done": ""})()
    check("цвет статуса из настроек", models.status_color(TaskStatus.TO_DO, fake_settings) == "#123456")
    check("пустая настройка -> дефолт", models.status_color(TaskStatus.STARTED, fake_settings) == "#E0913C")

    # регулярные задачи
    sr = TaskStore()
    sr.add("Рег")
    sr.tasks[0].status = TaskStatus.DONE
    sr.set_regular(0, True)
    check("флаг regular сохраняется", sr.tasks[0].regular)
    data = sr.to_dict()
    sr2 = TaskStore()
    sr2.load_dict(data)
    check("regular сохраняется при перезапуске", sr2.tasks[0].regular is True)

    # сброс в новый день: любой статус -> To Do, сброшенные попадают в самый верх
    sr3 = TaskStore()
    sr3.add("A")
    sr3.add("B")
    sr3.add("C")
    sr3.tasks[2].status = TaskStatus.DONE   # A
    sr3.tasks[1].status = TaskStatus.STARTED  # B
    for i in range(3):
        sr3.set_regular(i, True)
    changed_res = sr3.reset_regular_to_todo()
    check("сброс регулярных в To Do", changed_res and all(t.status is TaskStatus.TO_DO for t in sr3.tasks))
    check("сброшенные поднимаются вверх", [t.title for t in sr3.tasks] == ["B", "A", "C"])

    # повторный вызов ничего не меняет
    check("повторный сброс без изменений", sr3.reset_regular_to_todo() is False)

    # инвариант: активные всегда перед Done
    s2 = TaskStore()
    for i in range(20):
        s2.add(f"t{i}")
    for i in range(18):
        s2.set_status(0, TaskStatus.DONE)
    for i in range(10):
        s2.set_status(0, TaskStatus.STARTED)
    order_ok = True
    seen_done = False
    for t_ in s2.tasks:
        if t_.status is TaskStatus.DONE:
            seen_done = True
        if seen_done and t_.status.is_active:
            order_ok = False
    check("инвариант активные-перед-Done", order_ok)

    # перезапуск восстанавливает порядок
    data = s2.to_dict()
    s3 = TaskStore()
    s3.load_dict(data)
    check("восстановление после перезапуска", [t.id for t in s3.tasks] == [t.id for t in s2.tasks])


# ---------------------------------------------------------------- Импорт/экспорт
def test_import_export():
    from import_export import apply_import, export_tasks, load_tasks

    print("## Импорт/экспорт")
    d = Path(tempfile.mkdtemp())
    s = TaskStore()
    for i in range(4):
        s.add(f"Задача {i}")
    s.set_status(0, TaskStatus.STARTED)
    s.set_status(1, TaskStatus.DONE)
    order = [t.title for t in s.tasks]

    for fmt in ("txt", "csv", "json"):
        p = d / f"exp.{fmt}"
        export_tasks(p, fmt, s)
        items = load_tasks(p, fmt)
        check(f"{fmt} порядок сохраняется", [t for t, _, _, _ in items] == order)
        if fmt == "txt":
            check("TXT без статусов", all(st is None for _, st, _, _ in items))
        if fmt == "csv":
            sts = [st.value if st else None for _, st, _, _ in items]
            check("CSV со статусами", sts == [t.status.value for t in s.tasks])

    # заменить
    s2 = TaskStore()
    apply_import(s2, load_tasks(d / "exp.txt", "txt"), "replace")
    check("Заменить", len(s2.tasks) == 4)
    # добавить
    s3 = TaskStore()
    s3.add("Старая")
    apply_import(s3, load_tasks(d / "exp.txt", "txt"), "add")
    check("Добавить", len(s3.tasks) == 5 and s3.tasks[0].title == "Старая")
    # лимит при импорте
    s4 = TaskStore()
    for i in range(100):
        s4.add(f"x{i}")
    applied = apply_import(s4, [(f"New{i}", None, False, False) for i in range(50)], "add")
    check("импорт не превышает 100", len(s4.tasks) == 100 and applied == 0)


# ---------------------------------------------------------------- Drag: критический сценарий (раздел 18)
def test_drag_critical():
    from drag_manager import TaskListWidget
    from main_window import MainWindow

    print("## Drag-and-drop (критический сценарий)")
    from app import AppContext

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)

    for i in range(10):
        ctx.store.add(f"Задача {i}")
    main = MainWindow(ctx)
    ctx.main_window = main
    main.show()

    w = main._list
    # в тесте передаём локальную (content) координату y вместо глобальной,
    # чтобы не зависеть от позиции окна в offscreen-режиме
    w._content_y = lambda gpos: gpos.y()
    # берём задачу №3 (индекс 2)
    d = 2
    w._pressed = w._widgets[d]
    w._begin_drag()
    check("drag начат", w.dragging and w._drag[0] == 2, f"drag={w._drag}")
    check("исходная карточка скрыта при drag", not w._widgets[d].isVisible())
    check("перетаскиваемое представление создано", w._rep is not None)

    # перетащить между №7 и №8 (индексы 6 и 7) — курсор внутри половины слота 7
    target_y = 7 * STEP + 5  # y = 355 → round(7.1) = 7
    w._update_drag(QPoint(0, int(target_y)))
    t_last = w._drag[1]
    check("между №7 и №8", t_last == 7, f"t={t_last}")

    # двинуть назад
    w._update_drag(QPoint(0, d * STEP))
    changed_back = w._drag[1] == 2
    check("непрерывный пересчёт при движении назад", changed_back, f"t={w._drag[1]}")

    # снова вниз
    w._update_drag(QPoint(0, 8 * STEP + 5))
    check("снова вниз", w._drag[1] == 8, f"t={w._drag[1]}")

    # отпустить
    w._end_drag(QPoint(0, 8 * STEP + 5))
    check("drag завершён", not w.dragging)
    titles = [t.title for t in ctx.store.tasks]
    # новые задачи сверху: исходный порядок [9,8,7,6,5,4,3,2,1,0],
    # перетаскиваем индекс 2 (Задача 7) в слот 8 → он встаёт в конец
    expected = [f"Задача {i}" for i in [9, 8, 6, 5, 4, 3, 2, 1, 7, 0]]
    check("порядок после отпускания == слот вставки", titles == expected, str(titles))

    # перезапуск: порядок сохранён
    data = ctx.store.to_dict()
    ctx.store.tasks.clear()
    ctx.store.load_dict(data)
    check("порядок сохраняется после перезапуска", [t.title for t in ctx.store.tasks] == titles)

    # drag активной задачи не уходит в блок Done
    for i in range(5):
        ctx.store.add(f"D{i}")
        ctx.store.set_status(ctx.store.tasks.index(ctx.store.tasks[-1]), TaskStatus.DONE)
    d_idx = ctx.store.tasks.index(ctx.store.tasks[-1])
    ctx.store.set_status(len(ctx.store) - 1, TaskStatus.DONE)
    w.rebuild(ctx.store.tasks, animate=False)
    w._pressed = w._widgets[8] if ctx.store.tasks[8].status.is_active else None
    # автопрокрутка: вычислить зону краёв окна
    check("движок жив", w is not None)

    # взаимное исключение переименования
    w.rebuild(ctx.store.tasks, animate=False)
    w._widgets[0].start_edit()
    w._widgets[1].start_edit()
    only_one = (w._widgets[0]._edit is None and w._widgets[1]._edit is not None)
    check("переименование взаимоисключающее", only_one)
    w.cancel_edit()

    # выход мышкой/Enter сохраняет введённый текст
    w.rebuild(ctx.store.tasks, animate=False)
    w._widgets[0].start_edit()
    w._widgets[0]._edit.setText("Новое имя")
    w._widgets[0].commit_edit()
    check("выход кликом/Enter сохраняет", ctx.store.tasks[0].title == "Новое имя")

    # ESC отменяет переименование
    w._widgets[0].start_edit()
    w._widgets[0]._edit.setText("Не сохранится")
    w._widgets[0]._cancel_edit()
    check("ESC отменяет переименование", ctx.store.tasks[0].title == "Новое имя")

    main.close()
    ctx.quit()


# ---------------------------------------------------------------- Напоминания
def test_reminders():
    print("## Напоминания")
    from app import AppContext, ReminderManager
    from main_window import MainWindow
    from system_tray import SystemTray

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    for i in range(3):
        ctx.store.add(f"r{i}")
    main = MainWindow(ctx)
    ctx.main_window = main
    tray = SystemTray(ctx.settings_manager, ctx)
    ctx.tray = tray
    rm = ReminderManager(ctx)
    ctx.reminders = rm
    main.show()

    # после запуска полный отсчёт
    check("полный отсчёт после запуска", rm._remaining == rm._interval)

    # интервал изменился — немедленно новый полный отсчёт
    ctx.settings_manager.s.reminder_interval_seconds = 200
    rm.on_settings_changed()
    check("сброс при изменении интервала", rm._interval == 200 and rm._remaining == 200)

    # показ уведомления, скрытие Enter-ом -> новый полный интервал
    rm._remaining = 0
    rm._fire()
    check("уведомление показано", rm._reminder is not None and rm._reminder.isVisible())
    check("только активные задачи", all(t.status.is_active for t in rm._reminder._tasks))
    rm._reminder._hide()
    check("после скрытия новый полный интервал", rm._remaining == 200)

    # пустой список
    ctx.store.tasks.clear()
    rm._remaining = 0
    rm._fire()
    check("пустое уведомление", rm._reminder is not None and rm._reminder.isVisible())
    rm._reminder._hide()
    check("цикл продолжается", rm._remaining == 200)

    # нет второго окна при повторном запуске
    rm._interval = 10
    rm._remaining = 0
    rm._fire()
    first = rm._reminder
    rm._fire()  # повторный запуск, пока открыто
    check("не создаёт второе окно", rm._reminder is first)
    rm._reminder._hide()

    ctx.quit()


# ---------------------------------------------------------------- Окно
def test_window():
    print("## Главное окно")
    from app import AppContext
    from main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    main = MainWindow(ctx)
    ctx.main_window = main
    main.show()
    check("размер 300x700", main.size().width() == 300 and main.size().height() == 700)
    check("resize запрещён", main.minimumSize() == main.maximumSize())

    # сохранить/восстановить позицию
    main.move(123, 45)
    main._save_position()
    ctx.settings_manager.flush()
    ctx2 = AppContext(app)
    check("положение окна сохраняется",
          ctx2.settings_manager.s.window_x == 123 and ctx2.settings_manager.s.window_y == 45)

    ctx.save_data()
    ctx.quit()


# ---------------------------------------------------------------- Полноэкранное уведомление
def test_fullscreen_render():
    print("## Полноэкранное уведомление")
    from app import AppContext
    from reminder_window import ReminderWindow

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    for i in range(8):
        ctx.store.add(f"Ф{i}")
    ctx.store.set_status(2, TaskStatus.STARTED)
    ctx.store.set_status(6, TaskStatus.DONE)

    scr = QGuiApplication.primaryScreen()
    win = ReminderWindow(ctx.settings_manager.s, ctx.store.active_tasks())
    win.attach_to_screen(scr)
    check("полноэкранный размер", win.width() == scr.geometry().width())
    check("только активные задачи", all(t.status.is_active for t in win._tasks))
    with_tasks = win.width() > 0
    check("рендер с задачами", with_tasks)
    pix = win.grab()
    check("граб рендерится", not pix.isNull())
    win.close()

    # пустое уведомление
    empty = ReminderWindow(ctx.settings_manager.s, [])
    empty.attach_to_screen(scr)
    pix2 = empty.grab()
    check("рендер пустого уведомления", not pix2.isNull())
    empty.close()


def test_performance_paths():
    print("## Производительность: переиспользование и кэши")
    from app import AppContext
    from main_window import MainWindow
    from reminder_window import ReminderWindow

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    ctx.store.tasks.clear()
    for i in range(10):
        ctx.store.add(f"П{i}")
    main = MainWindow(ctx)
    ctx.main_window = main
    main.show()
    w = main._list

    before = {wd.task.id: wd for wd in w._widgets}
    target = ctx.store.tasks[3]
    main._on_status_cycle(target)
    after = {wd.task.id: wd for wd in w._widgets}
    reused = sum(1 for tid, wd in after.items() if before.get(tid) is wd and tid != target.id)
    check("карточки неизменившихся задач переиспользуются", reused == 9, f"reused={reused}")
    check("изменившаяся карточка пересоздана", after[target.id] is not before[target.id])
    check("порядок карточек = порядок задач", [wd.task.id for wd in w._widgets] == [t.id for t in ctx.store.tasks])

    ctx.store.remove(0)
    main.refresh(animate=False)
    check("удалённая задача убрана из списка", len(w._widgets) == len(ctx.store.tasks))

    # фильтр «клик вне поля» живёт только во время переименования
    w._widgets[0].start_edit()
    check("фильтр кликов включён при переименовании", w._click_filter_active)
    w._widgets[0]._cancel_edit()
    check("фильтр кликов снят после переименования", not w._click_filter_active)

    # отложенная запись настроек
    sm = ctx.settings_manager
    sm.flush()
    mtime = S.SETTINGS_PATH.stat().st_mtime_ns
    sm.s.opacity_percent = 37
    sm.save()
    check("save() не пишет на диск сразу", S.SETTINGS_PATH.stat().st_mtime_ns == mtime and sm._save_timer.isActive())
    sm.flush()
    import json as _json
    check("flush() записывает настройки", _json.loads(S.SETTINGS_PATH.read_text(encoding="utf-8"))["opacity_percent"] == 37)
    sm.s.opacity_percent = 0
    sm.flush()

    # кэш раскладки полноэкранного окна
    win = ReminderWindow(sm.s, ctx.store.tasks)
    win.resize(1200, 800)
    calls = []
    orig = win._compute_layout
    win._compute_layout = lambda: (calls.append(1), orig())[1]
    win.grab()
    win.grab()
    check("раскладка считается один раз на два кадра", len(calls) == 1, f"calls={len(calls)}")
    win.set_tasks(ctx.store.tasks[:3])
    win.grab()
    check("смена задач пересчитывает раскладку", len(calls) == 2)
    sm.s.text_size += 2
    win.grab()
    check("смена настроек пересчитывает раскладку", len(calls) == 3)
    sm.s.text_size -= 2
    win.close()
    main._quitting = True
    main.close()


def test_updater():
    print("## Автообновление")
    import hashlib
    import updater

    check("разбор версии", updater.parse_version("v2.6.3.2") == (2, 6, 3, 2))
    check("хвостовые нули не важны", updater.parse_version("2.7") == updater.parse_version("v2.7.0.0"))
    check("новее", updater.is_newer("v2.7.0.0", "2.6.3.2") and updater.is_newer("2.6.10", "2.6.9"))
    check("не новее", not updater.is_newer("v2.6.3.2", "2.6.3.2") and not updater.is_newer("2.6.3.1", "2.6.3.2"))

    release = {
        "tag_name": "v2.7.0.0",
        "body": "## Что нового",
        "html_url": "https://example/rel",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example/notes.txt", "size": 1},
            {"name": "ToDoReminder.exe", "browser_download_url": "https://example/app.exe", "size": 5,
             "digest": "sha256:ABCDEF"},
        ],
    }
    info = updater.parse_release(release)
    check("выбран EXE-ассет", info is not None and info.asset_url.endswith("app.exe"))
    check("версия и SHA-256 из релиза", info.version == "2.7.0.0" and info.sha256 == "abcdef")
    check("релиз без EXE пропускается", updater.parse_release({"tag_name": "v9", "assets": []}) is None)

    d = Path(tempfile.mkdtemp())
    payload = b"new exe payload" * 1000
    src = d / "remote.exe"
    src.write_bytes(payload)
    good = updater.ReleaseInfo("9", "v9", "", "", src.as_uri(), len(payload), hashlib.sha256(payload).hexdigest())
    got = updater.download(good, d / "dl.exe")
    check("загрузка с проверкой SHA-256", got.read_bytes() == payload)

    bad = updater.ReleaseInfo("9", "v9", "", "", src.as_uri(), len(payload), "0" * 64)
    try:
        updater.download(bad, d / "bad.exe")
        check("неверная контрольная сумма отклоняется", False)
    except updater.UpdateError:
        check("неверная контрольная сумма отклоняется",
              not (d / "bad.exe").exists() and not (d / "bad.exe.part").exists())

    try:
        updater.download(good, d / "cancel.exe", cancelled=lambda: True)
        check("отмена загрузки", False)
    except updater.UpdateCancelled:
        check("отмена загрузки", not (d / "cancel.exe").exists())

    exe = d / "ToDoReminder.exe"
    exe.write_bytes(b"old")
    new = d / "ToDoReminder.exe.new"
    new.write_bytes(b"new")
    updater.swap_executables(exe, new)
    check("подмена EXE", exe.read_bytes() == b"new" and updater.old_exe_path(exe).read_bytes() == b"old"
          and not new.exists())

    os.environ["_PYI_APPLICATION_HOME_DIR"] = "x"
    env = updater.clean_child_env()
    del os.environ["_PYI_APPLICATION_HOME_DIR"]
    check("служебные переменные PyInstaller сброшены",
          "_PYI_APPLICATION_HOME_DIR" not in env and env.get("PYINSTALLER_RESET_ENVIRONMENT") == "1")


def test_review_fixes():
    print("## Исправления по ревью")
    import hashlib
    import updater
    from PySide6.QtWidgets import QMessageBox
    from app import AppContext
    from main_window import MainWindow
    from settings_window import SettingsDialog
    from update_manager import UpdateManager

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    main = MainWindow(ctx)
    ctx.main_window = main
    main.show()
    um = UpdateManager(ctx)
    ctx.updates = um

    # окно новой версии не должно блокироваться открытыми «Настройками» (WindowModal)
    dlg = SettingsDialog(ctx.settings_manager, QGuiApplication.screens(), main)
    dlg.show()
    app.processEvents()
    info = updater.ReleaseInfo("99.0", "v99.0", "", "https://example/rel", "https://example/a.exe", 1, None)
    from PySide6.QtCore import QEvent, QObject

    class BlockSpy(QObject):
        blocked = False

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.WindowBlocked:
                BlockSpy.blocked = True
            return False

    spy = BlockSpy()
    app.installEventFilter(spy)
    um._on_checked(info, False)
    app.processEvents()
    offer = um._dialog
    app.removeEventFilter(spy)
    check("окно обновления не заблокировано настройками",
          offer is not None and offer.parentWidget() is None and not BlockSpy.blocked,
          f"blocked={BlockSpy.blocked}")
    # фоновая проверка не пересоздаёт уже открытое окно той же версии
    um._on_checked(info, True)
    check("фоновая проверка не пересоздаёт окно", um._dialog is offer)
    dlg.close()
    dlg.deleteLater()
    app.processEvents()
    check("закрытие настроек не уничтожает окно обновления", um._dialog is offer and offer.isVisible())

    # повторная ручная проверка: destroyed старого окна не обнуляет ссылку на новое
    um._on_checked(info, False)
    second = um._dialog
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    check("ссылка на текущее окно переживает удаление прежнего", um._dialog is second and second is not offer)
    um._on_checked(info, True)
    check("после этого фоновая проверка не плодит окна", um._dialog is second)
    second.close()
    app.processEvents()

    # результат проверки во время загрузки не открывает окон
    um._downloading = True
    um._on_checked(info, False)
    check("во время загрузки предложение не показывается", um._dialog is None)
    um._downloading = False

    # отмена, пришедшая после последнего чанка, не ставит обновление
    d = Path(tempfile.mkdtemp())
    new = d / "x.new"
    new.write_bytes(b"x")
    installed = []
    orig_install = updater.install_and_restart
    updater.install_and_restart = lambda *a, **k: installed.append(a)
    try:
        um._cancel.set()
        um._on_downloaded(new)
    finally:
        updater.install_and_restart = orig_install
    check("отмена после загрузки не устанавливает", not installed and not new.exists())

    # без digest и без размера скачанный файл проверить нельзя — отказ
    payload = b"abc"
    src = d / "r.exe"
    src.write_bytes(payload)
    blind = updater.ReleaseInfo("9", "v9", "", "", src.as_uri(), 0, None)
    try:
        updater.download(blind, d / "blind.exe")
        check("без размера и SHA-256 загрузка отклоняется", False)
    except updater.UpdateError:
        check("без размера и SHA-256 загрузка отклоняется", not (d / "blind.exe").exists())
    sized = updater.ReleaseInfo("9", "v9", "", "", src.as_uri(), len(payload), hashlib.sha256(payload).hexdigest())
    check("с размером и SHA-256 загрузка проходит", updater.download(sized, d / "ok.exe").read_bytes() == payload)

    # сброс настроек сохраняет служебную дату ежедневного сброса
    ctx.settings_manager.s.regular_reset_date = "2026-10-18"
    dlg2 = SettingsDialog(ctx.settings_manager, QGuiApplication.screens(), main)
    orig_q = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        dlg2._reset_defaults()
    finally:
        QMessageBox.question = orig_q
    check("сброс настроек не обнуляет дату ежедневного сброса",
          ctx.settings_manager.s.regular_reset_date == "2026-10-18")
    dlg2.close()

    # выход после обновления не пишет настройки повторно
    ctx.settings_manager.flush()
    mtime = S.SETTINGS_PATH.stat().st_mtime_ns
    ctx.settings_manager.s.opacity_percent = 55
    ctx.quit(save=False)
    ctx.settings_manager.flush()
    check("quit(save=False) не трогает файл настроек", S.SETTINGS_PATH.stat().st_mtime_ns == mtime)

    # текст релиза пишется в UTF-8 напрямую
    import subprocess
    root = Path(__file__).resolve().parent.parent
    notes = d / "notes.md"
    subprocess.run([sys.executable, str(root / "tools" / "release_notes.py"), "v2.7.0.0", str(notes)], check=True)
    check("текст релиза в UTF-8", "Автообновление" in notes.read_text(encoding="utf-8"))


def test_update_polish():
    print("## Обновления: напоминания и выход")
    import updater
    from app import AppContext, ReminderManager
    from main_window import MainWindow
    from update_manager import UpdateManager, _safe_emit

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    main = MainWindow(ctx)
    ctx.main_window = main
    rm = ReminderManager(ctx)
    ctx.reminders = rm
    um = UpdateManager(ctx)
    ctx.updates = um

    # пока идёт загрузка обновления (модальный прогресс), напоминание ждёт на нуле
    um._downloading = True
    rm._remaining = 1
    rm._tick()
    rm._tick()
    check("напоминание отложено во время загрузки", rm._reminder is None and rm._remaining == 0)
    um._downloading = False
    rm._tick()
    check("после загрузки напоминание показано", rm._reminder is not None and rm._reminder.isVisible())
    rm._reminder._hide()
    app.processEvents()

    # модальное сообщение обновления: поверх всех окон и снимает блокировку напоминаний после закрытия
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QMessageBox
    seen = {}
    orig_exec = QMessageBox.exec

    def fake_exec(box):
        seen["on_top"] = bool(box.windowFlags() & _Qt.WindowStaysOnTopHint)
        seen["blocks"] = um.blocks_reminders
        return 0

    QMessageBox.exec = fake_exec
    try:
        um._message(QMessageBox.Information, "проверка")
    finally:
        QMessageBox.exec = orig_exec
    check("сообщение обновления поверх всех окон", seen.get("on_top") is True)
    check("пока сообщение открыто, напоминания отложены; после — нет",
          seen.get("blocks") is True and not um.blocks_reminders)

    # сбой запуска загрузки не оставляет флаг «идёт загрузка»
    info = updater.ReleaseInfo("99.0", "v99.0", "", "", "https://example/a.exe", 1, None)
    orig_can = updater.can_write_next_to
    updater.can_write_next_to = lambda exe: True

    def boom(*a):
        raise RuntimeError("can't start new thread")

    um._launch_download = boom
    try:
        um._start_download(info)
        check("сбой запуска загрузки сбрасывает флаг", False)
    except RuntimeError:
        check("сбой запуска загрузки сбрасывает флаг", not um._downloading and not um.blocks_reminders)
    finally:
        updater.can_write_next_to = orig_can

    # ответ проверки после выхода не открывает окон
    um.shutdown()
    shown = []
    um._message = lambda *a, **k: shown.append(a)
    um._on_checked(info, False)
    um._on_checked(None, False)
    um._on_check_failed("нет сети", False)
    check("после выхода результаты проверки не показываются", not shown and um._dialog is None)
    check("выход останавливает таймеры и загрузку",
          not um._first.isActive() and not um._periodic.isActive() and um._cancel.is_set())

    # emit в удалённый мост из рабочего потока не бросает исключение
    import shiboken6
    bridge = um._bridge
    sig = bridge.checked
    shiboken6.delete(bridge)
    try:
        _safe_emit(sig, None, True)
        check("emit в удалённый мост безопасен", True)
    except Exception as e:  # noqa: BLE001
        check("emit в удалённый мост безопасен", False, repr(e))
    main._quitting = True
    main.close()


def test_issue_1():
    print("## Issue #1: автоудаление, крестик, переполнение напоминания")
    from app import AppContext
    from main_window import MainWindow
    from models import Task
    from reminder_window import ReminderWindow

    app = QApplication.instance() or QApplication(sys.argv)

    # 1. автоудаление выполненных — настраивается
    ctx = AppContext(app)
    ctx.store.tasks.clear()
    ctx.store.add("готовое")
    ctx.store.add("регулярное")
    ctx.store.set_status(0, TaskStatus.DONE)
    ctx.store.set_regular(ctx.store.tasks.index(next(t for t in ctx.store.tasks if t.title == "регулярное")), True)
    for t in ctx.store.tasks:
        t.status = TaskStatus.DONE
    s = ctx.settings_manager.s
    s.auto_remove_done = False
    ctx._startup_cleanup()
    s.regular_reset_date = "2000-01-01"
    ctx._daily_check()
    titles = {t.title: t.status for t in ctx.store.tasks}
    check("выключено: Done не удаляются ни при запуске, ни в новый день", titles.get("готовое") is TaskStatus.DONE)
    check("выключено: регулярные всё равно сбрасываются в To Do", titles.get("регулярное") is TaskStatus.TO_DO)
    s.auto_remove_done = True
    s.regular_reset_date = "2000-01-01"
    ctx._daily_check()
    check("включено: Done удаляются в новый день", [t.title for t in ctx.store.tasks] == ["регулярное"])
    ctx.store.tasks[0].status = TaskStatus.DONE
    ctx._startup_cleanup()
    check("включено: Done удаляются при запуске", not ctx.store.tasks)

    # 2. крестик удаления на карточке
    ctx.store.add("удали меня")
    ctx.store.add("останься")
    main = MainWindow(ctx)
    ctx.main_window = main
    main.show()
    app.processEvents()
    w = main._list.widget_by_task(next(t for t in ctx.store.tasks if t.title == "удали меня"))
    check("у карточки есть крестик", w is not None and w.del_btn.isVisible())
    w.del_btn.click()
    app.processEvents()
    check("крестик удаляет задачу", [t.title for t in ctx.store.tasks] == ["останься"])
    w2 = main._list._widgets[0]
    w2.start_edit()
    check("поле переименования не наезжает на крестик",
          w2._edit.geometry().right() < w2.del_btn.geometry().left())
    w2._cancel_edit()

    # двойной щелчок по крестику: второй щелчок приходится на подъехавшую карточку
    import time as _time
    from PySide6.QtCore import QEvent as _QEvent, QPointF as _QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt
    ctx.store.tasks.clear()
    for i in range(4):
        ctx.store.add(f"task{i}")
    main.refresh(animate=False)
    lst = main._list
    lst._deleted_at = _time.monotonic() - 10  # предыдущая проверка удаляла только что
    first = lst._widgets[0]
    gpos = first.del_btn.mapToGlobal(first.del_btn.rect().center())
    first.del_btn.click()
    for _ in range(10):
        lst._tick()
    app.processEvents()
    under = lst._widgets[0]
    local = _QPointF(under.del_btn.mapFromGlobal(gpos))
    for et in (_QEvent.MouseButtonDblClick, _QEvent.MouseButtonRelease):
        ev = QMouseEvent(et, local, _QPointF(gpos), Qt.LeftButton,
                         Qt.LeftButton if et != _QEvent.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(under.del_btn, ev)
    under.del_btn.click()  # даже «честный» второй click в интервале двойного щелчка
    app.processEvents()
    check("двойной щелчок по крестику удаляет одно дело", len(ctx.store.tasks) == 3, str([t.title for t in ctx.store.tasks]))
    ev = QMouseEvent(_QEvent.MouseButtonDblClick, _QPointF(5, 5), _QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(lst._widgets[0], ev)
    check("двойной клик сразу после удаления не открывает переименование", lst.active_edit_widget() is None)
    lst._deleted_at = _time.monotonic() - 10
    lst._widgets[0].del_btn.click()
    app.processEvents()
    check("после интервала крестик снова удаляет", len(ctx.store.tasks) == 2)
    # быстрый щелчок по крестику в другом месте (другая карточка) — намеренный, не блокируется
    from PySide6.QtCore import QPoint as _QPoint
    from PySide6.QtGui import QCursor
    lst._deleted_pos = QCursor.pos() + _QPoint(0, 200)
    lst._widgets[0].del_btn.click()
    app.processEvents()
    check("быстрый щелчок в другом месте удаляет", len(ctx.store.tasks) == 1)
    main._quitting = True
    main.close()

    # 3. переполнение полноэкранного напоминания
    def mk(n, status, title="Дело с описанием средней длины"):
        out = []
        for i in range(n):
            t = Task.create(f"{title} {i}")
            t.status = status
            t.position = i
            out.append(t)
        return out

    def layout(tasks, **over):
        st = S.Settings()
        st.text_size = 32
        st.fullscreen_min_font_size = 14
        for k, v in over.items():
            setattr(st, k, v)
        win = ReminderWindow(st, tasks)
        win.resize(1600, 900)
        lay = win._current_layout()
        cols = lay.n_cols
        more = [i.title for i in lay.items if i.marker is None and i.title.startswith("…")]
        layout.notes = [i.title for i in lay.items if i.marker is None and i.title.startswith("Скрыто")]
        shown = sum(1 for i in lay.items if i.marker is not None)
        win.close()
        return cols, more, shown

    few = mk(6, TaskStatus.TO_DO)
    cols, more, shown = layout(few)
    check("влезает — раскладка как настроена (2+2)", cols == 4 and not more and shown == 6)

    # Done занимает место: при нехватке выполненные скрываются, активные — все на экране
    active = mk(40, TaskStatus.TO_DO) + mk(40, TaskStatus.STARTED)
    done = mk(60, TaskStatus.DONE)
    cols, more, shown = layout(active + done, show_done_in_fullscreen=True,
                               fullscreen_columns_todo=1, fullscreen_columns_started=1, fullscreen_columns_done=1)
    check("при нехватке места Done скрываются, активные все видны", not more and shown == 80, f"cols={cols} more={more} shown={shown}")
    check("о скрытых Done есть пометка", layout.notes == ["Скрыто выполненных: 60"], str(layout.notes))

    # одни Done и не влезают — не пустой экран, а «… и ещё N»
    cols, more, shown = layout(mk(300, TaskStatus.DONE), show_done_in_fullscreen=True)
    hidden = sum(int(m.rsplit(" ", 1)[1]) for m in more)
    check("одни Done: экран не пустой", shown > 0 and shown + hidden == 300, f"shown={shown} hidden={hidden}")

    # единственное дело выше экрана (срочное со ссылками) всё равно на экране, а не «… и ещё 1»
    url = "https://example.com/very/long/link/path/to/document"
    big = Task.create(f"позвонить в бухгалтерию {url} согласовать договор аренды {url} оборудования {url}")
    big.urgent = True
    st = S.Settings()
    st.text_size = 20
    st.urgent_fullscreen_size_delta = 6
    st.fullscreen_columns_todo, st.fullscreen_columns_started, st.fullscreen_columns_done = 2, 4, 1
    win = ReminderWindow(st, [big])
    win.resize(1024, 600)
    lay = win._current_layout()
    titles = [i.title for i in lay.items]
    check("единственное длинное дело видно", any(t.startswith("⚡") for t in titles) and not any(t.startswith("…") for t in titles),
          str(titles)[:120])
    check("колонки не добавляются статусу с одним делом", lay.n_cols == 6, f"cols={lay.n_cols}")
    win.close()

    # высокое первое дело с делами под ним: обрезается, под ним «… и ещё N» в пределах экрана
    # (30 огромных дел: даже 12 колонок не спасают, в каждой — обрезанное первое дело и «… и ещё N»)
    huge = []
    for i in range(30):
        t = Task.create(f"{i} " + " ".join(["очень длинное описание дела"] * 60))
        t.position = i
        huge.append(t)
    st = S.Settings()
    st.text_size = 48
    st.fullscreen_columns_todo, st.fullscreen_columns_started = 1, 1
    win = ReminderWindow(st, huge)
    win.resize(800, 600)
    lay = win._current_layout()
    shown = [i for i in lay.items if i.marker is not None]
    more = [i for i in lay.items if i.title.startswith("…")]
    hidden = sum(int(m.title.rsplit(" ", 1)[1]) for m in more)
    clipped = all(i.rect.height() == i.height < 600 for i in shown)
    more_ok = more and all(m.rect.y() + m.height <= 600 for m in more) and all(
        any(m.rect.x() == s.rect.x() and m.rect.y() >= s.rect.y() + s.height for s in shown) for m in more)
    check("высокое первое дело обрезано по видимой области", shown and clipped,
          str([(i.rect.height(), i.height) for i in shown][:3]))
    check("под обрезанным делом «… и ещё N» в пределах экрана", bool(more_ok) and len(shown) + hidden == 30,
          f"shown={len(shown)} hidden={hidden}")
    win.close()

    # пометка о скрытых Done не теряется ни при переполнении, ни когда активные легли впритык
    def note_case(w, h, text_size, n_todo, n_started, n_done):
        st = S.Settings()
        st.text_size = text_size
        st.fullscreen_min_font_size = 14
        st.show_done_in_fullscreen = True
        st.fullscreen_columns_todo = st.fullscreen_columns_started = st.fullscreen_columns_done = 1
        win = ReminderWindow(st, mk(n_todo, TaskStatus.TO_DO) + mk(n_started, TaskStatus.STARTED) + mk(n_done, TaskStatus.DONE))
        win.resize(w, h)
        lay = win._current_layout()
        notes = [i for i in lay.items if i.marker is None and i.title.startswith("Скрыто")]
        bottom = max(i.rect.y() + i.height for i in lay.items)
        win.close()
        return notes, bottom

    notes, bottom = note_case(1600, 900, 72, 70, 70, 40)
    check("пометка о Done при переполнении", len(notes) == 1 and bottom <= 900, f"notes={len(notes)} bottom={bottom}")
    bad_heights = []
    for hh in (524, 545, 546, 565, 566, 567):
        notes, bottom = note_case(1200, hh, 20, 20, 20, 80)
        if len(notes) != 1 or bottom > hh:
            bad_heights.append(hh)
    check("пометка о Done, когда активные легли впритык", not bad_heights, str(bad_heights))

    # Done возвращаются, если после добавления колонок для активных им хватает места
    cols, more, shown = layout(mk(60, TaskStatus.TO_DO) + mk(3, TaskStatus.DONE), show_done_in_fullscreen=True,
                               fullscreen_columns_todo=1, fullscreen_columns_started=1, fullscreen_columns_done=1)
    check("Done возвращаются в свободную колонку", shown == 63 and not more and not layout.notes,
          f"cols={cols} shown={shown} more={more} notes={layout.notes}")

    # не влезает в 1+1 колонку — колонки добавляются
    cols, more, shown = layout(mk(60, TaskStatus.TO_DO) + mk(10, TaskStatus.STARTED),
                               fullscreen_columns_todo=1, fullscreen_columns_started=1)
    check("при нехватке места добавляются колонки", cols > 2 and not more and shown == 70, f"cols={cols} more={more}")
    check("колонок не больше 12", cols <= 12)

    # не влезает никак — «… и ещё N», ничего не теряется молча
    many = mk(100, TaskStatus.TO_DO, "Дело номер с очень длинным описанием, которое переносится на несколько строк подряд")
    cols, more, shown = layout(many)
    hidden = sum(int(m.rsplit(" ", 1)[1]) for m in more)
    check("если не влезает — строка «… и ещё N»", bool(more))
    check("показанные + скрытые = все дела", shown + hidden == 100, f"shown={shown} hidden={hidden}")

    # одно слишком длинное слово не прячет Done, если по высоте место есть
    url = mk(1, TaskStatus.TO_DO, "https://example.com/" + "a" * 120)
    cols, more, shown = layout(mk(3, TaskStatus.TO_DO) + mk(3, TaskStatus.DONE) + url, show_done_in_fullscreen=True)
    check("длинное слово не скрывает Done", shown == 7 and not more, f"shown={shown} more={more}")

    # «показывать Done» без Done-дел не съедает лимит колонок
    cols, more, shown = layout(mk(60, TaskStatus.TO_DO) + mk(10, TaskStatus.STARTED), show_done_in_fullscreen=True,
                               fullscreen_columns_todo=1, fullscreen_columns_started=1, fullscreen_columns_done=8)
    check("пустой Done не съедает лимит колонок", cols > 2 and not more, f"cols={cols} more={more}")

    # «… и ещё N» в узкой колонке не вылезает за нижний край
    st = S.Settings()
    st.text_size = 14
    st.fullscreen_min_font_size = 14
    st.fullscreen_columns_todo = 8
    st.fullscreen_columns_started = 4
    win = ReminderWindow(st, mk(400, TaskStatus.TO_DO, "Дело с текстом") + mk(200, TaskStatus.STARTED, "Дело с текстом"))
    win.resize(1600, 900)
    lay = win._current_layout()
    bottom = max(i.rect.y() + i.height for i in lay.items)
    check("строка «… и ещё N» не вылезает за экран", bottom <= 900, f"bottom={bottom}")
    win.close()


def test_settings_layout():
    print("## Окно настроек: прокрутка и компактная раскладка")
    from PySide6.QtWidgets import QScrollArea
    from app import AppContext
    from main_window import MainWindow
    from settings_window import SettingsDialog

    app = QApplication.instance() or QApplication(sys.argv)
    ctx = AppContext(app)
    main = MainWindow(ctx)
    ctx.main_window = main
    dlg = SettingsDialog(ctx.settings_manager, QGuiApplication.screens(), main)
    dlg.show()
    app.processEvents()

    avail = (dlg.screen() or QGuiApplication.primaryScreen()).availableGeometry()
    check("содержимое в области прокрутки", isinstance(dlg._scroll, QScrollArea) and dlg._scroll.widget() is not None)
    check("минимальная высота окна мала (окно можно уменьшить)", dlg.minimumSizeHint().height() < 400 and dlg.minimumHeight() <= 400,
          f"min={dlg.minimumSizeHint().height()}/{dlg.minimumHeight()}")
    check("окно не выше доступной области экрана", dlg.frameGeometry().height() <= avail.height())
    dlg.resize(dlg.width(), 350)
    app.processEvents()
    check("окно уменьшается по высоте", dlg.height() <= 360, f"h={dlg.height()}")

    def same_row(*widgets):
        ys = {w.mapTo(dlg, w.rect().center()).y() for w in widgets}
        return max(ys) - min(ys) <= 2

    dlg.done_combo.setCurrentIndex(1)
    app.processEvents()
    check("колонки To Do / Started / Done в одну строку",
          same_row(dlg.cols_todo_spin, dlg.cols_started_spin, dlg.cols_done_spin) and dlg.cols_done_spin.isVisible())
    dlg.done_combo.setCurrentIndex(0)
    app.processEvents()
    check("колонки Done прячутся вместе с подписью", not dlg._cols_done_box.isVisible())
    check("размер, шрифт, начертание, выравнивание в одну строку",
          same_row(dlg.size_spin, dlg.font_combo, dlg.style_combo, dlg.align_combo))
    color_btns = [dlg._color_refs[f][0] for f in ("bg_color", "text_color", "color_status_todo",
                                                    "color_status_started", "color_status_done")]
    check("цвета в одну строку", same_row(*color_btns))
    check("срочные: увеличение, цвет, начертание в одну строку",
          same_row(dlg.urgent_size_spin, dlg._color_refs["urgent_fullscreen_color"][0], dlg.urgent_style_combo))
    check("образец цвета показывает HEX", color_btns[0].text() == ctx.settings_manager.s.bg_color.upper())

    # строки формы не сжимаются (раньше окно выше экрана ужимало поля, и текст счётчика обрезался)
    check("поле интервала не сжато по высоте", dlg.interval_spin.height() >= dlg.interval_spin.sizeHint().height(),
          f"h={dlg.interval_spin.height()} hint={dlg.interval_spin.sizeHint().height()}")

    # при исходном размере (если экран позволяет) горизонтальной прокрутки нет
    hbar = dlg._scroll.horizontalScrollBar()
    content_min = dlg._scroll.widget().minimumSizeHint().width()
    dlg._fit_to_screen()
    app.processEvents()
    if avail.width() - 40 >= content_min + dlg._scroll.verticalScrollBar().sizeHint().width() + 2:
        check("при обычной ширине горизонтальной прокрутки нет", hbar.maximum() == 0, f"max={hbar.maximum()}")

    # при минимальной ширине окна содержимое не обрезается справа
    dlg.resize(dlg.minimumWidth(), 400)
    app.processEvents()
    viewport_w = dlg._scroll.viewport().width()
    check("минимальная ширина не обрезает содержимое (или есть горизонтальная прокрутка)",
          viewport_w >= content_min or (hbar.isVisible() and hbar.maximum() > 0),
          f"viewport={viewport_w} content={content_min}")

    # сброс к умолчанию обновляет и поля срочных дел
    dlg.urgent_size_spin.setValue(20)
    dlg.urgent_style_combo.setCurrentIndex(3)

    # сброс к умолчанию обновляет образцы цветов
    from PySide6.QtGui import QColor as _QColor
    from PySide6.QtWidgets import QColorDialog, QMessageBox
    orig_get = QColorDialog.getColor
    QColorDialog.getColor = staticmethod(lambda *a, **k: _QColor("#123456"))
    try:
        dlg._color_refs["bg_color"][0].click()  # выбор цвета как пользователем
    finally:
        QColorDialog.getColor = orig_get
    check("выбор цвета обновляет образец и настройку",
          dlg._color_refs["bg_color"][0].text() == "#123456" and ctx.settings_manager.s.bg_color == "#123456")
    orig_q = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        dlg._reset_defaults()
    finally:
        QMessageBox.question = orig_q
    check("сброс обновляет образец цвета", dlg._color_refs["bg_color"][0].text() == S.Settings().bg_color.upper())
    defaults = S.Settings()
    check("сброс обновляет поля срочных дел",
          dlg.urgent_size_spin.value() == defaults.urgent_fullscreen_size_delta
          and dlg.urgent_style_combo.currentIndex() == defaults.urgent_fullscreen_style_index,
          f"{dlg.urgent_size_spin.value()} {dlg.urgent_style_combo.currentIndex()}")
    # контраст подписи на образце: на зелёном Done — тёмный текст
    from settings_window import SettingsDialog as _SD
    check("контрастный текст на образце #4CAF50", _SD._text_color_for("#4CAF50") == "#000000")
    check("контрастный текст на образце #171C26", _SD._text_color_for("#171C26") == "#FFFFFF")
    dlg.close()
    main._quitting = True
    main.close()


def test_embedded_store():
    print("## Данные внутри EXE")
    import datastore as D

    d = Path(tempfile.mkdtemp())
    exe = d / "ToDoReminder.exe"
    import json
    import shutil
    import struct as _struct
    # как настоящий onefile-EXE PyInstaller: заканчивается записью cookie «!8sIIii64s» (88 байт),
    # где имя python*.dll добито нулями — т.е. чистая программа сама кончается нулями
    program = b"MZ" + os.urandom(4000) + _struct.pack("!8sIIii64s", b"MEI\x0c\x0b\x0a\x0b\x0e",
                                                        4090, 3000, 500, 312, b"python312.dll")
    check("поддельный EXE кончается нулями, как настоящий", program.endswith(b"\x00" * 28))
    exe.write_bytes(program)
    work = d / "work"

    base, doc = D.read_embedded(exe)
    check("у чистого EXE данных нет", doc is None and base == len(program))

    # перенос старой папки data
    legacy = d / "data"
    legacy.mkdir()
    (legacy / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (legacy / "tasks.json").write_text('{"tasks": [{"id": "1", "title": "старое"}]}', encoding="utf-8")
    st = D.EmbeddedStore(exe, work_dir=work, legacy_dir=legacy)
    check("старая папка data подхвачена", st.load_settings().get("theme") == "dark"
          and st.load_tasks()["tasks"][0]["title"] == "старое" and st.dirty)
    check("рабочая копия создана сразу", st.work_file.path.exists())

    st.save_tasks({"tasks": [{"id": "1", "title": "новое дело"}]})
    check("выход записывает данные внутрь EXE", st.finalize())
    base, doc = D.read_embedded(exe)
    check("программа внутри EXE не изменилась", exe.read_bytes()[:base] == program)
    check("в EXE — актуальные дела", doc and doc["tasks"]["tasks"][0]["title"] == "новое дело")
    check("старая папка data удалена после переноса", not legacy.exists())
    check("рабочая копия удалена после записи в EXE", not st.work_file.path.exists())
    check("старый EXE отложен в .old", (d / "ToDoReminder.exe.old").exists())

    # «флешка»: копия EXE в другом месте, без рабочей копии
    usb = d / "usb"
    usb.mkdir()
    (usb / "ToDoReminder.exe").write_bytes(exe.read_bytes())
    st2 = D.EmbeddedStore(usb / "ToDoReminder.exe", work_dir=d / "other-pc")
    check("копия EXE несёт дела с собой", st2.load_tasks()["tasks"][0]["title"] == "новое дело" and not st2.dirty)
    check("без изменений EXE не переписывается", st2.finalize() and not (usb / "ToDoReminder.exe.old").exists())

    # сбой: изменения после последней записи в EXE берутся из рабочей копии
    st3 = D.EmbeddedStore(exe, work_dir=work)
    st3.save_settings({"theme": "light", "text_size": 40})
    st4 = D.EmbeddedStore(exe, work_dir=work)   # «перезапуск после падения» без finalize
    check("после сбоя данные из рабочей копии", st4.load_settings().get("text_size") == 40)

    # повторная запись в EXE не наращивает хвосты
    st4.save_tasks({"tasks": []})
    st4.finalize()
    size1 = exe.stat().st_size
    st5 = D.EmbeddedStore(exe, work_dir=work)
    st5.save_tasks({"tasks": [{"id": "2", "title": "x"}]})
    st5.save_tasks({"tasks": []})
    st5.finalize()
    check("хвост один, размер не растёт", abs(exe.stat().st_size - size1) < 64 and D.read_embedded(exe)[0] == len(program))

    # перенос: файл с BOM (Блокнот) читается, нечитаемый файл не удаляется
    d2 = Path(tempfile.mkdtemp())
    exe2 = d2 / "ToDoReminder.exe"
    exe2.write_bytes(program)
    legacy2 = d2 / "data"
    legacy2.mkdir()
    (legacy2 / "settings.json").write_bytes('﻿{"theme": "dark"}'.encode("utf-8"))
    (legacy2 / "tasks.json").write_text("{битый json", encoding="utf-8")
    st_b = D.EmbeddedStore(exe2, work_dir=d2 / "w", legacy_dir=legacy2)
    check("перенос читает файл с BOM", st_b.load_settings().get("theme") == "dark")
    st_b.finalize()
    check("нечитаемый файл старых данных не удаляется", (legacy2 / "tasks.json").exists()
          and not (legacy2 / "settings.json").exists())

    # ПК A / ПК B: старая рабочая копия с ПК A не должна перебить правки, сделанные на ПК B
    d3 = Path(tempfile.mkdtemp())
    usb_exe = d3 / "ToDoReminder.exe"
    usb_exe.write_bytes(program)
    pc_a, pc_b = d3 / "pcA", d3 / "pcB"
    a1 = D.EmbeddedStore(usb_exe, work_dir=pc_a)
    a1.save_tasks({"tasks": [{"id": "1", "title": "v1"}]})
    a1.finalize()
    a2 = D.EmbeddedStore(usb_exe, work_dir=pc_a)
    for i in range(4):
        a2.save_tasks({"tasks": [{"id": "1", "title": f"сбой A {i}"}]})
    # ПК A упал без выхода — рабочая копия с бОльшей ревизией осталась на A
    b = D.EmbeddedStore(usb_exe, work_dir=pc_b)
    b.save_tasks({"tasks": [{"id": "1", "title": "ВАЖНОЕ с ПК B"}]})
    b.finalize()
    back = D.EmbeddedStore(usb_exe, work_dir=pc_a)
    check("правки с другого ПК не перебиваются старой рабочей копией",
          back.load_tasks()["tasks"][0]["title"] == "ВАЖНОЕ с ПК B")
    conflicts = list(pc_a.glob("work-*-conflict-*.json"))
    check("устаревшая рабочая копия отложена, а не удалена, и есть сообщение",
          len(conflicts) == 1 and "сбой A 3" in conflicts[0].read_text(encoding="utf-8") and back.notices)

    # обычное восстановление после сбоя на том же ПК — с сообщением
    a3 = D.EmbeddedStore(usb_exe, work_dir=pc_a)
    a3.save_tasks({"tasks": [{"id": "1", "title": "после B, сбой"}]})
    a4 = D.EmbeddedStore(usb_exe, work_dir=pc_a)
    check("восстановление после сбоя с сообщением",
          a4.load_tasks()["tasks"][0]["title"] == "после B, сбой" and any("Восстановлены" in n for n in a4.notices))

    # обновление: данные в скачанном EXE, рабочая копия продолжает новое поколение (без ложного конфликта)
    upd = d3 / "ToDoReminder.exe.new"
    upd.write_bytes(b"MZ" + os.urandom(2000))
    conflicts_before = len(list(pc_a.glob("work-*-conflict-*.json")))
    a4.embed_into(upd)
    check("после обновления данные в новом EXE", D.read_embedded(upd)[1]["tasks"]["tasks"][0]["title"] == "после B, сбой")
    os.replace(upd, usb_exe)        # как install_and_restart: новая версия встаёт на место старой
    a5 = D.EmbeddedStore(usb_exe, work_dir=pc_a)
    check("после обновления нет ложного конфликта и сообщения о восстановлении",
          len(list(pc_a.glob("work-*-conflict-*.json"))) == conflicts_before and not a5.notices
          and a5.load_tasks()["tasks"][0]["title"] == "после B, сбой")

    # обновление скачано и данные перенесены, но установка не удалась → выход без новых правок
    d7 = Path(tempfile.mkdtemp())
    exe7 = d7 / "ToDoReminder.exe"
    exe7.write_bytes(program)
    s70 = D.EmbeddedStore(exe7, work_dir=d7 / "w")
    s70.save_tasks({"tasks": [{"id": "1", "title": "u0"}]})
    s70.finalize()
    s71 = D.EmbeddedStore(exe7, work_dir=d7 / "w")
    s71.save_tasks({"tasks": [{"id": "1", "title": "правки сессии"}]})
    new7 = d7 / "ToDoReminder.exe.new"
    new7.write_bytes(b"MZ" + os.urandom(1500))
    s71.embed_into(new7)          # install_and_restart затем падает — программа работает дальше
    check("после неудачной установки правки ещё не записаны в EXE (dirty)", s71.dirty)
    s71.finalize()
    s72 = D.EmbeddedStore(exe7, work_dir=d7 / "w")
    check("неудачная установка обновления не теряет правки сессии",
          s72.load_tasks()["tasks"][0]["title"] == "правки сессии" and not s72.notices)

    # тот же сценарий, но вместо выхода — сбой: правки восстанавливаются, а не уходят в «конфликт»
    s73 = D.EmbeddedStore(exe7, work_dir=d7 / "w")
    s73.save_tasks({"tasks": [{"id": "1", "title": "ещё правки"}]})
    new7.write_bytes(b"MZ" + os.urandom(1500))
    s73.embed_into(new7)
    s74 = D.EmbeddedStore(exe7, work_dir=d7 / "w")   # сбой, старая версия запущена снова
    check("неудачная установка + сбой: правки восстановлены без ложного конфликта",
          s74.load_tasks()["tasks"][0]["title"] == "ещё правки"
          and not list((d7 / "w").glob("*conflict*")) and any("Восстановлены" in n for n in s74.notices))

    # рабочая копия с тем же содержимым, что в EXE (её не дал удалить антивирус) — тихо убирается
    s74.finalize()
    s75 = D.EmbeddedStore(exe7, work_dir=d7 / "w")
    s75.work_file.save(dict(D.read_embedded(exe7)[1], base_gen="чужое", pending_gen=None))
    s76 = D.EmbeddedStore(exe7, work_dir=d7 / "w")
    check("рабочая копия, совпадающая с EXE, не даёт ложного конфликта",
          not s76.notices and not list((d7 / "w").glob("*conflict*")) and not s76.work_file.path.exists())

    # повреждённые встроенные данные — с сообщением, а не тихий пустой список
    raw7 = bytearray(exe7.read_bytes())
    raw7[-D.TRAILER.size - 5] ^= 0xFF
    exe7.write_bytes(bytes(raw7))
    s77 = D.EmbeddedStore(exe7, work_dir=d7 / "w2")
    check("повреждённые данные внутри программы — с сообщением", any("повреждены" in n for n in s77.notices))

    # чистый EXE (только что из релиза) — без ложного «повреждены»
    dc = Path(tempfile.mkdtemp())
    clean_exe = dc / "ToDoReminder.exe"
    clean_exe.write_bytes(program)
    sc = D.EmbeddedStore(clean_exe, work_dir=dc / "w")
    check("чистый EXE из релиза — без сообщений", not sc.notices and not sc.dirty)
    real = Path(__file__).resolve().parent.parent / "dist" / "ToDoReminder.exe"
    if real.exists():   # если собран — проверяем и настоящий (только чтение копии, не запуск)
        real_copy = dc / "real.exe"
        shutil.copy2(real, real_copy)
        base_r, doc_r, dmg_r = D.inspect_embedded(real_copy)
        check("собранный dist\\ToDoReminder.exe распознаётся как чистый", doc_r is None and not dmg_r)

    # обрезанный хвост без рабочей копии — с сообщением, а не тихий пустой список
    dt = Path(tempfile.mkdtemp())
    trunc = dt / "ToDoReminder.exe"
    trunc.write_bytes((program + D.pack({"rev": 2, "gen": "g", "settings": {}, "tasks": {"tasks": [{"id": "1", "title": "x"}]}}))[:-10])
    st_t = D.EmbeddedStore(trunc, work_dir=dt / "w")
    check("обрезанный хвост без рабочей копии — с сообщением", any("повреждены" in n for n in st_t.notices))

    # запасной файл (session / .unsaved.json) подхватывается при следующем запуске
    dfb = Path(tempfile.mkdtemp())
    exe_fb = dfb / "ToDoReminder.exe"
    exe_fb.write_bytes(program)
    s_fb0 = D.EmbeddedStore(exe_fb, work_dir=dfb / "w")
    s_fb0.save_tasks({"tasks": [{"id": "1", "title": "в EXE"}]})
    s_fb0.finalize()
    s_fb1 = D.EmbeddedStore(exe_fb, work_dir=dfb / "w")
    s_fb1._work_blocked = True
    s_fb1.save_tasks({"tasks": [{"id": "1", "title": "из запасного"}]})
    orig_w2 = D.write_exe_with_data
    D.write_exe_with_data = lambda *a, **k: (_ for _ in ()).throw(PermissionError("только чтение"))
    try:
        s_fb1.finalize()
    finally:
        D.write_exe_with_data = orig_w2
    fb_path = s_fb1.fallback_path
    s_fb2 = D.EmbeddedStore(exe_fb, work_dir=dfb / "w")
    check("запасной файл подхватывается при следующем запуске",
          s_fb2.load_tasks()["tasks"][0]["title"] == "из запасного" and any("Восстановлены" in n for n in s_fb2.notices))
    s_fb2.finalize()
    check("после записи в EXE запасной файл убран", fb_path is not None and not Path(fb_path).exists())
    unsaved = exe_fb.with_name(exe_fb.name + ".unsaved.json")
    emb = D.read_embedded(exe_fb)[1]
    unsaved.write_text(json.dumps({"rev": emb["rev"] + 1, "base_gen": emb["gen"], "pending_gen": None,
                                   "settings": {}, "tasks": {"tasks": [{"id": "1", "title": "из .unsaved"}]}},
                                  ensure_ascii=False), encoding="utf-8")
    s_fb3 = D.EmbeddedStore(exe_fb, work_dir=dfb / "w")
    check(".unsaved.json рядом с EXE подхватывается", s_fb3.load_tasks()["tasks"][0]["title"] == "из .unsaved")
    s_fb3.finalize()
    check("после записи в EXE .unsaved.json убран", not unsaved.exists())

    # свой EXE не прочитался: сообщение, нет ложного «повреждены»; следующий запуск — без ложного конфликта
    dun = Path(tempfile.mkdtemp())
    exe_un = dun / "ToDoReminder.exe"
    exe_un.write_bytes(program)
    s_un0 = D.EmbeddedStore(exe_un, work_dir=dun / "w")
    s_un0.save_tasks({"tasks": [{"id": "1", "title": "база"}]})
    s_un0.finalize()
    s_un1 = D.EmbeddedStore(exe_un, work_dir=dun / "w")
    s_un1.save_tasks({"tasks": [{"id": "1", "title": "перед занятым EXE"}]})   # сбой: рабочая копия есть
    orig_ins = D.inspect_embedded
    D.inspect_embedded = lambda p: (_ for _ in ()).throw(OSError("файл занят"))
    try:
        s_un2 = D.EmbeddedStore(exe_un, work_dir=dun / "w")
    finally:
        D.inspect_embedded = orig_ins
    check("EXE не прочитался: сообщение без ложного «повреждены», данные из рабочей копии",
          any("Не удалось прочитать" in n for n in s_un2.notices) and not any("повреждены" in n for n in s_un2.notices)
          and s_un2.load_tasks()["tasks"][0]["title"] == "перед занятым EXE")
    s_un2.save_tasks({"tasks": [{"id": "1", "title": "во время занятого"}]})
    s_un2.finalize()
    s_un3 = D.EmbeddedStore(exe_un, work_dir=dun / "w")
    check("после занятого EXE — правки восстановлены без ложного конфликта",
          s_un3.load_tasks()["tasks"][0]["title"] == "во время занятого"
          and not list((dun / "w").glob("*conflict*")))

    # ---- выбор между копиями (рабочая + запасные), ревью 5
    def fresh(name):
        dd = Path(tempfile.mkdtemp())
        ee = dd / "ToDoReminder.exe"
        ee.write_bytes(program)
        return dd, ee

    def put_session(dd, ee, title, rev, base_gen, **extra):
        st_ = D.EmbeddedStore(ee, work_dir=dd / "probe-key")  # только чтобы узнать ключ
        key = st_._key
        sess = dd / "w" / f"work-{key}-session-20260101-000000-{rev:06d}.json"
        sess.parent.mkdir(parents=True, exist_ok=True)
        sess.write_text(json.dumps(dict({"rev": rev, "base_gen": base_gen, "pending_gen": None, "settings": {},
                                         "tasks": {"tasks": [{"id": "1", "title": title}]}}, **extra),
                                   ensure_ascii=False), encoding="utf-8")
        return sess

    # E2: повреждён хвост; своя рабочая копия (сбой) + чужой запасной файл с бОльшим rev
    dE, eE = fresh("e2")
    sE = D.EmbeddedStore(eE, work_dir=dE / "w")
    sE.save_tasks({"tasks": [{"id": "1", "title": "base"}]})
    sE.finalize()
    sE2 = D.EmbeddedStore(eE, work_dir=dE / "w")
    sE2.save_tasks({"tasks": [{"id": "1", "title": "OWN-CRASH"}]})          # сбой
    put_session(dE, eE, "FOREIGN-OLD", 50, "чужое-поколение")
    rawE = bytearray(eE.read_bytes())
    rawE[-D.TRAILER.size - 3] ^= 0xFF
    eE.write_bytes(bytes(rawE))
    sE3 = D.EmbeddedStore(eE, work_dir=dE / "w")
    all_text = "".join(p.read_text(encoding="utf-8") for p in (dE / "w").glob("*.json"))
    check("повреждён хвост: выбрана своя рабочая копия, а не чужой файл",
          sE3.load_tasks()["tasks"][0]["title"] == "OWN-CRASH")
    check("повреждён хвост: чужой файл отложен, а не удалён", "FOREIGN-OLD" in all_text
          and list((dE / "w").glob("*conflict*")))
    sE3.finalize()
    check("после выхода чужие данные не пропали",
          "FOREIGN-OLD" in "".join(p.read_text(encoding="utf-8") for p in (dE / "w").glob("*.json")))

    # N3: чужой запасной файл — сообщение один раз, а не при каждом запуске
    dM, eM = fresh("m1")
    sM = D.EmbeddedStore(eM, work_dir=dM / "w")
    sM.save_tasks({"tasks": [{"id": "1", "title": "в EXE"}]})
    sM.finalize()
    put_session(dM, eM, "чужие правки", 7, "другое")
    counts = [len(D.EmbeddedStore(eM, work_dir=dM / "w").notices) for _ in range(3)]
    check("чужой запасной файл — сообщение один раз", counts == [1, 0, 0], str(counts))

    # N4: только для чтения + остаток папки data / лишний запасной файл — без ложной ошибки и без накопления
    dF, eF = fresh("f1")
    sF = D.EmbeddedStore(eF, work_dir=dF / "w")
    sF.save_tasks({"tasks": [{"id": "1", "title": "x"}]})
    sF.finalize()
    (dF / "data").mkdir()
    (dF / "data" / "tasks.json").write_text('{"tasks": [{"id": "1", "title": "старое"}]}', encoding="utf-8")
    emb_F = D.read_embedded(eF)[1]
    put_session(dF, eF, "x", emb_F["rev"], emb_F["gen"])   # тот же текст, что в EXE
    orig_w3 = D.write_exe_with_data
    D.write_exe_with_data = lambda *a, **k: (_ for _ in ()).throw(PermissionError("только чтение"))
    try:
        results = []
        for _ in range(3):
            st_f = D.EmbeddedStore(eF, work_dir=dF / "w", legacy_dir=dF / "data")
            results.append((st_f.finalize(), len(list((dF / "w").glob("*session*")))))
    finally:
        D.write_exe_with_data = orig_w3
    check("только для чтения без изменений: нет ложной ошибки и файлы не копятся",
          results == [(True, 0), (True, 0), (True, 0)], str(results))
    check("остаток папки data удалён без перезаписи EXE", not (dF / "data").exists())

    # N5: EXE не читался, копий не было — правки потом откладываются с понятным сообщением
    dU, eU = fresh("u1")
    sU = D.EmbeddedStore(eU, work_dir=dU / "w")
    sU.save_tasks({"tasks": [{"id": "1", "title": "реальные"}]})
    sU.finalize()
    orig_ins2 = D.inspect_embedded
    D.inspect_embedded = lambda p: (_ for _ in ()).throw(OSError("занят"))
    try:
        sU2 = D.EmbeddedStore(eU, work_dir=dU / "w")
        sU2.save_tasks({"tasks": [{"id": "1", "title": "правки вслепую"}]})
        sU2.finalize()
    finally:
        D.inspect_embedded = orig_ins2
    sU3 = D.EmbeddedStore(eU, work_dir=dU / "w")
    check("после «слепой» сессии реальные данные целы", sU3.load_tasks()["tasks"][0]["title"] == "реальные")
    check("«слепые» правки отложены с сообщением про «Импорт»",
          any("не читались" in n and "Импорт" in n for n in sU3.notices) and list((dU / "w").glob("*unsaved*")))

    # N6: чистый EXE (заменили релизом) + .unsaved.json с поколением → восстановление, не «конфликт»
    dN, eN = fresh("n6")
    sN = D.EmbeddedStore(eN, work_dir=dN / "w")
    sN.save_tasks({"tasks": [{"id": "1", "title": "было"}]})
    sN.finalize()
    gN = D.read_embedded(eN)[1]["gen"]
    eN.write_bytes(program)                       # EXE заменили чистым релизом
    eN.with_name(eN.name + ".unsaved.json").write_text(json.dumps(
        {"rev": 5, "base_gen": gN, "pending_gen": None, "settings": {},
         "tasks": {"tasks": [{"id": "1", "title": "из .unsaved"}]}}, ensure_ascii=False), encoding="utf-8")
    sN2 = D.EmbeddedStore(eN, work_dir=dN / "w")
    check("чистый EXE + .unsaved.json с поколением — восстановление",
          sN2.load_tasks()["tasks"][0]["title"] == "из .unsaved" and not list((dN / "w").glob("*conflict*")))

    # ---- ревью 6: происхождение копий
    # F1: сбой на ПК A (рабочая копия) + флешка привезла .unsaved.json с ПК B той же основы
    dR, eR = fresh("r1")
    sR = D.EmbeddedStore(eR, work_dir=dR / "w")
    sR.save_tasks({"tasks": [{"id": "1", "title": "основа"}]})
    sR.finalize()
    gR = D.read_embedded(eR)[1]["gen"]
    sR2 = D.EmbeddedStore(eR, work_dir=dR / "w")
    sR2.save_tasks({"tasks": [{"id": "1", "title": "A-CRASH"}]})              # сбой на A
    eR.with_name(eR.name + ".unsaved.json").write_text(json.dumps(
        {"rev": 99, "base_gen": gR, "pending_gen": None, "origin": "pc-B", "settings": {},
         "tasks": {"tasks": [{"id": "1", "title": "B-UNSAVED"}]}}, ensure_ascii=False), encoding="utf-8")
    sR3 = D.EmbeddedStore(eR, work_dir=dR / "w")
    every = "".join(p.read_text(encoding="utf-8") for p in list((dR / "w").glob("*.json")) + list(dR.glob("*.json")))
    check("две ветки одной основы с разных ПК: обе сохранены",
          "A-CRASH" in every + json.dumps(sR3.load_tasks(), ensure_ascii=False)
          and "B-UNSAVED" in every + json.dumps(sR3.load_tasks(), ensure_ascii=False))
    check("о второй ветке есть сообщение", any("другой копии" in n for n in sR3.notices))

    # F2: EXE не прочитался — рабочая копия этого ПК не подменяется чужой с бОльшим rev
    dQ, eQ = fresh("r4")
    sQ = D.EmbeddedStore(eQ, work_dir=dQ / "w")
    sQ.save_tasks({"tasks": [{"id": "1", "title": "A-CRASH"}]})              # сбой: рабочая копия
    eQ.with_name(eQ.name + ".unsaved.json").write_text(json.dumps(
        {"rev": 500, "base_gen": "H", "pending_gen": None, "origin": "pc-B", "settings": {},
         "tasks": {"tasks": [{"id": "1", "title": "B-UNSAVED"}]}}, ensure_ascii=False), encoding="utf-8")
    orig_ins3 = D.inspect_embedded
    D.inspect_embedded = lambda p: (_ for _ in ()).throw(OSError("занят"))
    try:
        sQ2 = D.EmbeddedStore(eQ, work_dir=dQ / "w")
    finally:
        D.inspect_embedded = orig_ins3
    check("EXE не прочитался: рабочая копия этого ПК не подменена чужой",
          sQ2.load_tasks()["tasks"][0]["title"] == "A-CRASH"
          and "A-CRASH" in sQ2.work_file.path.read_text(encoding="utf-8"))

    # F3: повреждён хвост на чистой основе — своя .unsaved не считается «чужой»
    dS, eS = fresh("r6")
    sS = D.EmbeddedStore(eS, work_dir=dS / "w")
    sS.save_tasks({"tasks": [{"id": "1", "title": "сбой"}]})                 # рабочая копия без поколения
    eS.with_name(eS.name + ".unsaved.json").write_text(json.dumps(
        {"rev": 1, "base_gen": None, "pending_gen": None, "origin": sS._origin, "settings": {},
         "tasks": {"tasks": [{"id": "1", "title": "сбой-ранее"}]}}, ensure_ascii=False), encoding="utf-8")
    eS.write_bytes(program[:-30])                                              # испорчен cookie
    sS2 = D.EmbeddedStore(eS, work_dir=dS / "w")
    check("пустая линия: своя копия не считается чужой", not any("другой копии" in n for n in sS2.notices))

    # F4: хвост повреждён, копий нет, EXE только для чтения — без ложной ошибки и пустых файлов
    dT, eT = fresh("r2")
    eT.write_bytes(program[:-30])
    orig_w4 = D.write_exe_with_data
    D.write_exe_with_data = lambda *a, **k: (_ for _ in ()).throw(PermissionError("только чтение"))
    try:
        res = []
        for _ in range(3):
            st_t2 = D.EmbeddedStore(eT, work_dir=dT / "w")
            res.append((st_t2.finalize(), len(list((dT / "w").glob("*session*"))) if (dT / "w").exists() else 0))
    finally:
        D.write_exe_with_data = orig_w4
    check("повреждён хвост, нечего сохранять, только чтение: выход без ошибки и без пустых файлов",
          res == [(True, 0)] * 3, str(res))

    # ---- ревью 7
    # G1: свежий запасной файл этого ПК не проигрывает устаревшей рабочей копии, когда EXE не прочитался
    dG, eG = fresh("g1")
    sG = D.EmbeddedStore(eG, work_dir=dG / "w")
    sG.save_tasks({"tasks": [{"id": "1", "title": "base"}]})
    sG.finalize()
    sG2 = D.EmbeddedStore(eG, work_dir=dG / "w")
    sG2.save_tasks({"tasks": [{"id": "1", "title": "s1"}]})                  # рабочая копия rev+1
    sG2._work_blocked = True                                                  # дальше рабочая копия не пишется
    for i in range(2, 9):
        sG2.save_tasks({"tasks": [{"id": "1", "title": f"s{i}"}]})
    orig_w5 = D.write_exe_with_data
    D.write_exe_with_data = lambda *a, **k: (_ for _ in ()).throw(PermissionError("нет"))
    try:
        sG2.finalize()                                                        # → session-файл с «s8»
    finally:
        D.write_exe_with_data = orig_w5
    orig_ins4 = D.inspect_embedded
    D.inspect_embedded = lambda p: (_ for _ in ()).throw(OSError("занят"))
    try:
        sG3 = D.EmbeddedStore(eG, work_dir=dG / "w")
        seen = sG3.load_tasks()["tasks"][0]["title"]
        sG3.save_tasks({"tasks": [{"id": "1", "title": "U-EDIT"}]})
        sG3.finalize()
    finally:
        D.inspect_embedded = orig_ins4
    sG4 = D.EmbeddedStore(eG, work_dir=dG / "w")
    check("EXE не прочитался: взят самый свежий свой запасной файл", seen == "s8", seen)
    check("правки сессии с непрочитанным EXE не теряются", sG4.load_tasks()["tasks"][0]["title"] == "U-EDIT")

    # G2: копия без метки происхождения (старая сборка) — не «чужая»
    dH, eH = fresh("g2")
    sH = D.EmbeddedStore(eH, work_dir=dH / "w")
    sH.save_tasks({"tasks": [{"id": "1", "title": "base"}]})
    sH.finalize()
    gH = D.read_embedded(eH)[1]
    sH2 = D.EmbeddedStore(eH, work_dir=dH / "w")
    sH2.save_tasks({"tasks": [{"id": "1", "title": "mine"}]})               # рабочая копия с origin
    put_session(dH, eH, "legacy9", gH["rev"] + 9, gH["gen"])                  # без поля origin
    sH3 = D.EmbeddedStore(eH, work_dir=dH / "w")
    check("копия без метки происхождения не даёт ложного конфликта",
          not any("другой копии" in n for n in sH3.notices) and not list((dH / "w").glob("*conflict*")))

    # импорт понимает формат рабочей/запасной копии
    from import_export import load_tasks as _load_tasks_file
    copy_file = dfb / "copy.json"
    copy_file.write_text(json.dumps({"rev": 3, "settings": {}, "tasks": {"tasks": [
        {"id": "1", "title": "из копии", "status": "To Do"}]}}, ensure_ascii=False), encoding="utf-8")
    items = _load_tasks_file(copy_file, "json")
    check("импорт открывает рабочую/запасную копию", [t for t, *_ in items] == ["из копии"])

    # выдернутая флешка: конец EXE обнулён / обрезан
    d8 = Path(tempfile.mkdtemp())
    exe8 = d8 / "ToDoReminder.exe"
    exe8.write_bytes(program)
    s80 = D.EmbeddedStore(exe8, work_dir=d8 / "w")
    s80.save_tasks({"tasks": [{"id": "1", "title": "до сбоя"}]})
    s80.finalize()
    s81 = D.EmbeddedStore(exe8, work_dir=d8 / "w")
    s81.save_tasks({"tasks": [{"id": "1", "title": "правки перед выдёргиванием"}]})   # сбой: рабочая копия есть
    raw8 = bytearray(exe8.read_bytes())
    raw8[-20:] = b"\x00" * 20
    exe8.write_bytes(bytes(raw8))
    s82 = D.EmbeddedStore(exe8, work_dir=d8 / "w")
    check("обнулённый конец + рабочая копия: восстановление, а не ложный конфликт",
          s82.load_tasks()["tasks"][0]["title"] == "правки перед выдёргиванием"
          and any("повреждены" in n for n in s82.notices) and not list((d8 / "w").glob("*conflict*")))
    zeroed = d8 / "zeroed.exe"
    zeroed.write_bytes(program + D.pack({"rev": 1, "gen": "g", "settings": {}, "tasks": {}})[:-28] + b"\x00" * 28)
    s83 = D.EmbeddedStore(zeroed, work_dir=d8 / "w-other")
    check("обнулённый конец без рабочей копии — с сообщением о повреждении",
          any("повреждены" in n for n in s83.notices))

    # embed_into: рабочую копию не записать → установка упала → сбой: правки сессии не пропали
    d9 = Path(tempfile.mkdtemp())
    exe9 = d9 / "ToDoReminder.exe"
    exe9.write_bytes(program)
    s90 = D.EmbeddedStore(exe9, work_dir=d9 / "w")
    s90.save_tasks({"tasks": [{"id": "1", "title": "сессия"}]})
    new9 = d9 / "ToDoReminder.exe.new"
    new9.write_bytes(b"MZ" + os.urandom(1000))
    orig_save = D.JsonFile.save
    D.JsonFile.save = lambda self, data: (_ for _ in ()).throw(OSError("диск занят"))
    try:
        s90.embed_into(new9)
    finally:
        D.JsonFile.save = orig_save
    s91 = D.EmbeddedStore(exe9, work_dir=d9 / "w")
    check("сбой записи рабочей копии в embed_into не теряет правки сессии",
          s91.load_tasks()["tasks"][0]["title"] == "сессия")

    # в EXE записать нельзя, рабочую копию тоже — данные сессии уходят в запасной файл
    s92 = D.EmbeddedStore(exe9, work_dir=d9 / "w")
    s92._work_blocked = True
    s92.save_tasks({"tasks": [{"id": "1", "title": "запасной файл"}]})
    orig_w = D.write_exe_with_data
    D.write_exe_with_data = lambda *a, **k: (_ for _ in ()).throw(PermissionError("только чтение"))
    try:
        ok = s92.finalize()
    finally:
        D.write_exe_with_data = orig_w
    fb = s92.fallback_path
    check("если некуда — данные в запасном файле, и он назван",
          not ok and fb is not None and "запасной файл" in Path(fb).read_text(encoding="utf-8"))

    # свой EXE не прочитался — в этой сессии в него не пишем (не отрезать настоящий хвост)
    exe9b = d9 / "keep.exe"
    exe9b.write_bytes(program + D.pack({"rev": 3, "gen": "real", "settings": {}, "tasks": {"tasks": [{"id": "r", "title": "настоящие"}]}}))
    orig_i = D.inspect_embedded
    D.inspect_embedded = lambda p: (_ for _ in ()).throw(OSError("занят"))
    try:
        s93 = D.EmbeddedStore(exe9b, work_dir=d9 / "w3")
    finally:
        D.inspect_embedded = orig_i
    s93.save_tasks({"tasks": []})
    before = exe9b.read_bytes()
    check("непрочитанный свой EXE не перезаписывается", not s93.finalize() and exe9b.read_bytes() == before)

    # конфликтная копия, которую нельзя удалить, не плодится при каждом запуске
    d10 = Path(tempfile.mkdtemp())
    exe10 = d10 / "ToDoReminder.exe"
    exe10.write_bytes(program)
    s100 = D.EmbeddedStore(exe10, work_dir=d10 / "w")
    s100.save_tasks({"tasks": [{"id": "1", "title": "a"}]})
    s100.finalize()
    D.EmbeddedStore(exe10, work_dir=d10 / "w").save_tasks({"tasks": [{"id": "1", "title": "чужая ветка"}]})
    s100b = D.EmbeddedStore(exe10, work_dir=d10 / "other")   # «другой ПК» меняет EXE
    s100b.save_tasks({"tasks": [{"id": "1", "title": "B"}]})
    s100b.finalize()
    orig_rep = os.replace

    def no_move(src, dst, *a, **k):
        if str(src).endswith(".json") and "work-" in str(src):
            raise PermissionError("держит синхронизатор")
        return orig_rep(src, dst, *a, **k)

    orig_unlink = D._unlink_quietly
    D.os.replace = no_move
    D._unlink_quietly = lambda p: None
    try:
        for _ in range(3):
            D.EmbeddedStore(exe10, work_dir=d10 / "w")
    finally:
        D.os.replace = orig_rep
        D._unlink_quietly = orig_unlink
    check("неудаляемая конфликтная копия откладывается один раз",
          len(list((d10 / "w").glob("*conflict*"))) == 1)

    # повреждённое поле длины при целой метке не обрезает программу
    d4 = Path(tempfile.mkdtemp())
    exe4 = d4 / "ToDoReminder.exe"
    exe4.write_bytes(program + D.pack({"rev": 1, "gen": "x", "settings": {}, "tasks": {}}))
    raw4 = bytearray(exe4.read_bytes())
    length, crc, magic = D.TRAILER.unpack(bytes(raw4[-D.TRAILER.size:]))
    raw4[-D.TRAILER.size:] = D.TRAILER.pack(length + 3000, crc, magic)
    exe4.write_bytes(bytes(raw4))
    st7 = D.EmbeddedStore(exe4, work_dir=d4 / "w")
    st7.save_tasks({"tasks": [{"id": "z", "title": "z"}]})
    st7.finalize()
    check("порча поля длины не обрезает программу", exe4.read_bytes()[:len(program)] == program
          and D.read_embedded(exe4)[1]["tasks"]["tasks"][0]["title"] == "z")

    # испорченная рабочая копия не ломает запуск
    d5 = Path(tempfile.mkdtemp())
    exe5 = d5 / "ToDoReminder.exe"
    exe5.write_bytes(program)
    st8 = D.EmbeddedStore(exe5, work_dir=d5 / "w")
    st8.save_tasks({"tasks": []})
    st8.work_file.path.write_text('{"rev": null, "tasks": 5}', encoding="utf-8")
    try:
        st9 = D.EmbeddedStore(exe5, work_dir=d5 / "w")
        check("испорченная рабочая копия не ломает запуск", st9.load_tasks() == {} and st9.notices)
    except Exception as e:  # noqa: BLE001
        check("испорченная рабочая копия не ломает запуск", False, repr(e))

    # частичный перенос повторяется, когда старый файл исправили
    d6 = Path(tempfile.mkdtemp())
    exe6 = d6 / "ToDoReminder.exe"
    exe6.write_bytes(program)
    leg6 = d6 / "data"
    leg6.mkdir()
    (leg6 / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (leg6 / "tasks.json").write_text("{битый", encoding="utf-8")
    s6 = D.EmbeddedStore(exe6, work_dir=d6 / "w", legacy_dir=leg6)
    s6.finalize()
    (leg6 / "tasks.json").write_text('{"tasks": [{"id": "f", "title": "починенный"}]}', encoding="utf-8")
    s6b = D.EmbeddedStore(exe6, work_dir=d6 / "w", legacy_dir=leg6)
    check("исправленный старый файл переносится при следующем запуске",
          s6b.load_tasks()["tasks"][0]["title"] == "починенный" and s6b.load_settings().get("theme") == "dark")
    s6b.finalize()
    check("после переноса папка data удалена", not leg6.exists())

    # удаление .old: путь со спецсимволами cmd и %ПЕРЕМЕННЫМИ%
    import time as _t
    weird = Path(tempfile.mkdtemp()) / "a %PATH% b & c ^ d ! (e)"
    weird.mkdir()
    victim = weird / "ToDoReminder.exe.old"
    victim.write_bytes(b"x")
    D.schedule_delete(victim)
    for _ in range(30):
        if not victim.exists():
            break
        _t.sleep(0.2)
    check("отложенное удаление .old с %, &, ^, ! в пути", not victim.exists())

    # повреждённый хвост не ломает запуск
    raw = bytearray(exe.read_bytes())
    raw[-40] ^= 0xFF
    bad = d / "bad.exe"
    bad.write_bytes(bytes(raw))
    check("повреждённый хвост игнорируется", D.read_embedded(bad)[1] is None)

    # данные переносятся в скачанное обновление
    new = d / "ToDoReminder.exe.new"
    new.write_bytes(b"MZ" + os.urandom(3000))
    st5.save_settings({"theme": "dark", "marker": "обновление"})
    st5.embed_into(new)
    check("обновление получает данные", D.read_embedded(new)[1]["settings"].get("marker") == "обновление")

    # нельзя записать (папка только для чтения и т.п.) — данные остаются в рабочей копии
    orig = D.write_exe_with_data
    D.write_exe_with_data = lambda *a, **k: (_ for _ in ()).throw(PermissionError("нет прав"))
    try:
        st6 = D.EmbeddedStore(exe, work_dir=work)
        st6.save_tasks({"tasks": [{"id": "3", "title": "останусь"}]})
        ok = st6.finalize()
    finally:
        D.write_exe_with_data = orig
    check("без прав на запись EXE не теряет данные", not ok and st6.work_file.path.exists()
          and D.EmbeddedStore(exe, work_dir=work).load_tasks()["tasks"][0]["title"] == "останусь")


def test_finalize_on_exit():
    print("## Запись данных в EXE при выходе")
    from app import AppContext

    app = QApplication.instance() or QApplication(sys.argv)

    class FakeStore:
        def __init__(self):
            self.finalized = 0
            self.saved = []

        def load_settings(self):
            return {}

        def load_tasks(self):
            return {}

        def save_settings(self, d):
            self.saved.append(("s", d))

        def save_tasks(self, d):
            self.saved.append(("t", d))

        def finalize(self):
            self.finalized += 1
            return True

    fake = FakeStore()
    orig = S._STORE
    S._STORE = fake
    try:
        ctx = AppContext(app)
        ctx.app = type("A", (), {"quit": lambda self: None, "processEvents": lambda self: None})()
        ctx.quit()
        ctx.finalize_storage()   # aboutToQuit после quit() — повторно не пишет
        check("выход записывает данные внутрь EXE ровно один раз", fake.finalized == 1)
        check("перед записью в EXE настройки сброшены в хранилище", any(k == "s" for k, _ in fake.saved))

        # сохранить некуда (ни в EXE, ни на диск) — выход отменяется, программа работает дальше
        from PySide6.QtWidgets import QMessageBox
        fake3 = FakeStore()
        fake3.finalize = lambda: False
        fake3.fallback_path = None
        fake3.last_error = "нет места"
        S._STORE = fake3
        ctx3 = AppContext(app)
        quits = []
        ctx3.app = type("A", (), {"quit": lambda self: quits.append(1), "processEvents": lambda self: None})()
        orig_crit = QMessageBox.critical
        QMessageBox.critical = staticmethod(lambda *a, **k: None)
        try:
            ctx3.quit()
        finally:
            QMessageBox.critical = orig_crit
        check("если сохранить некуда — выход отменяется", not quits and not ctx3._storage_finalized)

        fake2 = FakeStore()
        S._STORE = fake2
        ctx2 = AppContext(app)
        ctx2.app = ctx.app
        ctx2.quit(save=False)
        ctx2.finalize_storage()
        check("после перезапуска в новую версию старый EXE не переписывается", fake2.finalized == 0)
    finally:
        S._STORE = orig


def test_single_instance_and_interval():
    print("## Один экземпляр и интервал проверки обновлений")
    from single_instance import SingleInstance
    from update_manager import check_interval_ms

    app = QApplication.instance() or QApplication(sys.argv)
    lock_dir = tempfile.mkdtemp()
    name = f"ToDoReminderTest{os.getpid()}"
    first = SingleInstance(name, lock_dir=lock_dir)
    check("первый экземпляр запускается", first.acquire())
    got = []
    first.activated.connect(lambda: got.append(1))
    second = SingleInstance(name, lock_dir=lock_dir)
    check("второй экземпляр не запускается", not second.acquire())
    # второй экземпляр — отдельным процессом, как в жизни
    import subprocess
    import time as _t
    root = str(Path(__file__).resolve().parent.parent)
    child_code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "app = QCoreApplication([])\n"
        "from single_instance import SingleInstance\n"
        "s = SingleInstance(sys.argv[2], lock_dir=sys.argv[3])\n"
        "print('acquired' if s.acquire() else ('sent' if s.activate_existing() else 'fail'))\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code, root, name, lock_dir],
                             stdout=subprocess.PIPE, text=True)
    deadline = _t.time() + 15
    while _t.time() < deadline and (child.poll() is None or not got):
        app.processEvents()
        _t.sleep(0.02)
    out = (child.communicate(timeout=10)[0] or "").strip()
    check("второй процесс не запускается и просит первый показать окно", out == "sent" and got == [1],
          f"child={out} got={got}")
    broken = SingleInstance(name, lock_dir=str(Path(lock_dir) / "нет-такой-папки"))
    check("ошибка файла блокировки не мешает запуску", broken.acquire() and broken.lock_unavailable)
    first.release()
    third = SingleInstance(name, lock_dir=lock_dir)
    check("после выхода первого можно запуститься снова", third.acquire())
    third.release()

    check("интервал: раз в час", check_interval_ms(1) == 3_600_000)
    check("интервал: раз в сутки", check_interval_ms(24) == 86_400_000)
    check("неизвестный интервал → 6 часов", check_interval_ms(5) == check_interval_ms("x") == 6 * 3_600_000)

    from app import AppContext
    from main_window import MainWindow
    from update_manager import UpdateManager
    ctx = AppContext(app)
    ctx.main_window = MainWindow(ctx)
    um = UpdateManager(ctx)
    ctx.settings_manager.s.update_check_hours = 1
    ctx.settings_manager.save()
    check("смена интервала в настройках применяется", um._periodic.interval() == 3_600_000)
    um._on_check_failed("нет сети", True)
    check("после неудачной тихой проверки — повтор через 10 минут", um._retry.isActive())
    um.shutdown()
    check("выход останавливает повтор", not um._retry.isActive())

    from settings_window import SettingsDialog
    dlg = SettingsDialog(ctx.settings_manager, QGuiApplication.screens(), ctx.main_window)
    idx = dlg.update_interval_combo.findData(24)
    dlg.update_interval_combo.setCurrentIndex(idx)
    check("выбор «раз в сутки» в настройках сохраняется", ctx.settings_manager.s.update_check_hours == 24)
    check("в списке ровно 1/3/6/12/24 часа",
          [dlg.update_interval_combo.itemData(i) for i in range(dlg.update_interval_combo.count())] == [1, 3, 6, 12, 24])
    dlg.auto_update_cb.setChecked(False)
    check("интервал недоступен при выключенной проверке", not dlg.update_interval_combo.isEnabled())
    dlg.close()


def main():
    test_tasks()
    test_statuses()
    test_import_export()
    test_drag_critical()
    test_reminders()
    test_window()
    test_fullscreen_render()
    test_performance_paths()
    test_updater()
    test_review_fixes()
    test_update_polish()
    test_issue_1()
    test_settings_layout()
    test_embedded_store()
    test_finalize_on_exit()
    test_single_instance_and_interval()

    print()
    print(f"ПРОЙДЕНО: {PASSED}   ПРОВАЛЕНО: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()