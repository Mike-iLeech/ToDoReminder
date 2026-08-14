# ToDo Reminder

![Версия](https://img.shields.io/badge/version-2.5.0-blue)
![Лицензия](https://img.shields.io/badge/license-GPLv3-blue)
![Python](https://img.shields.io/badge/Python-3.14-informational)
![Framework](https://img.shields.io/badge/UI-PySide6-blueviolet)

Портативный ежедневник-напоминатель на **Python + PySide6** для Windows.
Одно маленькое окно 300×700, задачи со статусами **To Do / Started / Done**, перетаскивание,
полноэкранные напоминания по таймеру, тёмная/светлая тема и системный трей.

> Приложение сделано специально с любовью 💙

---

## Возможности

- **Быстрое добавление** — Enter или кнопка «✓». Новые дела появляются сверху списка.
- **Статусы по кругу** — кнопка статуса у каждого дела. **ЛКМ** — вперёд (To Do → Started → Done), **ПКМ** — назад.
  Цвета статусов (и маркеров в напоминании) настраиваются.
- **Перетаскивание** дел мышкой — без «призрака» и полосы вставки.
- **Переименование** двойным кликом: Enter или клик мимо — сохранить, **Esc** — отменить.
- **Регулярные задачи** — по правому клику. С наступлением нового дня статус сбрасывается в To Do и дело поднимается вверх,
  даже если приложение всё это время было закрыто.
- **Таймер и полноэкранное напоминание** — список по колонкам статусов с цветными маркерами, поверх всех окон.
- **Тёмная / светлая тема** — переключается кнопкой, заголовки (шапки) окон тоже меняются через DWM.
- **Системный трей** — закрытие сворачивает в трей, ЛКМ возвращает окно, ПКМ — меню (включая «Выход»).
- **Импорт / экспорт** в **JSON / TXT / CSV**.
- **Очистка списка** только после подтверждения.
- **Портативность** — все данные в папке `data` рядом с программой.

## Требования

- Windows 10 / 11
- Python 3.10+ (разработка велась на 3.14)
- Зависимости: `PySide6`

## Запуск из исходников

```bash
pip install -r requirements.txt
python main.py
```

## Сборка портативного EXE

```bash
# зависимости для сборки
pip install pyinstaller

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "ToDoReminder" `
    --icon "resources\icon.ico" `
    --version-file "version_info.txt" `
    --add-data "resources\icon.ico;resources" `
    main.py
```

Готовый файл: `dist\ToDoReminder.exe`. Он не требует ничего кроме себя —
данные создаются рядом (папка `data`).

## Быстрый запуск тестов

```bash
python tests\run_tests.py
```

## Структура проекта

```
main.py                 точка входа
app.py                  контекст приложения, трей, ежедневные проверки
main_window.py          главное окно, таймер, справка
settings_window.py      окно настроек
task_widget.py          карточка задачи (кнопка статуса, переименование)
drag_manager.py         список задач + drag & drop
reminder_window.py      полноэкранное напоминание
models.py               модель задачи и хранилище
settings.py             настройки (dataclass + менеджер)
theme.py                темы, стили, тёмные заголовки
system_tray.py          системный трей
import_export.py        импорт/экспорт JSON/TXT/CSV
autostart.py, storage.py  автозапуск и хранилище
version.py              версия приложения
resources/icon.ico      иконка
tests/run_tests.py      60 автотестов
docs/                   документация проекта (техническое задание)
```

## Документация

- **Техническое задание**, по которому разрабатывалось приложение: [docs/Technical_Specification.md](docs/Technical_Specification.md)
- Wiki проекта: [github.com/mixanizmus1993-debug/ToDoReminder/wiki](https://github.com/mixanizmus1993-debug/ToDoReminder/wiki)

## Лицензия

Проект распространяется под **GNU General Public License v3.0 (GPLv3)** — свободная
лицензия: можно использовать, изменять и распространять, сохраняя авторство и ту же
лицензию на производные работы. Полный текст — см. файл [LICENSE](LICENSE).

---
Полный список изменений: [CHANGELOG.md](CHANGELOG.md).