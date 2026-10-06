"""Brushed-metal theme: palette, generated textures and the workspace stylesheet.

Presentation only. Textures are drawn locally with a fixed seed; nothing is
downloaded and a missing or unwritable asset folder only drops the texture.
"""
from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen, QPolygonF

ASSETS = Path(__file__).resolve().parent / "assets"

# Indicator colours for the black-glass status readout and transcript headings.
STATE_COLORS = {"Connected": "#5fe08a", "Busy": "#ffc857", "Connecting": "#ffc857",
                "Error": "#ff7468", "Blocked": "#ff7468"}
STATE_IDLE = "#aeb7c1"
HEADING_COLOR = "#8ec3ff"
EVENT_COLOR = "#d5dbe1"

CHROME = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f8fa, stop:0.46 #d0d5db, stop:0.52 #b6bcc4, stop:1 #d6dbe0)"
CHROME_HOVER = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:0.46 #e0e5ea, stop:0.52 #c6ccd4, stop:1 #e6eaee)"
CHROME_PRESSED = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8c949d, stop:0.5 #a9b0b8, stop:1 #c3c9cf)"
CHROME_OFF = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #565d65, stop:1 #444a51)"
PLATE = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5a616a, stop:0.03 #4a5058, stop:1 #393e45)"
PLATE_DARK = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4c5259, stop:0.03 #3f444b, stop:1 #2e3238)"
CHASSIS = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2f343a, stop:1 #1b1e22)"
ANODIZED = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #86bdf6, stop:0.46 #3482de, stop:0.52 #1d64bf, stop:1 #2d79d3)"
ANODIZED_HOVER = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #a3cdfa, stop:0.46 #4692ea, stop:0.52 #2a72cd, stop:1 #3d88df)"
HANDLE_V = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7f8790, stop:0.5 #e3e7eb, stop:1 #7f8790)"
HANDLE_H = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7f8790, stop:0.5 #e3e7eb, stop:1 #7f8790)"

STYLE = """
QWidget { color: #eef1f4; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC'; font-size: 13px; }
QMainWindow, QDialog { background-color: @CHASSIS@; background-image: url("@BRUSHED@"); }
QLabel { background: transparent; }
QLabel#brand { font-size: 17px; font-weight: 650; color: #f6f8fa; }
QLabel#subtitle, QLabel#muted { color: #c3cad2; }
QLabel#agentTitle { font-size: 16px; font-weight: 650; color: #f6f8fa; }
QLabel#status { color: #aeb7c1; font-size: 12px; font-weight: 600; background: #0b0d0f; border: 1px solid #050607; border-bottom-color: #6b737d; border-radius: 9px; padding: 2px 9px; }
QFrame#panel { background-color: @PLATE@; background-image: url("@BRUSHED@"); border: 1px solid #121416; border-top-color: #8a939d; border-radius: 8px; }
QFrame#sidebar, QFrame#work_details { background-color: @PLATE_DARK@; background-image: url("@BRUSHED@"); border: 1px solid #121416; border-top-color: #7a838d; border-radius: 8px; }
QFrame#message { border: none; border-bottom: 1px solid #2a2f35; border-radius: 0; background: transparent; }
QFrame#event { border: 1px solid #343a41; border-radius: 6px; background: #181c20; }

QPushButton, QToolButton { color: #12161a; background: @CHROME@; border: 1px solid #0d0f11; border-radius: 5px; padding: 6px 10px; min-height: 19px; }
QPushButton:hover, QToolButton:hover { background: @CHROME_HOVER@; }
QPushButton:pressed, QToolButton:pressed, QPushButton:checked, QToolButton:checked { background: @CHROME_PRESSED@; padding-top: 7px; padding-bottom: 5px; }
QPushButton:focus, QToolButton:focus { border-color: #6ab0ff; }
QPushButton:disabled, QToolButton:disabled { color: #9ba4ae; background: @CHROME_OFF@; border-color: #23262a; }
QPushButton#primary { color: #ffffff; background: @ANODIZED@; border-color: #0a2a55; font-weight: 600; }
QPushButton#primary:hover { background: @ANODIZED_HOVER@; }
QPushButton#stop { color: #a01912; font-weight: 600; }
QPushButton#primary:disabled, QPushButton#stop:disabled { color: #9ba4ae; background: @CHROME_OFF@; border-color: #23262a; font-weight: 400; }
QToolButton::menu-indicator { image: none; }

QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QSpinBox { color: #e9eef3; background: #0f1215; border: 1px solid #050607; border-bottom-color: #6b737d; border-right-color: #4d545c; border-radius: 5px; padding: 6px; selection-background-color: #2f6fb8; selection-color: #ffffff; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: #6ab0ff; }
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled, QSpinBox:disabled { color: #98a1ab; background: #1f2327; }
QComboBox { padding: 5px 28px 5px 8px; }
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 22px; background: @CHROME@; border: 1px solid #0d0f11; border-top-right-radius: 5px; border-bottom-right-radius: 5px; }
QComboBox::drop-down:disabled { background: @CHROME_OFF@; }
QComboBox::down-arrow { image: url("@ARROW_DOWN@"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { color: #e9eef3; background: #171a1e; border: 1px solid #8a939d; outline: 0; selection-background-color: #2f6fb8; selection-color: #ffffff; }
QSpinBox { padding-right: 22px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 20px; background: @CHROME@; border: 1px solid #0d0f11; }
QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 5px; }
QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 5px; }
QSpinBox::up-arrow { image: url("@ARROW_UP@"); width: 10px; height: 6px; }
QSpinBox::down-arrow { image: url("@ARROW_DOWN@"); width: 10px; height: 6px; }
QCheckBox { background: transparent; spacing: 7px; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea[well="true"] { background: #0f1215; border: 1px solid #050607; border-bottom-color: #6b737d; border-right-color: #4d545c; border-radius: 6px; }
QScrollBar:vertical { width: 12px; background: #0b0d0f; border-radius: 6px; margin: 0; }
QScrollBar::handle:vertical { background: @HANDLE_V@; border: 1px solid #0d0f11; border-radius: 5px; min-height: 28px; }
QScrollBar:horizontal { height: 12px; background: #0b0d0f; border-radius: 6px; margin: 0; }
QScrollBar::handle:horizontal { background: @HANDLE_H@; border: 1px solid #0d0f11; border-radius: 5px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { border: none; }
QTabBar { background: transparent; }
QTabBar::tab { color: #c3cad2; background: @PLATE_DARK@; border: 1px solid #121416; border-bottom: none; border-top-left-radius: 5px; border-top-right-radius: 5px; padding: 7px 12px; margin-right: 2px; }
QTabBar::tab:hover { color: #ffffff; }
QTabBar::tab:selected { color: #12161a; background: @CHROME@; font-weight: 600; }
QHeaderView::section { color: #eef1f4; background: @PLATE@; padding: 7px; border: none; border-right: 1px solid #23262a; border-bottom: 1px solid #121416; font-weight: 600; }
QTreeWidget, QTableWidget { color: #e9eef3; background: #0f1215; border: 1px solid #050607; border-bottom-color: #6b737d; alternate-background-color: #171b1f; selection-background-color: #2f6fb8; selection-color: #ffffff; gridline-color: #2a2f35; }
QTreeWidget::item { padding: 5px; }
QTableCornerButton::section { background: #393e45; border: none; }
QSplitter::handle { background: transparent; width: 8px; }

QMenu { color: #12161a; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #eceff2, stop:1 #c9ced4); border: 1px solid #0d0f11; padding: 5px; }
QMenu::item { color: #12161a; background: transparent; padding: 6px 18px; border-radius: 3px; }
QMenu::item:selected { color: #ffffff; background: #2f6fb8; }
QMenu::item:disabled { color: #7b838c; background: transparent; }
QMenu::separator { height: 1px; background: #8d959e; margin: 4px 8px; }
QToolTip { color: #12161a; background: #e6e9ec; border: 1px solid #0d0f11; padding: 3px 5px; }
"""


def metal_palette() -> QPalette:
    """Fallback colours for anything the stylesheet does not reach."""
    palette = QPalette()
    for role, value in ((QPalette.Window, "#2a2e33"), (QPalette.WindowText, "#eef1f4"),
                        (QPalette.Base, "#0f1215"), (QPalette.AlternateBase, "#171b1f"),
                        (QPalette.Text, "#e9eef3"), (QPalette.PlaceholderText, "#8c959f"),
                        (QPalette.Button, "#c9ced4"), (QPalette.ButtonText, "#12161a"),
                        (QPalette.Highlight, "#2f6fb8"), (QPalette.HighlightedText, "#ffffff"),
                        (QPalette.ToolTipBase, "#e6e9ec"), (QPalette.ToolTipText, "#12161a"),
                        (QPalette.Link, "#8ec3ff"), (QPalette.BrightText, "#ffffff")):
        palette.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#98a1ab"))
    return palette


def _brushed(path: Path, size: int = 256) -> None:
    # Tileable horizontal grain: translucent light and dark hairlines.
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    rng = random.Random(7)
    painter = QPainter(image)
    for y in range(size):
        for _ in range(3):
            shade = 255 if rng.random() < 0.5 else 0
            painter.setPen(QPen(QColor(shade, shade, shade, rng.randint(3, 15)), 1))
            start, length = rng.randrange(size), rng.randint(size // 5, size)
            painter.drawLine(start, y, start + length, y)
            painter.drawLine(start - size, y, start + length - size, y)
    painter.end()
    image.save(str(path), "PNG")


def _arrow(path: Path, up: bool) -> None:
    image = QImage(10, 6, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#12161a"))
    points = [(0, 6), (10, 6), (5, 0)] if up else [(0, 0), (10, 0), (5, 6)]
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.end()
    image.save(str(path), "PNG")


def build_style() -> str:
    assets = {"BRUSHED": ("brushed.png", _brushed), "ARROW_DOWN": ("arrow_down.png", lambda p: _arrow(p, False)),
              "ARROW_UP": ("arrow_up.png", lambda p: _arrow(p, True))}
    style = STYLE
    for key, (name, draw) in assets.items():
        path = ASSETS / name
        try:
            if not path.is_file():
                ASSETS.mkdir(parents=True, exist_ok=True)
                draw(path)
        except Exception:
            pass
        style = style.replace("@" + key + "@", path.as_posix() if path.is_file() else "")
    for key, value in (("CHROME_HOVER", CHROME_HOVER), ("CHROME_PRESSED", CHROME_PRESSED), ("CHROME_OFF", CHROME_OFF),
                       ("CHROME", CHROME), ("PLATE_DARK", PLATE_DARK), ("PLATE", PLATE), ("CHASSIS", CHASSIS),
                       ("ANODIZED_HOVER", ANODIZED_HOVER), ("ANODIZED", ANODIZED),
                       ("HANDLE_V", HANDLE_V), ("HANDLE_H", HANDLE_H)):
        style = style.replace("@" + key + "@", value)
    return style
