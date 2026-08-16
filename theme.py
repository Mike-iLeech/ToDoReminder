from __future__ import annotations

import ctypes
import math
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

LIGHT = {
    "window_bg": "#F3F6FB",
    "card_bg": "#FFFFFF",
    "card_border": "#E6ECF6",
    "card_hover": "#B9C8E4",
    "text": "#1A2233",
    "muted": "#7A8599",
    "input_bg": "#FFFFFF",
    "input_border": "#D7DFEA",
    "hover": "#EAF0FB",
    "pressed": "#DFE8F7",
    "scrollbar": "#C7D1E0",
    "scrollbar_hover": "#A9B8CE",
    "accent": "#4F7CF7",
    "accent_hover": "#3E68E0",
    "accent_pressed": "#3357C4",
    "rep_border": "#4F7CF7",
    "reminder_bg": "#FFFFFF",
    "reminder_text": "#000000",
    "reminder_urgent_text": "#B71C1C",
}

DARK = {
    "window_bg": "#171C26",
    "card_bg": "#222A39",
    "card_border": "#2F3A4D",
    "card_hover": "#46536B",
    "text": "#E6EAF2",
    "muted": "#93A0B5",
    "input_bg": "#222A39",
    "input_border": "#38455C",
    "hover": "#2B3648",
    "pressed": "#333F56",
    "scrollbar": "#38455C",
    "scrollbar_hover": "#4C5E78",
    "accent": "#4F7CF7",
    "accent_hover": "#3E68E0",
    "accent_pressed": "#3357C4",
    "rep_border": "#6B9AFF",
    "reminder_bg": "#171C26",
    "reminder_text": "#FFFFFF",
    "reminder_urgent_text": "#FF5252",
}


ACTIVE_THEME = "light"  # обновляется при сборке стилей; используется для затемнения заголовков


def build_stylesheet(theme: str) -> str:
    global ACTIVE_THEME
    ACTIVE_THEME = theme
    c = LIGHT if theme != "dark" else DARK
    return f"""
    MainWindow {{
        background: {c['window_bg']};
        font-family: 'Segoe UI';
    }}
    QDialog {{
        background: {c['window_bg']};
        font-family: 'Segoe UI';
    }}
    QMessageBox {{
        background: {c['window_bg']};
    }}
    QLineEdit {{
        background: {c['input_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 10px;
        padding: 7px 12px;
        font-size: 13px;
        color: {c['text']};
        selection-background-color: {c['accent']};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus {{ border: 2px solid {c['accent']}; }}
    QLineEdit[inlineEdit="true"] {{
        background: {c['input_bg']};
        border: 1px solid {c['accent']};
        border-radius: 4px;
        padding: 0 4px;
        font-size: 13px;
        color: {c['text']};
        selection-background-color: {c['accent']};
        selection-color: #FFFFFF;
    }}
    QSpinBox {{
        background: {c['input_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        padding: 3px 6px;
        font-size: 12px;
        color: {c['text']};
    }}
    QSpinBox:focus {{ border: 2px solid {c['accent']}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: transparent;
        border: none;
        width: 16px;
    }}
    QSpinBox::up-arrow {{
        image: url({_arrow_image_path("up", theme)});
        width: 10px;
        height: 6px;
    }}
    QSpinBox::down-arrow {{
        image: url({_arrow_image_path("down", theme)});
        width: 10px;
        height: 6px;
    }}
    QSpinBox[spinPill="true"] {{
        background: {c['input_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 15px;
        padding: 0 6px;
        font-size: 13px;
        font-weight: 600;
        color: {c['text']};
    }}
    QSpinBox[spinPill="true"]:focus {{ border: 2px solid {c['accent']}; }}
    QComboBox {{
        background: {c['input_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 12px;
        color: {c['text']};
    }}
    QComboBox:hover {{ border-color: {c['card_hover']}; }}
    QComboBox:focus {{ border: 2px solid {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{
        image: url({_arrow_image_path("down", theme)});
        width: 10px;
        height: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: {c['card_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 6px;
        color: {c['text']};
        selection-background-color: {c['accent']};
        selection-color: #FFFFFF;
    }}
    QPushButton {{
        background: {c['card_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        padding: 5px 12px;
        font-size: 12px;
        font-weight: 500;
        color: {c['text']};
    }}
    QPushButton:hover {{ background: {c['hover']}; border-color: {c['card_hover']}; }}
    QPushButton:pressed {{ background: {c['pressed']}; }}
    QPushButton[iconBtn="true"] {{
        background: {c['card_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        padding: 0;
    }}
    QPushButton[iconBtn="true"]:hover {{ background: {c['hover']}; border-color: {c['card_hover']}; }}
    QPushButton[iconBtn="true"]:pressed {{ background: {c['pressed']}; }}
    QPushButton[roundBtn="true"] {{
        background: {c['card_bg']};
        border: 1px solid {c['input_border']};
        border-radius: 15px;
        color: {c['accent']};
        font-size: 18px;
        font-weight: 600;
        padding: 0;
    }}
    QPushButton[roundBtn="true"]:hover {{ background: {c['hover']}; border-color: {c['card_hover']}; }}
    QPushButton[roundBtn="true"]:pressed {{ background: {c['pressed']}; }}
    QPushButton[accent="true"] {{
        background: {c['accent']};
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        padding: 4px 10px;
    }}
    QPushButton[accent="true"]:hover {{ background: {c['accent_hover']}; }}
    QPushButton[accent="true"]:pressed {{ background: {c['accent_pressed']}; }}
    QCheckBox {{ color: {c['text']}; font-size: 12px; spacing: 7px; }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {c['input_border']};
        border-radius: 6px;
        background: {c['input_bg']};
    }}
    QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
    QCheckBox::indicator:checked {{
        background: {c['accent']};
        border-color: {c['accent']};
        image: url({_check_image_path()});
    }}
    QLabel {{ color: {c['muted']}; font-size: 12px; }}
    QLabel#timerLabel {{ color: {c['text']}; font-size: 30px; font-weight: 600; }}
    QScrollArea {{ border: none; background: transparent; }}
    QTextBrowser {{
        background: {c['window_bg']};
        color: {c['text']};
        border: none;
        padding: 0;
    }}
    TaskListWidget {{ background: transparent; }}
    QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['scrollbar']}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['scrollbar_hover']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    TaskWidget[card="true"] {{ background: {c['card_bg']}; border: 1px solid {c['card_border']}; border-radius: 10px; }}
    TaskWidget[card="true"]:hover {{ border-color: {c['card_hover']}; }}
    TaskWidget[card="true"] ElidedLabel {{ background: transparent; color: {c['text']}; font-size: 13px; }}
    QLabel[dragRep="true"] {{
        background: {c['card_bg']};
        border: 1px solid {c['rep_border']};
        border-radius: 6px;
        color: {c['text']};
        padding-left: 6px;
        font-size: 13px;
    }}
    """


def _check_image_path() -> str:
    """Создаёт один раз PNG галочки (белая) и возвращает абсолютный путь для QSS."""
    path = Path(tempfile.gettempdir()) / "todoreminder_check_white.png"
    if not path.exists():
        pix = QPixmap(16, 16)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#FFFFFF"), 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(3, 8), QPointF(7, 12))
        painter.drawLine(QPointF(7, 12), QPointF(13, 4))
        painter.end()
        pix.save(str(path), "PNG")
    return path.as_posix()


def _arrow_image_path(direction: str, theme: str) -> str:
    """Создаёт PNG стрелки в цвете, подходящем теме, и возвращает путь для QSS."""
    color = LIGHT["muted"] if theme != "dark" else DARK["muted"]
    fname = f"todoreminder_arrow_{direction}_{color.lstrip('#')}.png"
    path = Path(tempfile.gettempdir()) / fname
    if not path.exists():
        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if direction == "down":
            painter.drawLine(QPointF(2, 4), QPointF(6, 8))
            painter.drawLine(QPointF(6, 8), QPointF(10, 4))
        else:
            painter.drawLine(QPointF(2, 8), QPointF(6, 4))
            painter.drawLine(QPointF(6, 4), QPointF(10, 8))
        painter.end()
        pix.save(str(path), "PNG")
    return path.as_posix()


# ------------------------------------------------------------------ тёмный заголовок окна (Windows)

def set_dark_titlebar(window, on: bool) -> None:
    """DWMWA_USE_IMMERSIVE_DARK_MODE: тёмная/светлая шапка окна Windows."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
    except Exception:
        return
    try:
        value = ctypes.c_int(1 if on else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        # принудительно перерисовываем рамку, иначе DWM оставляет старое значение
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
        )
    except Exception:
        pass


def apply_titlebars(app, on: bool) -> None:
    """Применяет цвет шапки ко всем уже открытым окнам."""
    for w in app.topLevelWidgets():
        set_dark_titlebar(w, on)


class TitlebarFilter(QObject):
    """Следит за показом окон и красит шапку под текущую тему."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            set_dark_titlebar(obj, ACTIVE_THEME == "dark")
        return False


def theme_icon(current_theme: str) -> QIcon:
    """Луна — перейти в тёмную тему, солнце — в светлую."""
    if current_theme == "dark":
        return _draw_sun()
    return _draw_moon()


def _draw_moon() -> QIcon:
    pix = QPixmap(20, 20)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#E8B34B"))
    painter.drawEllipse(3, 4, 14, 12)
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    painter.drawEllipse(10, 1, 13, 13)
    painter.end()
    return QIcon(pix)


def _draw_sun() -> QIcon:
    pix = QPixmap(20, 20)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#E8B34B"))
    painter.drawEllipse(5, 5, 10, 10)
    painter.setPen(QPen(QColor("#E8B34B"), 2))
    painter.setBrush(Qt.NoBrush)
    for i in range(8):
        ang = math.radians(i * 45)
        x1 = 10.0 + 7.0 * math.cos(ang)
        y1 = 10.0 + 7.0 * math.sin(ang)
        x2 = 10.0 + 10.5 * math.cos(ang)
        y2 = 10.0 + 10.5 * math.sin(ang)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    painter.end()
    return QIcon(pix)


def clear_icon() -> QIcon:
    """Красный крестик для кнопки «Очистка списка дел»."""
    pix = QPixmap(20, 20)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#E5484D"), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(QPointF(5, 5), QPointF(15, 15))
    painter.drawLine(QPointF(15, 5), QPointF(5, 15))
    painter.end()
    return QIcon(pix)