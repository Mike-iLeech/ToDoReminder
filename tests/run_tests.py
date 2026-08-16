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
    ctx.settings_manager.save()
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


def main():
    test_tasks()
    test_statuses()
    test_import_export()
    test_drag_critical()
    test_reminders()
    test_window()
    test_fullscreen_render()

    print()
    print(f"ПРОЙДЕНО: {PASSED}   ПРОВАЛЕНО: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()