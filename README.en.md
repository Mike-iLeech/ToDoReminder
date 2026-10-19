# ToDo Reminder

![Version](https://img.shields.io/badge/version-2.7.2.0-blue)
![License](https://img.shields.io/badge/license-GPLv3-blue)
![Python](https://img.shields.io/badge/Python-3.14-informational)
![Framework](https://img.shields.io/badge/UI-PySide6-blueviolet)

A portable daily planner & reminder built on **Python + PySide6** for Windows.
One small 300×700 window, tasks with **To Do / Started / Done** statuses, drag & drop,
fullscreen timer reminders, dark/light theme and a system tray.

> Made with love 💙

---

## Features

- **Quick add** — Enter or the "✓" button. New tasks appear at the top of the list.
- **Status cycling** — a status button on every task. **LMB** — forward (To Do → Started → Done), **RMB** — back.
  Status colors (and reminder markers) are configurable.
- **Drag & drop** tasks with the mouse — no "ghost" or insertion bar.
- **Rename by double-click**: Enter or click elsewhere — save, **Esc** — cancel.
- **Recurring tasks** — via right-click. When a new day starts, the status resets to To Do and the task moves to the top,
  even if the app was closed all that time.
- **Timer and fullscreen reminder** — a list grouped by status columns with colored markers, always on top.
- **Dark / light theme** — toggle button; window title bars are also themed via DWM.
- **System tray** — closing minimizes to tray, LMB restores the window, RMB opens the menu (including "Exit").
- **Import / export** as **JSON / TXT / CSV**.
- **Clear list** only after confirmation.
- **Portability** — settings and tasks are stored inside the EXE itself: no files next to it; copy the EXE to a USB stick and the data goes with it.
- **Single instance** — launching again just shows the running window.
- **Auto-update** — new versions are downloaded straight from GitHub Releases.

## Requirements

- Windows 10 / 11
- Python 3.10+ (developed on 3.14)
- Dependency: `PySide6`

## Run from source

```bash
pip install -r requirements.txt
python main.py
```

## Build a portable EXE

```powershell
pip install -r requirements.txt
.\build.ps1
```

The script generates the icon and version metadata (from `version.py`) and builds a one-file EXE with PyInstaller.

## Releases and auto-update

The app updates itself from **GitHub Releases** — no separate server is needed. It queries
`api.github.com/repos/Mike-iLeech/ToDoReminder/releases/latest`, compares the tag with `APP_VERSION`
and, if newer, offers to download the `ToDoReminder.exe` asset (SHA-256 verified), swaps its own EXE
and restarts. Settings and tasks are carried over into the new EXE. Check frequency is configurable (1/3/6/12/24 hours).

To release: bump `APP_VERSION` in `version.py`, add a `CHANGELOG.md` section, merge to `main` and tag
`vX.Y.Z.W`. The GitHub Actions workflow runs the tests, builds the EXE and publishes the release.
Versions before 2.7.0.0 have no auto-update — move to 2.7.0.0 manually once.

Result: `dist\ToDoReminder.exe`. It needs nothing but itself —
settings and tasks live inside it (when run from source — in the `data` folder).

## Run tests

```bash
python tests\run_tests.py
```

## Project structure

```
main.py                 entry point
app.py                  app context, tray, daily checks
main_window.py          main window, timer, help
settings_window.py      settings window
task_widget.py          task card (status button, rename)
drag_manager.py         task list + drag & drop
reminder_window.py      fullscreen reminder
models.py               task model and storage
settings.py             settings (dataclass + manager)
theme.py                themes, styles, dark title bars
system_tray.py          system tray
import_export.py        JSON/TXT/CSV import & export
autostart.py, storage.py  autostart and storage
version.py              app version
updater.py              auto-update: GitHub API, download, EXE swap
update_manager.py       auto-update: background checks and dialogs
resources/icon.ico      icon
tests/run_tests.py      automated tests
docs/                   project documentation (technical specification)
```

## Documentation

- **Technical specification** the app was built from: [docs/Technical_Specification.md](docs/Technical_Specification.md)
- Project wiki: [github.com/Mike-iLeech/ToDoReminder/wiki](https://github.com/Mike-iLeech/ToDoReminder/wiki)

## License

Distributed under the **GNU General Public License v3.0 (GPLv3)** — free software:
you can use, modify and redistribute it, preserving authorship and the same
license on derivative works. Full text: see [LICENSE](LICENSE).

---
Full changelog: [CHANGELOG.md](CHANGELOG.md).