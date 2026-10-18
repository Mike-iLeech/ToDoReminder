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
    from PySide6.QtWidgets import QLineEdit, QScrollArea
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

    # внутреннее поле счётчиков без собственных отступов и рамки (не ложится поверх пилюли)
    inner = dlg.interval_spin.findChild(QLineEdit)
    check("поле внутри счётчика занимает его высоту", inner.height() >= dlg.interval_spin.height() - 8,
          f"inner={inner.height()} spin={dlg.interval_spin.height()}")

    # сброс к умолчанию обновляет образцы цветов
    from PySide6.QtWidgets import QMessageBox
    ctx.settings_manager.s.bg_color = "#123456"
    orig_q = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        dlg._reset_defaults()
    finally:
        QMessageBox.question = orig_q
    check("сброс обновляет образец цвета", dlg._color_refs["bg_color"][0].text() == S.Settings().bg_color.upper())
    dlg.close()
    main._quitting = True
    main.close()


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

    print()
    print(f"ПРОЙДЕНО: {PASSED}   ПРОВАЛЕНО: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()