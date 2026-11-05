"""Adaptation de l'interface à l'écran du PC (résolution, mise à l'échelle)."""
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtWidgets import QApplication

# Choix « Taille du texte » dans les paramètres
TEXT_SIZES = ["Auto", "Petite", "Normale", "Grande", "Très grande"]
_FACTOR = {"Petite": 0.85, "Normale": 1.0, "Grande": 1.15, "Très grande": 1.3}


def available(widget=None):
    """Zone utilisable de l'écran (sans la barre des tâches)."""
    scr = None
    if widget is not None and widget.screen() is not None:
        scr = widget.screen()
    if scr is None:
        scr = QGuiApplication.primaryScreen()
    return scr.availableGeometry() if scr else QRect(0, 0, 1366, 768)


def is_small(widget=None):
    a = available(widget)
    return a.width() < 1400 or a.height() < 850


def scale(widget=None):
    """Facteur < 1 sur les petits écrans (référence : 1400 x 860)."""
    a = available(widget)
    return max(0.7, min(1.0, a.width() / 1400, a.height() / 860))


def fit(widget, w, h, ratio=0.92):
    """Redimensionne une fenêtre à w x h sans dépasser l'écran, et la centre."""
    a = available(widget)
    w = min(w, int(a.width() * ratio)); h = min(h, int(a.height() * ratio))
    widget.resize(w, h)
    widget.move(a.x() + (a.width() - w) // 2, a.y() + (a.height() - h) // 2)


def on_screen(rect):
    """Vrai si le rectangle est visible sur un des écrans actuels."""
    for s in QGuiApplication.screens():
        if s.availableGeometry().intersected(rect).width() > 200:
            return True
    return False


_base_pt = None


def apply_text_size(choice):
    """Taille de la police de l'application : auto selon l'écran, ou choix utilisateur."""
    global _base_pt
    app = QApplication.instance()
    f = QFont(app.font())
    if _base_pt is None:
        _base_pt = f.pointSizeF() if f.pointSizeF() > 0 else 10.0
    k = _FACTOR.get(choice, 1.0)   # « Auto » : taille du système
    f.setPointSizeF(round(_base_pt * k, 1))
    app.setFont(f)


def big_pt():
    """Taille de la grande police de saisie (indicatif, RST)."""
    return max(13, round(20 * scale()))
