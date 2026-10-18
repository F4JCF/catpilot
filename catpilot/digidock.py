"""Panneau « Numérique » : FT8 / FT4, RTTY / PSK31 (clavier à clavier) et SSTV.

La réception utilise l'audio USB du poste (comme la chute d'eau) ; l'émission passe le poste
en DATA-U et joue le signal sur sa sortie audio USB.
"""
import json
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from . import modems
from .digitx import DigiTx
from .voicekeyer import guess_radio_output, list_devices

DEFAULT_MACROS = [
    ("CQ", "CQ CQ CQ de {MYCALL} {MYCALL} {MYCALL}\nCQ CQ CQ de {MYCALL} {MYCALL} {MYCALL} pse k\n"),
    ("Réponse", "{CALL} {CALL} de {MYCALL} {MYCALL} {MYCALL} k\n"),
    ("Report", "{CALL} de {MYCALL}\nTnx for the call. Your RST is 599 599.\nMy QTH is {QTH}, locator {LOC}.\n"
               "Name is {NAME}.\nHow copy? {CALL} de {MYCALL} k\n"),
    ("Station", "{CALL} de {MYCALL}\nRig: Yaesu FT-991A, logiciel CAT Pilot.\n{CALL} de {MYCALL} k\n"),
    ("73", "{CALL} de {MYCALL}\nTnx for the QSO, 73 and good DX!\n{CALL} de {MYCALL} sk\n"),
    ("Merci", "{CALL} de {MYCALL} tnx 73 sk\n"),
]
CALL_RX = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}\d[A-Z]{1,4}(/[A-Z0-9]{1,4})?$")


class RxText(QPlainTextEdit):
    word = Signal(str)

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)
        w = self.textCursor().selectedText().strip().upper()
        if w:
            self.word.emit(w)


class KeyboardTab(QWidget):
    """RTTY et PSK31 : texte reçu, texte à émettre, messages programmables."""

    def __init__(self, dock):
        super().__init__()
        self.dock, self.win = dock, dock.win
        s = self.win.settings
        self.psk = modems.Psk31Rx()
        self.rtty = modems.RttyRx()
        self.freq = float(s.value("kb_freq", 1000))
        self.psk.set_freq(self.freq)
        self.rtty.set_freq(self.freq)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        h = QHBoxLayout()
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["PSK31", "RTTY 45 (170 Hz)"])
        self.cb_mode.setCurrentIndex(int(s.value("kb_mode", 0)))
        self.cb_mode.currentIndexChanged.connect(self._mode_changed)
        h.addWidget(self.cb_mode)
        self.lb_f = QLabel("")
        self.lb_f.setObjectName("value")
        self.lb_f.setToolTip("Fréquence audio du signal décodé. Clic dans la chute d'eau pour la choisir.")
        h.addWidget(self.lb_f)
        self.ck_afc = QCheckBox("AFC")
        self.ck_afc.setChecked(True)
        self.ck_afc.setToolTip("Suit automatiquement une petite dérive du signal (PSK31)")
        self.ck_afc.toggled.connect(lambda on: setattr(self.psk, "afc", on))
        h.addWidget(self.ck_afc)
        self.ck_rev = QCheckBox("Inverser")
        self.ck_rev.setToolTip("RTTY : échange les tonalités mark et space")
        self.ck_rev.toggled.connect(lambda on: setattr(self.rtty, "reverse", on))
        h.addWidget(self.ck_rev)
        h.addWidget(QLabel("Squelch"))
        self.sl_sq = QSlider(Qt.Horizontal)
        self.sl_sq.setRange(0, 90)
        self.sl_sq.setValue(int(s.value("kb_squelch", 30)))
        self.sl_sq.setMaximumWidth(110)
        self.sl_sq.setToolTip("Qualité minimale du signal pour afficher le texte")
        self.sl_sq.valueChanged.connect(self._squelch)
        h.addWidget(self.sl_sq)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(10)
        self.bar.setMaximumWidth(90)
        self.bar.setToolTip("Qualité du signal reçu")
        h.addWidget(self.bar)
        h.addStretch()
        b = QPushButton("Effacer")
        b.clicked.connect(lambda: self.rx.clear())
        h.addWidget(b)
        v.addLayout(h)
        self.rx = RxText()
        self.rx.setReadOnly(True)
        self.rx.setMaximumBlockCount(2000)
        self.rx.setPlaceholderText("Texte reçu. Clic dans la chute d'eau sur un signal pour le décoder. "
                                   "Double-clic sur un indicatif : il passe dans Corresp. et dans le carnet.")
        self.rx.word.connect(self.use_word)
        v.addWidget(self.rx, 1)
        g = QGridLayout()
        g.addWidget(QLabel("Corresp."), 0, 0)
        self.ed_call = QLineEdit()
        self.ed_call.setMaximumWidth(120)
        g.addWidget(self.ed_call, 0, 1)
        g.addWidget(QLabel("Prénom"), 0, 2)
        self.ed_name = QLineEdit(s.value("kb_name", ""))
        self.ed_name.setMaximumWidth(110)
        self.ed_name.setPlaceholderText("{NAME}")
        g.addWidget(self.ed_name, 0, 3)
        g.addWidget(QLabel("QTH"), 0, 4)
        self.ed_qth = QLineEdit(s.value("kb_qth", ""))
        self.ed_qth.setPlaceholderText("{QTH}")
        g.addWidget(self.ed_qth, 0, 5)
        v.addLayout(g)
        self.tx_text = QPlainTextEdit()
        self.tx_text.setMaximumHeight(70)
        self.tx_text.setPlaceholderText("Texte à émettre ; Ctrl+Entrée pour l'envoyer")
        v.addWidget(self.tx_text)
        from PySide6.QtGui import QKeySequence, QShortcut
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self.tx_text, activated=self.send_typed)
        h = QHBoxLayout()
        b = QPushButton("Émettre")
        b.clicked.connect(self.send_typed)
        h.addWidget(b)
        b = QPushButton("Stop")
        b.clicked.connect(self.dock.tx.stop)
        h.addWidget(b)
        self.macros = json.loads(s.value("kb_macros", "null") or "null") or DEFAULT_MACROS
        for i, (label, text) in enumerate(self.macros):
            b = QPushButton(label)
            b.setToolTip(text.replace("\n", " / ") + "\n(clic droit : modifier)")
            b.clicked.connect(lambda _c=False, n=i: self.send(self.expand(self.macros[n][1])))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p, n=i, bt=b: self.edit_macro(n, bt))
            h.addWidget(b)
        v.addLayout(h)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        v.addWidget(self.lb)
        self._squelch(self.sl_sq.value())
        self._mode_changed()
        self.t = QTimer(self)
        self.t.timeout.connect(self._status)
        self.t.start(250)

    @property
    def modem(self):
        return self.psk if self.cb_mode.currentIndex() == 0 else self.rtty

    def _mode_changed(self, *_):
        rtty = self.cb_mode.currentIndex() == 1
        self.ck_rev.setVisible(rtty)
        self.ck_afc.setVisible(not rtty)
        self.update_markers()

    def _squelch(self, v):
        self.psk.squelch = v / 100
        self.rtty.squelch = 0.25 + v / 400

    def update_markers(self):
        wf = self.win.wf
        if not self.isVisible():
            for k in ("kb", "kb2"):
                wf.markers.pop(k, None)
            return
        f = self.modem.freq
        if self.cb_mode.currentIndex() == 1:
            wf.markers["kb"] = (f - 85, "#29b6f6", "S")
            wf.markers["kb2"] = (f + 85, "#29b6f6", "M")
        else:
            wf.markers.pop("kb2", None)
            wf.markers["kb"] = (f, "#29b6f6", "PSK")

    def wf_click(self, hz, _mods):
        self.freq = float(hz)
        self.psk.set_freq(hz)
        self.rtty.set_freq(hz)
        self.update_markers()
        return True

    def feed(self, x, sr):
        if self.dock.tx.busy:
            return
        txt = self.modem.feed(x, sr)
        if txt:
            self.rx.moveCursor(QTextCursor.End)
            self.rx.insertPlainText(txt)
            self.rx.moveCursor(QTextCursor.End)

    def _status(self):
        m = self.modem
        self.bar.setValue(int(max(0.0, min(1.0, m.quality if m is self.psk else m.quality * 2)) * 100))
        self.lb_f.setText(f"{m.freq:.0f} Hz")
        if self.cb_mode.currentIndex() == 0 and abs(m.freq - self.freq) > 0.5:
            self.freq = m.freq
            self.update_markers()

    def use_word(self, w):
        w = w.strip(".,?=:;")
        if CALL_RX.match(w):
            self.ed_call.setText(w)

    def expand(self, text):
        st = getattr(self.win, "station", None)
        return (text.replace("{MYCALL}", (self.win.settings.value("mycall", "") or "").upper())
                .replace("{CALL}", self.ed_call.text().strip().upper())
                .replace("{LOC}", self.win.b_loc.text().split()[0] if st else "")
                .replace("{NAME}", self.ed_name.text().strip())
                .replace("{QTH}", self.ed_qth.text().strip()))

    def edit_macro(self, n, button):
        from PySide6.QtWidgets import QInputDialog
        label, ok = QInputDialog.getText(self, "Message programmable", "Nom du bouton :", text=self.macros[n][0])
        if not ok:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Message programmable",
                                                 "Texte ({MYCALL}, {CALL}, {LOC}, {NAME}, {QTH}) :",
                                                 self.macros[n][1])
        if ok:
            self.macros[n] = (label or self.macros[n][0], text)
            button.setText(self.macros[n][0])

    def send_typed(self):
        text = self.tx_text.toPlainText()
        if text.strip():
            self.tx_text.clear()
            self.send(self.expand(text) + ("" if text.endswith("\n") else "\n"))

    def send(self, text):
        if not text.strip():
            return
        tx = self.dock.tx
        sr = tx.rate()
        f = self.modem.freq
        if self.cb_mode.currentIndex() == 0:
            sig = modems.psk31_modulate(text, f, sr, amp=0.9)
        else:
            sig = modems.rtty_modulate(text, f, sr, amp=0.9, reverse=self.ck_rev.isChecked())
        if tx.play(sig, sr, label=text):
            self.dock.owner = self
            self.rx.moveCursor(QTextCursor.End)
            self.rx.appendHtml(f"<span style='color:#ff7043'>{text.strip().replace(chr(10), '<br>')}</span>")
            self.rx.moveCursor(QTextCursor.End)
            self.lb.setText(f"Émission ({len(sig) / sr:.0f} s)…")

    def tx_finished(self, msg):
        self.lb.setText(msg or "Émission terminée")
        self.psk.reset()
        self.psk.set_freq(self.freq)
        self.rtty.set_freq(self.rtty.freq)

    def save_settings(self, s):
        s.setValue("kb_mode", self.cb_mode.currentIndex())
        s.setValue("kb_freq", self.modem.freq)
        s.setValue("kb_squelch", self.sl_sq.value())
        s.setValue("kb_name", self.ed_name.text())
        s.setValue("kb_qth", self.ed_qth.text())
        s.setValue("kb_macros", json.dumps(self.macros))


class DigiDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Modes numériques", win)
        self.win = win
        self.setObjectName("digidock")
        s = win.settings
        self.tx = DigiTx(win)
        self.tx.finished.connect(self._tx_finished)
        self.owner = None
        w = QWidget()
        v = QVBoxLayout(w)
        self.tabs = QTabWidget()
        from .ftxtab import FtxTab
        self.ftx = FtxTab(self)
        self.kb = KeyboardTab(self)
        self.tabs.addTab(self.ftx, "FT8 / FT4")
        self.tabs.addTab(self.kb, "RTTY / PSK31")
        try:
            from .sstvtab import SstvTab
            self.sstv = SstvTab(self)
            self.tabs.addTab(self.sstv, "SSTV")
        except Exception as e:                  # bibliothèque SSTV absente
            self.sstv = None
            self.sstv_error = str(e)
        self.tabs.currentChanged.connect(self._tab_changed)
        v.addWidget(self.tabs, 1)
        h = QHBoxLayout()
        h.addWidget(QLabel("Sortie audio"))
        self.cb_out = QComboBox()
        outs = list_devices("output")
        for i, label in outs:
            self.cb_out.addItem(label, i)
        j = self.cb_out.findText(s.value("digi_out", ""))
        if j < 0:
            j = self.cb_out.findData(guess_radio_output(outs))
        if j >= 0:
            self.cb_out.setCurrentIndex(j)
        self.cb_out.setToolTip("Sortie audio USB du poste (« USB Audio CODEC »)")
        self.cb_out.currentIndexChanged.connect(self._out_changed)
        h.addWidget(self.cb_out, 1)
        h.addWidget(QLabel("Niveau"))
        self.sl_gain = QSlider(Qt.Horizontal)
        self.sl_gain.setRange(1, 100)
        self.sl_gain.setValue(int(s.value("digi_gain", 40)))
        self.sl_gain.setMaximumWidth(140)
        self.sl_gain.setToolTip("Réglez pour que l'ALC ne bouge pas (signal propre, sans harmoniques)")
        self.sl_gain.valueChanged.connect(lambda val: setattr(self.tx, "gain", val / 100))
        h.addWidget(self.sl_gain)
        self.lb_listen = QLabel("")
        self.lb_listen.setObjectName("hint")
        h.addWidget(self.lb_listen)
        v.addLayout(h)
        self.setWidget(w)
        self.setMinimumWidth(620)
        self.tx.gain = self.sl_gain.value() / 100
        self._out_changed()
        self.visibilityChanged.connect(self._visible)

    # --- audio ---------------------------------------------------------------------------
    def _out_changed(self, *_):
        self.tx.device = self.cb_out.currentData()

    def listening(self):
        return self._feed in self.win.wf.listeners and self.win.wf.running

    def start_listening(self):
        wf = self.win.wf
        if not wf.running:
            self.win.b_wf.setChecked(True)
        if wf.running and self._feed not in wf.listeners:
            wf.listeners.append(self._feed)
        self.lb_listen.setText("réception active" if wf.running else
                               "choisissez l'entrée audio du poste (chute d'eau) puis lancez la chute d'eau")

    def _visible(self, vis):
        if vis:
            self.start_listening()
            # la note CW du poste n'a pas de sens ici
            self._tab_changed(self.tabs.currentIndex())
        else:
            for k in ("rx", "tx", "kb", "kb2"):
                self.win.wf.markers.pop(k, None)
            self.win.wf.test_tones = self.win.wf.test_cw = True

    def _tab_changed(self, _i):
        for t in (self.ftx, self.kb):
            t.update_markers()
        if self.sstv:
            self.sstv.update_markers()
        # signal de test : sans les fausses porteuses ni l'appel CW, qui gêneraient ces modes
        self.win.wf.test_tones = self.win.wf.test_cw = not self.isVisible()

    def _feed(self, x, sr):
        if not self.isVisible():
            return
        self.ftx.engine.feed(x, sr)
        cur = self.tabs.currentWidget()
        if cur is self.kb:
            self.kb.feed(x, sr)
        elif self.sstv and cur is self.sstv:
            self.sstv.feed(x, sr)

    def wf_click(self, hz, mods):
        cur = self.tabs.currentWidget()
        return bool(cur and hasattr(cur, "wf_click") and cur.wf_click(hz, mods))

    def _tx_finished(self, msg):
        owner = self.owner or self.ftx
        self.owner = None
        if hasattr(owner, "tx_finished"):
            owner.tx_finished(msg)

    def save_settings(self, s):
        s.setValue("digi_out", self.cb_out.currentText())
        s.setValue("digi_gain", self.sl_gain.value())
        self.ftx.save_settings(s)
        self.kb.save_settings(s)
        if self.sstv:
            self.sstv.save_settings(s)
        self.tx.stop()
