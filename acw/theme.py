"""Console theme for the live Monitor workbench, plus legacy theme definitions.

Presentation only. Small images are drawn locally; nothing is downloaded and a missing or
unwritable asset folder only drops the image.
"""
from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen, QPolygonF

SPACE = {'xs': 4, 'sm': 8, 'md': 12, 'lg': 16, 'xl': 24}
RADIUS = 6

ASSETS = Path(__file__).resolve().parent / "assets"

# Indicator colours for the black-glass status readout and transcript headings.
STATE_COLORS = {"Connected": "#86efac", "Busy": "#67e8f9", "Connecting": "#67e8f9",
                "Error": "#fda4af", "Blocked": "#fbbf24"}
STATE_IDLE = "#94a3a0"
HEADING_COLOR = "#bef264"
EVENT_COLOR = "#c9c7c0"
MUTED_COLOR = "#8f8e87"
CODE_BLOCK_BG, CODE_INLINE_BG, CODE_INLINE_FG = "#0a110e", "#24371f", "#d9f99d"

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

METAL_STYLE = """
QWidget { color: #eef1f4; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC'; font-size: 13px; }
QMainWindow, QDialog { background-color: @CHASSIS@; background-image: url("@BRUSHED@"); }
QLabel { background: transparent; }
QLabel#brand { font-size: 17px; font-weight: 650; color: #f6f8fa; }
QLabel#subtitle, QLabel#muted { color: #c3cad2; }
QLabel#agentTitle { font-size: 16px; font-weight: 650; color: #f6f8fa; }
QLabel#status { color: #aeb7c1; font-size: 12px; font-weight: 600; background: #0b0d0f; border: 1px solid #050607; border-bottom-color: #6b737d; border-radius: 9px; padding: 2px 9px; }
QFrame#panel { background-color: @PLATE@; background-image: url("@BRUSHED@"); border: 1px solid #121416; border-top-color: #8a939d; border-radius: 8px; }
QFrame#sidebar, QFrame#work_details { background-color: @PLATE_DARK@; background-image: url("@BRUSHED@"); border: 1px solid #121416; border-top-color: #7a838d; border-radius: 8px; }
QFrame#message { border: none; background: transparent; }
QFrame#message_user { background: #1b2026; border: 1px solid #2c333b; border-radius: 10px; margin-left: 40px; }
QLabel#message_meta { color: #7f8892; font-size: 11px; }
QToolButton#ghost { color: #8c959f; background: transparent; border: none; border-radius: 4px; padding: 1px 6px; min-height: 0; font-size: 12px; }
QToolButton#ghost:hover, QToolButton#ghost:pressed { color: #ffffff; background: #20262d; padding: 1px 6px; }
QFrame#event { border: none; background: transparent; }
QFrame#event_approval { border: 1px solid #6a5a2a; border-radius: 6px; background: #1d1a12; }
QFrame#run_bar { background: #10151b; border: 1px solid #2f6fb8; border-radius: 6px; }
QLabel#run_status { color: #cfe3fb; font-weight: 600; }
QFrame#activity { border: none; border-left: 2px solid #2c333b; background: transparent; }
QFrame#event QPlainTextEdit, QFrame#event_approval QPlainTextEdit { background: #07090b; border: 1px solid #20262d; border-radius: 4px; }

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
QCheckBox::indicator { width: 14px; height: 14px; background: #0f1215; border: 1px solid #8a939d; border-radius: 3px; }
QCheckBox::indicator:checked { background: #3482de; border-color: #cfe3fb; }
QCheckBox::indicator:disabled { border-color: #4d545c; }

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
QTreeWidget#nav_tree { border-radius: 6px; padding: 4px; outline: 0; }
QTreeWidget#nav_tree::item { padding: 6px 4px; border-radius: 4px; }
QTreeWidget#nav_tree::item:hover { background: #1c2126; }
QTreeWidget#nav_tree::item:selected { color: #ffffff; background: #24507f; }
QLabel#nav_status { color: #aeb7c1; font-size: 11px; }

QMenu { color: #12161a; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #eceff2, stop:1 #c9ced4); border: 1px solid #0d0f11; padding: 5px; }
QMenu::item { color: #12161a; background: transparent; padding: 6px 18px; border-radius: 3px; }
QMenu::item:selected { color: #ffffff; background: #2f6fb8; }
QMenu::item:disabled { color: #7b838c; background: transparent; }
QMenu::separator { height: 1px; background: #8d959e; margin: 4px 8px; }
QToolTip { color: #12161a; background: #e6e9ec; border: 1px solid #0d0f11; padding: 3px 5px; }
"""

DESKTOP_STYLE = """
/* Warm neutral desktop surfaces; accent marks selection and primary actions. */
QWidget { color: #d6d5d0; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC'; font-size: 13px; }
QMainWindow, QDialog { background: #262624; }
QLabel { background: transparent; }
QLabel#brand { font-size: 15px; font-weight: 600; color: #ececea; }
QLabel#subtitle, QLabel#muted { color: @MUTED@; }
QLabel#agentTitle, QLabel#sidebar_agent_title { font-size: 15px; font-weight: 600; color: #ececea; }
QLabel#status { color: @MUTED@; font-size: 12px; background: transparent; border: none; padding: 0 4px; }
QFrame#panel { background: #262624; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QFrame#sidebar { background: #1f1e1d; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QFrame#work_details { background: #1f1e1d; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QFrame#composer { background: #30302e; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QFrame#composer QPlainTextEdit { background: transparent; border: none; padding: 2px; font-size: 14px; }
QFrame#composer QComboBox { background: transparent; border: none; color: @MUTED@; padding: 3px 22px 3px 6px; }
QFrame#composer QComboBox:hover { color: #ececea; background: #3a3a3a; }
QFrame#message { border: none; background: transparent; }
QFrame#message_user { background: #1a1a19; border: none; border-radius: @RADIUS@px; margin-left: 40px; }
QLabel#message_meta { color: @MUTED@; font-size: 11px; }
QToolButton#ghost { color: #8f8e87; background: transparent; border: none; border-radius: @RADIUS@px; padding: 2px 7px; min-height: 0; font-size: 12px; }
QToolButton#ghost:hover, QToolButton#ghost:pressed { color: #ececea; background: #3a3a3a; padding: 2px 7px; }
QFrame#event { border: none; background: transparent; }
QFrame#event_approval { border: 1px solid #3a3a3a; border-radius: @RADIUS@px; background: #2b2820; }
QFrame#run_bar { background: #30302e; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QLabel#run_status { color: @MUTED@; font-weight: 600; }
QFrame#activity { border: none; border-left: 2px solid #3a3a3a; background: transparent; }
QFrame#event QPlainTextEdit, QFrame#event_approval QPlainTextEdit { background: #1a1a19; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }

QPushButton, QToolButton { color: #ececea; background: transparent; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; padding: 5px 10px; min-height: 19px; }
QPushButton:hover, QToolButton:hover { background: #30302e; border-color: #4a4944; }
QPushButton:pressed, QToolButton:pressed, QPushButton:checked, QToolButton:checked { background: #3a3a3a; }
QPushButton:focus, QToolButton:focus { border-color: #d97757; }
QPushButton:disabled, QToolButton:disabled { color: @MUTED@; background: transparent; border-color: #3a3a3a; }
QPushButton#primary, QPushButton[primary="true"] { color: #ffffff; background: #d97757; border-color: #d97757; font-weight: 600; }
QPushButton#primary:hover, QPushButton[primary="true"]:hover { background: #c4663f; border-color: #c4663f; }
QPushButton#primary:pressed, QPushButton[primary="true"]:pressed { background: #b05a37; border-color: #b05a37; }
QPushButton#primary:focus, QPushButton[primary="true"]:focus { border-color: #d97757; }
QPushButton#stop { color: @MUTED@; }
QPushButton#primary:disabled, QPushButton[primary="true"]:disabled { color: #8f8e87; background: #3a3a3a; border-color: #3a3a3a; font-weight: 400; }
QPushButton#stop:disabled { color: @MUTED@; }
QToolButton::menu-indicator { image: none; }

QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QSpinBox { color: #ececea; background: #30302e; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; padding: 6px; selection-background-color: #5a4a42; selection-color: #ececea; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: @MUTED@; }
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled, QSpinBox:disabled { color: @MUTED@; background: #2b2b29; }
QComboBox { padding: 5px 24px 5px 8px; }
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 20px; background: transparent; border: none; }
QComboBox::down-arrow { image: url("@ARROW_DOWN_LIGHT@"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { color: #ececea; background: #30302e; border: 1px solid #3a3a3a; outline: 0; selection-background-color: #3a3a3a; selection-color: #ececea; }
QSpinBox { padding-right: 22px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 20px; background: transparent; border: none; }
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow { image: url("@ARROW_UP_LIGHT@"); width: 10px; height: 6px; }
QSpinBox::down-arrow { image: url("@ARROW_DOWN_LIGHT@"); width: 10px; height: 6px; }
QCheckBox { background: transparent; spacing: 7px; }
QCheckBox::indicator { width: 14px; height: 14px; background: #30302e; border: 1px solid #4a4944; border-radius: @RADIUS@px; }
QCheckBox::indicator:checked { background: @MUTED@; border-color: #3a3a3a; }
QCheckBox::indicator:disabled { border-color: #3a3a3a; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea[well="true"] { background: transparent; border: none; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: #4a4946; border-radius: @RADIUS@px; min-height: 28px; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0; }
QScrollBar::handle:horizontal { background: #4a4946; border-radius: @RADIUS@px; min-width: 28px; }
QScrollBar::handle:hover { background: #5f5e59; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { border: none; }
QTabBar { background: transparent; }
QTabBar::tab { color: @MUTED@; background: transparent; border: none; border-radius: @RADIUS@px; padding: 6px 11px; margin-right: 2px; }
QTabBar::tab:hover { color: #ececea; background: #30302e; }
QTabBar::tab:selected { color: #ececea; background: transparent; border-bottom: 2px solid #d97757; border-radius: 0; font-weight: 600; }
QHeaderView::section { color: @MUTED@; background: #262624; padding: 7px; border: none; border-bottom: 1px solid #3a3a3a; font-weight: 600; }
QTreeWidget, QTableWidget { color: #ececea; background: #262624; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; alternate-background-color: #2b2b29; selection-background-color: #3a3a3a; selection-color: #ececea; gridline-color: #3a3a3a; }
QTreeWidget::item { padding: 5px; }
QTableCornerButton::section { background: #262624; border: none; }
QSplitter::handle { background: transparent; width: 8px; }
QTreeWidget#nav_tree { background: transparent; border: none; padding: 0; outline: 0; }
QTreeWidget#nav_tree::item { padding: 6px 6px; border-radius: @RADIUS@px; }
QTreeWidget#nav_tree::item:hover { background: #2b2b29; }
QTreeWidget#nav_tree::item:selected { color: #ececea; background: #141413; }
QLabel#nav_status { color: @MUTED@; font-size: 11px; }
QFrame#sidebar QLineEdit { background: #262624; border-color: #3a3a3a; }

QMenu { color: #ececea; background: #30302e; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; padding: 5px; }
QMenu::item { color: #ececea; background: transparent; padding: 6px 18px; border-radius: @RADIUS@px; }
QMenu::item:selected { background: #3a3a3a; }
QMenu::item:disabled { color: @MUTED@; background: transparent; }
QMenu::separator { height: 1px; background: #3a3a3a; margin: 4px 8px; }
QToolTip { color: #ececea; background: #1a1a19; border: 1px solid #3a3a3a; padding: 3px 5px; }

QLabel#console_mark, QLabel#console_section { color: @MUTED@; font-size: 11px; }
QLabel#console_section { font-size: 12px; font-weight: 600; }
QWidget#agent_rail_body { background: #1f1e1d; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QFrame#teammate { background: #262624; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
QFrame#teammate[selected="true"] { border-left: 3px solid #d97757; }
QPushButton#teammate_open { text-align: left; color: #ececea; border: none; background: transparent; padding: 0; font-weight: 600; }
QPushButton#teammate_open:hover { background: #30302e; }
QToolButton[workspace_view="true"] { color: @MUTED@; background: transparent; border: none; border-radius: 0; padding: 6px 11px; }
QToolButton[workspace_view="true"]:checked { color: #ececea; border-bottom: 2px solid #d97757; font-weight: 600; }
QToolButton[workspace_view="true"]:focus { border: 1px solid #d97757; }
QTabBar QToolButton { padding: 0; min-width: 22px; max-width: 22px; min-height: 20px; }
"""


HACKER_STYLE = """
QWidget { color: #dce8e1; font-family: 'Segoe UI', 'Microsoft JhengHei UI'; font-size: 13px; }
QMainWindow, QDialog { background: #080d0c; }
QLabel { background: transparent; }
QLabel#console_mark, QLabel#console_section { color: #a3e635; font-family: 'Consolas', 'Microsoft JhengHei UI'; font-weight: 600; font-size: 12px; }
QLabel#brand { color: #adbbb4; font-size: 13px; }
QLabel#empty_conversation { color: #8ca28d; font-size: 15px; padding: 28px 10px; }
QLabel#subtitle, QLabel#muted, QLabel[kind="muted"] { color: #95aaa0; }
QLabel#agentTitle { color: #e9f2ec; font-size: 19px; font-weight: 600; }
QLabel#status { font-family: 'Consolas', 'Microsoft JhengHei UI'; font-size: 12px; }
QFrame#panel { background: #0d1512; border: 1px solid #2b4036; border-radius: 5px; }
QFrame#sidebar { background: #101a15; border: 1px solid #263b30; border-radius: 5px; }
QFrame#work_details { background: #101a15; border: 1px solid #30483a; border-radius: 5px; }
QFrame#composer { background: #142019; border: 1px solid #46634e; border-radius: 5px; }
QFrame#composer QPlainTextEdit { background: transparent; border: none; padding: 3px; font-size: 14px; }
QFrame#composer QComboBox { background: transparent; border: none; padding: 4px 22px 4px 6px; }
QFrame#message { background: transparent; border: none; }
QFrame#message_user { background: #1b2a1c; border: 1px solid #334b33; border-radius: 5px; margin-left: 24px; }
QLabel#message_meta { color: #9caf9d; font-size: 11px; font-family: 'Consolas', 'Microsoft JhengHei UI'; }
QFrame#event { border: none; background: transparent; }
QFrame#event_approval { background: #261f0e; border: 1px solid #aa802d; border-radius: 5px; }
QFrame#activity { background: transparent; border: none; border-left: 2px solid #395346; }
QFrame#run_bar { background: #132319; border: 1px solid #6b9439; border-radius: 4px; }
QLabel#run_status { color: #d9f99d; font-weight: 600; }
QPushButton, QToolButton { color: #dce8e1; background: #142019; border: 1px solid #3c5848; border-radius: 4px; padding: 6px 11px; min-height: 20px; }
QPushButton:hover, QToolButton:hover { color: #e8fccd; background: #253722; border-color: #8dbd48; }
QPushButton:pressed, QPushButton:checked, QToolButton:pressed, QToolButton:checked { color: #e8fccd; background: #2b4226; border-color: #a3e635; }
QPushButton:focus, QToolButton:focus { border-color: #a3e635; }
QPushButton:disabled, QToolButton:disabled { color: #708779; background: #111b16; border-color: #293b30; }
QPushButton#primary, QPushButton#add_agent { color: #101a0b; background: #a3e635; border-color: #a3e635; font-weight: 600; }
QPushButton#primary:hover, QPushButton#add_agent:hover { background: #c2f56c; }
QPushButton#primary:disabled { color: #8fa486; background: #283b23; border-color: #3d5534; }
QPushButton#stop { color: #fda4af; border-color: #68434a; }
QToolButton::menu-indicator { image: none; }
QToolButton#ghost { color: #96ada1; background: transparent; border: none; padding: 2px 7px; min-height: 0; }
QToolButton#ghost:hover { color: #d9f99d; background: #223025; }
QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QSpinBox { color: #dce8e1; background: #0b120f; border: 1px solid #35503e; border-radius: 4px; padding: 6px; selection-background-color: #3f5926; selection-color: #f0f7e8; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus { border-color: #a3e635; }
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled, QSpinBox:disabled { color: #829587; background: #101a14; border-color: #293b30; }
QComboBox { padding: 5px 24px 5px 8px; }
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 20px; background: transparent; border: none; }
QComboBox::down-arrow { image: url("@ARROW_DOWN_LIGHT@"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { color: #e1eddf; background: #142019; selection-background-color: #324c29; selection-color: #effadf; outline: 0; }
QSpinBox { padding-right: 22px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 20px; background: transparent; border: none; }
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow { image: url("@ARROW_UP_LIGHT@"); width: 10px; height: 6px; }
QSpinBox::down-arrow { image: url("@ARROW_DOWN_LIGHT@"); width: 10px; height: 6px; }
QCheckBox { background: transparent; spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #688360; background: #101a14; border-radius: 3px; }
QCheckBox::indicator:checked { background: #a3e635; border-color: #d9f99d; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #486153; border-radius: 3px; min-height: 28px; }
QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar::handle:horizontal { background: #486153; border-radius: 3px; min-width: 28px; }
QScrollBar::handle:hover { background: #88a373; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QTabWidget::pane { border: none; }
QTabBar { background: transparent; }
QTabBar::tab { color: #91a99b; background: #101a14; border: 1px solid #293e30; border-radius: 3px; padding: 7px 11px; margin-right: 3px; }
QTabBar::tab:hover { color: #d9f99d; border-color: #729747; }
QTabBar::tab:selected { color: #d9f99d; background: #22371f; border-color: #82b445; font-weight: 600; }
QTreeWidget, QTableWidget { color: #dce8e1; background: #0d1512; border: 1px solid #2b4036; border-radius: 4px; alternate-background-color: #142019; selection-background-color: #2c4425; gridline-color: #2b4036; }
QTreeWidget::item { padding: 6px; }
QTreeWidget#nav_tree { background: transparent; border: none; outline: 0; }
QTreeWidget#nav_tree::item:selected { color: #d9f99d; background: #263c21; }
QHeaderView::section { color: #a8bbaa; background: #142019; padding: 7px; border: none; border-bottom: 1px solid #35503e; }
QTableCornerButton::section { background: #142019; border: none; }
QSplitter::handle { background: transparent; width: 8px; }
QMenu { color: #dce8e1; background: #142019; border: 1px solid #507047; padding: 5px; }
QMenu::item { padding: 7px 18px; border-radius: 3px; }
QMenu::item:selected { color: #d9f99d; background: #2b4226; }
QMenu::item:disabled { color: #758879; }
QMenu::separator { height: 1px; background: #35503e; margin: 4px 8px; }
QToolTip { color: #e1eddf; background: #142019; border: 1px solid #66824f; padding: 5px; }
QWidget#agent_rail_body { background: #101a15; border: 1px solid #2b4036; border-radius: 5px; }
QFrame#teammate { background: #132017; border: 1px solid #324738; border-radius: 4px; }
QFrame#teammate[selected="true"] { background: #20301a; border-left: 3px solid #a3e635; }
QTabBar QToolButton { padding: 0; min-width: 22px; max-width: 22px; min-height: 20px; }
QPushButton#teammate_open { text-align: left; background: transparent; color: #e4eddf; border: none; padding: 0; font-weight: 600; }
QPushButton#teammate_open:focus { border: 1px solid #a3e635; }
QPushButton#teammate_open:hover { color: #bef264; }
"""


def desktop_state_color(state, pending=False):
    """Reserve semantic colors for approvals and failures in the desktop theme."""
    if pending:
        return '#e3b341'
    if state in ('Error', 'Interrupted', 'Blocked'):
        return '#f27d6b'
    return MUTED_COLOR


def console_palette() -> QPalette:
    palette = metal_palette()
    for role, value in ((QPalette.Window, '#080d0c'), (QPalette.WindowText, '#dce8e1'),
                        (QPalette.Base, '#0d1512'), (QPalette.AlternateBase, '#142019'),
                        (QPalette.Text, '#dce8e1'), (QPalette.PlaceholderText, '#8fa395'),
                        (QPalette.Button, '#142019'), (QPalette.ButtonText, '#dce8e1'),
                        (QPalette.Highlight, '#3f5926'), (QPalette.HighlightedText, '#f0f7e8'),
                        (QPalette.ToolTipBase, '#142019'), (QPalette.ToolTipText, '#dce8e1'),
                        (QPalette.Link, '#a3e635')):
        palette.setColor(role, QColor(value))
    return palette

def metal_palette() -> QPalette:
    """Fallback colours for anything the stylesheet does not reach."""
    palette = QPalette()
    for role, value in ((QPalette.Window, "#262624"), (QPalette.WindowText, "#ececea"),
                        (QPalette.Base, "#30302e"), (QPalette.AlternateBase, "#2b2b29"),
                        (QPalette.Text, "#ececea"), (QPalette.PlaceholderText, "#7c7b75"),
                        (QPalette.Button, "#30302e"), (QPalette.ButtonText, "#ececea"),
                        (QPalette.Highlight, "#5a4a42"), (QPalette.HighlightedText, "#ffffff"),
                        (QPalette.ToolTipBase, "#1a1a19"), (QPalette.ToolTipText, "#ececea"),
                        (QPalette.Link, "#8fb4e8"), (QPalette.BrightText, "#ffffff")):
        palette.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#7c7b75"))
    return palette


def desktop_palette() -> QPalette:
    palette = metal_palette()
    for role, value in ((QPalette.WindowText, '#d6d5d0'), (QPalette.Text, '#d6d5d0'),
                        (QPalette.PlaceholderText, MUTED_COLOR), (QPalette.Link, '#d6d5d0'),
                        (QPalette.Highlight, '#3a3a3a')):
        palette.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(MUTED_COLOR))
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


def _arrow(path: Path, up: bool, color: str = "#12161a") -> None:
    image = QImage(10, 6, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    points = [(0, 6), (10, 6), (5, 0)] if up else [(0, 0), (10, 0), (5, 6)]
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.end()
    image.save(str(path), "PNG")


def build_style(theme: str = "desktop") -> str:
    assets = {"BRUSHED": ("brushed.png", _brushed), "ARROW_DOWN": ("arrow_down.png", lambda p: _arrow(p, False)),
              "ARROW_UP": ("arrow_up.png", lambda p: _arrow(p, True)),
              "ARROW_DOWN_LIGHT": ("arrow_down_light.png", lambda p: _arrow(p, False, "#a3a29b")),
              "ARROW_UP_LIGHT": ("arrow_up_light.png", lambda p: _arrow(p, True, "#a3a29b"))}
    style = METAL_STYLE if theme == "metal" else DESKTOP_STYLE if theme == "desktop" else HACKER_STYLE
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
    return style.replace("@RADIUS@", str(RADIUS)).replace("@MUTED@", MUTED_COLOR)
