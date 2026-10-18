"""Thèmes d'affichage (bleu nuit, noir classique, nuit rouge) et taille du texte."""
import os
import sys

THEMES = {
    "jour": {
        "bg": "#050505", "panel": "#000", "border": "#5a5a5a", "text": "#e6e6e6",
        "amber": "#f2b705", "green": "#8cff3a", "red": "#e5463b", "hint": "#8a8a8a",
        "btn1": "#4a4a4a", "btn2": "#262626", "btn_hover": "#555", "btn_border": "#1a1a1a",
        "checked_border": "#f0f0f0", "checked_bg": "#2a2a2a", "disabled": "#555",
        "disabled_bg": "#181818", "field": "#111", "groove": "#888", "handle": "#1f8f2a",
        "handle_border": "#0b4d12", "header_bg": "#e8e8e8", "header_fg": "#000",
        "freq_border": "#d0d0d0", "arc_ok": "#2fbf3a", "needle": "#ff4d2e", "status": "#bdbdbd",
        "toolbar": "#0b0b0b",
    },
    # Face avant bleu nuit : boutons lumineux, afficheur vert, bandeau de montagnes.
    "bleu": {
        "bg": "#041029", "panel": "#06173a", "border": "#1f55a8", "text": "#e8f0ff",
        "amber": "#ffc928", "green": "#3cff5c", "red": "#ff5a4a", "hint": "#7f9cc8",
        "btn1": "#14386e", "btn2": "#0a2149", "btn_hover": "#1d4b8f", "btn_border": "#2c66be",
        "checked_border": "#8cc4ff", "checked_bg": "#1f6fe6", "disabled": "#4d6488",
        "disabled_bg": "#08193a", "field": "#03102a", "groove": "#2d5ea8", "handle": "#2f86ff",
        "handle_border": "#a9d0ff", "header_bg": "#12346a", "header_fg": "#ffffff",
        "freq_border": "#2f6fd0", "arc_ok": "#2fd13c", "needle": "#ff3b2e", "status": "#9fbbe6",
        "toolbar": "#06173a", "meter_bg": "#000000", "checked_fg": "#ffffff",
        "checked_bg2": "#1250b8", "panel2": "#041431", "radius": 6, "banner": True,
    },
    # Tout en rouge sombre : n'éblouit pas et préserve la vision de nuit en portable.
    "nuit": {
        "bg": "#000", "panel": "#000", "border": "#3a0d08", "text": "#b8321f",
        "amber": "#c8401f", "green": "#ff3b22", "red": "#ff6a4a", "hint": "#6e1c12",
        "btn1": "#240806", "btn2": "#120302", "btn_hover": "#33100a", "btn_border": "#3a0d08",
        "checked_border": "#ff3b22", "checked_bg": "#1c0503", "disabled": "#4a120a",
        "disabled_bg": "#080101", "field": "#0a0201", "groove": "#5a1a10", "handle": "#8a1c10",
        "handle_border": "#3a0a05", "header_bg": "#2a0805", "header_fg": "#ff5a3a",
        "freq_border": "#5a1408", "arc_ok": "#7a1c10", "needle": "#ff3020", "status": "#8a2414",
        "toolbar": "#050000",
    },
}


THEME_NAMES = {"bleu": "Bleu nuit", "jour": "Noir classique"}


def asset(name):
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, "assets", name).replace("\\", "/")


def make_style(name="jour", scale=1.0):
    c = THEMES.get(name, THEMES["jour"])
    f = lambda pt: f"{pt * scale:.1f}pt"
    return _base_style(c, f) + (_blue_extra(c, f) if c.get("banner") else "")


def _blue_extra(c, f):
    r = c["radius"]
    banner = asset("banner.png")
    return f"""
QLabel, QCheckBox, QRadioButton, QSlider {{ background: transparent; }}
QFrame#panel {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['panel']}, stop:1 {c['panel2']});
    border: 1px solid {c['border']}; border-radius: {r + 2}px; }}
QPushButton {{ border-radius: {r}px; padding: 5px 10px; font-weight: 600; }}
QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2457a4, stop:1 #123366);
    border-color: #5d97e6; }}
QPushButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['checked_bg']}, stop:1 {c['checked_bg2']});
    border: 1px solid {c['checked_border']}; color: {c['checked_fg']}; }}
QPushButton#bigkey {{ min-height: 30px; font-size: {f(10)}; }}
QLabel#freq {{ background: #000; border: 2px solid {c['freq_border']}; border-radius: {r + 2}px; font-weight: bold; }}
QLabel#vfob {{ background: #000; border: 2px solid {c['freq_border']}; border-radius: {r}px; font-weight: bold; }}
QLabel#cfreq {{ background: #000; border: 2px solid {c['freq_border']}; border-radius: {r}px; font-weight: bold; }}
QLabel#ptitle {{ color: {c['amber']}; font-size: {f(10.5)}; }}
QToolBar QLabel#info {{ background: #020a1c; border: 1px solid {c['border']}; border-radius: {r}px; padding: 2px 8px; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ border-radius: {r}px;
    border: 1px solid {c['btn_border']}; padding: 3px 6px; }}
QComboBox:hover, QLineEdit:focus, QSpinBox:focus {{ border-color: #6fa8ff; }}
QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {c['groove']}; }}
QSlider::groove:vertical {{ width: 4px; border-radius: 2px; background: {c['groove']}; }}
QSlider::sub-page:horizontal {{ background: {c['handle']}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {c['handle']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6fb0ff, stop:1 {c['handle']});
    border: 1px solid {c['handle_border']}; width: 13px; margin: -7px 0; border-radius: 3px; }}
QSlider::handle:vertical {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6fb0ff, stop:1 {c['handle']});
    border: 1px solid {c['handle_border']}; height: 13px; margin: 0 -7px; border-radius: 3px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px; border: 1px solid {c['btn_border']}; }}
QCheckBox::indicator:checked {{ background: {c['green']}; border-color: #9dffad; }}
QRadioButton::indicator:checked {{ background: {c['green']}; border-radius: 6px; }}
QMenuBar {{ border-image: url("{banner}") 0 0 0 0 stretch stretch; color: #ffffff; font-size: {f(10.5)};
    padding: 6px 4px; min-height: 26px; }}
QMenuBar::item {{ background: transparent; padding: 5px 12px; border-radius: {r}px; }}
QMenuBar::item:selected {{ background: rgba(47, 134, 255, 140); }}
QToolBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0a2350, stop:1 #061633);
    border-bottom: 1px solid {c['border']}; }}
QTabBar::tab {{ border-top-left-radius: {r}px; border-top-right-radius: {r}px; padding: 5px 12px; }}
QTabBar::tab:selected {{ background: {c['btn1']}; color: #fff; border-bottom: 2px solid {c['handle']}; }}
QHeaderView::section {{ font-weight: bold; }}
QTableWidget, QListWidget, QTreeWidget {{ border: 1px solid {c['border']}; border-radius: {r}px; }}
QProgressBar {{ border-radius: 3px; }}
QProgressBar::chunk {{ background: {c['handle']}; border-radius: 3px; }}
QDockWidget::title {{ background: {c['btn1']}; padding: 4px; }}
"""


def _base_style(c, f):
    return f"""
QMainWindow, QWidget {{ background: {c['bg']}; color: {c['text']};
    font-family: "Segoe UI", sans-serif; font-size: {f(9)}; }}
QFrame#panel {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 3px; }}
QLabel#ptitle {{ color: {c['amber']}; font-weight: bold; font-size: {f(9.5)}; }}
QLabel#freq {{ color: {c['green']}; background: {c['panel']}; border: 2px solid {c['freq_border']}; border-radius: 3px;
    font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: {f(38)}; padding: 0 14px; }}
QLabel#vfob {{ color: {c['green']}; background: {c['panel']}; border: 2px solid {c['freq_border']}; border-radius: 3px;
    font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: {f(15)}; padding: 1px 10px; }}
QLabel#cfreq {{ color: {c['green']}; background: {c['panel']}; border: 1px solid {c['freq_border']}; border-radius: 3px;
    font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: {f(22)}; padding: 0 8px; }}
QLabel#info {{ color: {c['amber']}; font-weight: bold; }}
QLabel#value {{ color: {c['amber']}; }}
QLabel#hint {{ color: {c['hint']}; }}
QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['btn1']}, stop:1 {c['btn2']});
    border: 1px solid {c['btn_border']}; border-radius: 3px; padding: 4px 8px; min-height: 18px; color: {c['text']}; }}
QPushButton:hover {{ background: {c['btn_hover']}; }}
QPushButton:checked {{ border: 2px solid {c['checked_border']}; color: {c['green']}; background: {c['checked_bg']}; }}
QPushButton:disabled {{ color: {c['disabled']}; background: {c['disabled_bg']}; }}
QPushButton#ptt {{ font-size: {f(13)}; font-weight: bold; min-height: 34px; }}
QPushButton#ptt:checked {{ background: #a01d15; border-color: #ff6a5e; color: #fff; }}
QSlider::groove:horizontal {{ height: 3px; background: {c['groove']}; }}
QSlider::groove:vertical {{ width: 3px; background: {c['groove']}; }}
QSlider::handle:horizontal {{ background: {c['handle']}; border: 1px solid {c['handle_border']}; width: 11px; margin: -8px 0; border-radius: 3px; }}
QSlider::handle:vertical {{ background: {c['handle']}; border: 1px solid {c['handle_border']}; height: 11px; margin: 0 -8px; border-radius: 3px; }}
QSlider::handle:disabled {{ background: {c['disabled_bg']}; border-color: {c['disabled']}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['field']};
    border: 1px solid {c['border']}; border-radius: 3px; padding: 2px 6px; }}
QComboBox QAbstractItemView {{ background: {c['field']}; selection-background-color: {c['btn_hover']}; }}
QProgressBar {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 2px; }}
QProgressBar::chunk {{ background: {c['amber']}; }}
QTableWidget, QListWidget, QTreeWidget {{ background: {c['panel']}; gridline-color: {c['border']}; color: {c['amber']};
    selection-background-color: {c['btn_hover']}; }}
QHeaderView::section {{ background: {c['header_bg']}; color: {c['header_fg']}; border: 1px solid {c['border']}; padding: 2px; }}
QDockWidget {{ color: {c['amber']}; font-weight: bold; }}
QTabBar::tab {{ background: {c['btn2']}; color: {c['text']}; padding: 4px 10px; border: 1px solid {c['border']}; }}
QTabBar::tab:selected {{ color: {c['green']}; border-bottom: 2px solid {c['green']}; }}
QStatusBar {{ color: {c['status']}; }}
QToolBar {{ background: {c['toolbar']}; border-bottom: 1px solid {c['border']}; spacing: 6px; padding: 3px; }}
QMenuBar {{ background: {c['toolbar']}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {c['btn_hover']}; }}
QMenu {{ background: {c['field']}; border: 1px solid {c['border']}; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {c['groove']}; background: {c['field']}; }}
QCheckBox::indicator:checked {{ background: {c['green']}; }}
"""
