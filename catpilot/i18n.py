"""Changement de langue de l'interface.

Le logiciel est écrit en français. En anglais, les textes sont traduits au
moment où ils s'affichent : les fonctions Qt qui posent un texte (libellés,
boutons, infobulles, menus, messages, barre d'état, dessins…) passent par
tr(). Les listes déroulantes gardent en interne leur texte français, pour que
le reste du code fonctionne à l'identique.
"""
import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QDockWidget, QFileDialog, QInputDialog, QLabel,
    QLineEdit, QMenu, QMenuBar, QMessageBox, QProgressDialog, QStatusBar, QTableWidget, QTabWidget,
    QWidget,
)

LANGS = {"fr": "Français", "en": "English"}
ORIG = Qt.UserRole + 77
_exact, _templates, _cache = {}, [], {}
active = False


def _compile(templates):
    out = []
    for fr, en in templates.items():
        parts = fr.split("{}")
        rx = "^" + "(.*?)".join(re.escape(p) for p in parts) + "$"
        out.append((re.compile(rx, re.S), en, fr.count("{}")))
    out.sort(key=lambda t: -len(t[0].pattern))      # les modèles les plus précis d'abord
    return out


def tr(text):
    """Traduit un texte (ou le renvoie tel quel)."""
    if not active or not isinstance(text, str) or not text:
        return text
    hit = _cache.get(text)
    if hit is not None:
        return hit
    res = _exact.get(text)
    if res is None:
        res = text
        for rx, en, n in _templates:
            m = rx.match(text)
            if m:
                res = en.format(*(tr(g) for g in m.groups()))
                break
        else:
            if "\n\n" in text:                       # message composé : on traduit chaque paragraphe
                res = "\n\n".join(tr(p) for p in text.split("\n\n"))
    if len(_cache) > 20000:
        _cache.clear()
    _cache[text] = res
    return res


def _wrap(cls, name, conv):
    orig = getattr(cls, name)

    def f(self, *a, **k):
        a, k = conv(a, k)
        return orig(self, *a, **k)
    setattr(cls, name, f)


def _first(a, k):
    if a and isinstance(a[0], str):
        a = (tr(a[0]),) + tuple(a[1:])
    return a, k


def _all_str(a, k):
    return tuple(tr(x) if isinstance(x, str) else x for x in a), k


def _wrap_static(cls, name, idx):
    orig = getattr(cls, name)

    def f(*a, **k):
        a = list(a)
        for i in idx:
            if i < len(a) and isinstance(a[i], str):
                a[i] = tr(a[i])
        for key in ("caption", "title", "text", "label", "filter"):
            if isinstance(k.get(key), str):
                k[key] = tr(k[key])
        return orig(*a, **k)
    setattr(cls, name, staticmethod(f))


def _patch_combo():
    """Affiche la traduction mais garde le texte français pour le code."""
    add_item, add_items = QComboBox.addItem, QComboBox.addItems
    item_text, current_text = QComboBox.itemText, QComboBox.currentText
    find_text, set_item_text = QComboBox.findText, QComboBox.setItemText

    def addItem(self, *a, **k):
        if a and isinstance(a[0], str):
            fr = a[0]
            add_item(self, tr(fr), *a[1:], **k)
            self.setItemData(self.count() - 1, fr, ORIG)
        else:
            add_item(self, *a, **k)

    def addItems(self, texts):
        for t in texts:
            addItem(self, t)

    def itemText(self, i):
        o = self.itemData(i, ORIG)
        return o if isinstance(o, str) else item_text(self, i)

    def currentText(self):
        i = self.currentIndex()
        if i >= 0:
            o = self.itemData(i, ORIG)
            if isinstance(o, str) and (not self.isEditable() or current_text(self) == item_text(self, i)):
                return o
        return current_text(self)

    def findText(self, text, *a):
        for i in range(self.count()):
            if self.itemData(i, ORIG) == text:
                return i
        return find_text(self, text, *a)

    def setCurrentText(self, text):
        i = findText(self, text)
        if i >= 0:
            self.setCurrentIndex(i)
        elif self.isEditable():
            self.setEditText(text)

    def setItemText(self, i, text):
        self.setItemData(i, text, ORIG)
        set_item_text(self, i, tr(text))

    QComboBox.addItem, QComboBox.addItems, QComboBox.itemText = addItem, addItems, itemText
    QComboBox.currentText, QComboBox.findText = currentText, findText
    QComboBox.setCurrentText, QComboBox.setItemText = setCurrentText, setItemText


def translate_tree(root):
    """Traduit les textes déjà posés (passés au constructeur) d'une fenêtre."""
    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        if w.property("_tr_done"):
            continue
        w.setProperty("_tr_done", True)
        if w.toolTip():
            w.setToolTip(w.toolTip())
        if w.isWindow() and w.windowTitle():
            w.setWindowTitle(w.windowTitle())
        if isinstance(w, QLabel) and w.text():
            w.setText(w.text())
        elif isinstance(w, QAbstractButton) and w.text():
            w.setText(w.text())
        elif isinstance(w, QLineEdit) and w.placeholderText():
            w.setPlaceholderText(w.placeholderText())
        elif isinstance(w, QDockWidget):
            w.setWindowTitle(w.windowTitle())
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                w.setTabText(i, tr(w.tabText(i)))
        elif isinstance(w, QTableWidget):
            for i in range(w.columnCount()):
                it = w.horizontalHeaderItem(i)
                if it:
                    it.setText(tr(it.text()))
        elif isinstance(w, QMenu):
            w.setTitle(w.title())
            for a in w.actions():
                if a.text():
                    a.setText(a.text())
        elif isinstance(w, QMenuBar):
            for a in w.actions():
                if a.text():
                    a.setText(a.text())


class _Watcher(QObject):
    """Traduit chaque fenêtre ou dialogue à sa première apparition."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow() \
                and not obj.property("_tr_root"):
            obj.setProperty("_tr_root", True)
            translate_tree(obj)
        return False


def install(lang):
    """À appeler avant de créer la fenêtre principale."""
    global active
    if lang != "en":
        return
    from . import i18n_en
    _exact.update(i18n_en.EXACT)
    _templates.extend(_compile(i18n_en.TEMPLATES))
    active = True
    _wrap(QLabel, "setText", _first)
    _wrap(QAbstractButton, "setText", _first)
    _wrap(QWidget, "setToolTip", _first)
    _wrap(QWidget, "setWindowTitle", _first)
    _wrap(QLineEdit, "setPlaceholderText", _first)
    _wrap(QStatusBar, "showMessage", _first)
    _wrap(QAction, "setText", _first)
    _wrap(QAction, "setToolTip", _first)
    _wrap(QMenu, "setTitle", _first)
    _wrap(QMenu, "addMenu", _first)
    _wrap(QMenuBar, "addMenu", _first)
    _wrap(QTabWidget, "addTab", lambda a, k: ((a[0], tr(a[1])) + tuple(a[2:]) if len(a) > 1 and isinstance(a[1], str) else a, k))
    _wrap(QTableWidget, "setHorizontalHeaderLabels", lambda a, k: (([tr(x) for x in a[0]],) + tuple(a[1:]), k))
    _wrap(QMessageBox, "setText", _first)
    _wrap(QMessageBox, "setInformativeText", _first)
    _wrap(QMessageBox, "addButton", _first)
    _wrap(QProgressDialog, "setLabelText", _first)
    _wrap(QDockWidget, "setWindowTitle", _first)
    _wrap(QPainter, "drawText", lambda a, k: (tuple(tr(x) if isinstance(x, str) else x for x in a), k))
    for name in ("information", "warning", "critical", "question", "about"):
        _wrap_static(QMessageBox, name, (1, 2))
    _wrap_static(QInputDialog, "getText", (1, 2))
    for name in ("getSaveFileName", "getOpenFileName"):
        _wrap_static(QFileDialog, name, (1, 3))
    _patch_combo()
    app = QApplication.instance()
    w = _Watcher(app)
    app.installEventFilter(w)
    app._tr_watcher = w
