from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
import sys

from PySide6.QtCore import QObject, Signal

from autostart import is_autostart_enabled, set_autostart
from storage import JsonFile

if getattr(sys, "frozen", False):
    # в собранном EXE данные хранятся рядом с исполняемым файлом
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
TASKS_PATH = DATA_DIR / "tasks.json"


@dataclass
class Settings:
    reminder_interval_seconds: int = 3600
    show_done_in_fullscreen: bool = False
    monitor_name: str = ""
    text_size: int = 32
    font_family: str = "Segoe UI"
    font_style_index: int = 0      # 0 Обычный, 1 Жирный, 2 Курсив, 3 Жирный курсив
    alignment_index: int = 0       # 0 Слева, 1 По центру, 2 Справа
    bg_color: str = "#FFFFFF"
    text_color: str = "#000000"
    opacity_percent: int = 0       # 0 = непрозрачно, 100 = полностью прозрачно
    autostart: bool = False
    tray_action_index: int = 0     # 0 Открывать основное окно, 1 Ничего
    always_on_top: bool = True     # полноэкранные окна поверх всех окон
    theme: str = "light"           # "light" или "dark"
    color_status_todo: str = "#5B7BD5"
    color_status_started: str = "#E0913C"
    color_status_done: str = "#4CAF50"
    window_x: int = -9999          # sentinel: позиция не сохранена
    window_y: int = -9999
    regular_reset_date: str = ""   # день, когда регулярным задачам уже сбрасывали статус
    urgent_fullscreen_size_delta: int = 5       # на сколько px больше базового размера шрифта срочных дел
    urgent_fullscreen_color: str = "#FF0000"    # цвет текста срочных дел в полноэкранном уведомлении
    urgent_fullscreen_style_index: int = 1      # 0 Обычный, 1 Жирный, 2 Курсив, 3 Жирный курсив


class SettingsManager(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.s = self._load()

    def _load(self) -> Settings:
        defaults = Settings()
        data = JsonFile(SETTINGS_PATH).load({})
        if not isinstance(data, dict):
            data = {}
        result = Settings()
        for field in fields(Settings):
            if field.name not in data:
                continue
            raw = data[field.name]
            try:
                if isinstance(raw, str):
                    value = str(raw)
                elif isinstance(raw, bool):
                    value = bool(raw)
                elif isinstance(raw, (int, float)):
                    value = int(raw)
                else:
                    value = raw
            except (TypeError, ValueError):
                continue
            setattr(result, field.name, value)
        if is_autostart_enabled():
            result.autostart = True
        return result

    def save(self) -> None:
        data = asdict(self.s)
        JsonFile(SETTINGS_PATH).save(data)
        set_autostart(self.s.autostart)
        self.changed.emit()