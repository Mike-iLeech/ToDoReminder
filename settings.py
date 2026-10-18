from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QTimer, Signal

from autostart import autostart_command, build_command, is_autostart_enabled, set_autostart
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
    fullscreen_min_font_size: int = 14          # минимальный размер шрифта при адаптации в полноэкранном окне
    fullscreen_columns_todo: int = 2            # число колонок для задач To Do в полноэкранном уведомлении
    fullscreen_columns_started: int = 2         # число колонок для задач Started в полноэкранном уведомлении
    fullscreen_columns_done: int = 2            # число колонок для задач Done в полноэкранном уведомлении
    auto_remove_done: bool = True               # удалять Done в начале нового дня и при запуске
    auto_update_check: bool = True             # проверять обновления на GitHub автоматически
    update_skip_version: str = ""               # версия, которую пользователь попросил не предлагать


class SettingsManager(QObject):
    """Настройки в памяти + отложенная запись на диск.

    save() сразу оповещает подписчиков (changed), а файл пишется одним разом через
    SAVE_DELAY_MS после последнего изменения: слайдер прозрачности или перетаскивание
    окна больше не дёргают fsync и реестр на каждый пиксель. flush() пишет немедленно
    (вызывается при выходе).
    """

    changed = Signal()
    SAVE_DELAY_MS = 400

    def __init__(self) -> None:
        super().__init__()
        self.s = self._load()
        self._closed = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.flush)

    def _load(self) -> Settings:
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
        self._save_timer.start()
        self.changed.emit()

    def discard_pending(self) -> None:
        """Отменить отложенную и все последующие записи (данные уже сохранены, процесс завершается)."""
        self._save_timer.stop()
        self._closed = True

    def flush(self) -> None:
        """Немедленно записать настройки на диск (и автозапуск в реестр, если он менялся)."""
        self._save_timer.stop()
        if self._closed:
            return
        JsonFile(SETTINGS_PATH).save(asdict(self.s))
        # реестр трогаем только при расхождении (в т.ч. если EXE переехал в другую папку)
        wanted = build_command() if self.s.autostart else None
        if autostart_command() != wanted:
            set_autostart(self.s.autostart)