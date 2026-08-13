from __future__ import annotations

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "ToDoReminder"


def build_command() -> str:
    flag = "--hide"
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {flag}'
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}" {flag}'


def set_autostart(enabled: bool) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, build_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, APP_VALUE_NAME)
            return True
    except (OSError, FileNotFoundError):
        return False