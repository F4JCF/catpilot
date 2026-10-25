"""Panneaux annexes : CW au clavier, audio d'émission, éditeur des menus du poste."""
import datetime
import json
import os

import serial.tools.list_ports
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QPlainTextEdit, QProgressBar, QDialog, QDockWidget, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .cwdecoder import CwDecoder
from .cwkeyer import LineKeyer, duration, normalize
from .memdock import MODIFIED, backup_dir

CW_CHUNK = 50                    # longueur maximale d'une mémoire de keyer du poste
DEFAULT_MACROS = ["CQ CQ CQ DE {MYCALL} {MYCALL} {MYCALL} K",
                  "{CALL} DE {MYCALL} TNX FER CALL UR RST 599 599 <BT> OP JEAN <BT> HW? {CALL} DE {MYCALL} K",
                  "{CALL} DE {MYCALL} TNX FER QSO 73 <SK>",
                  "QRZ? DE {MYCALL} K",
                  "TU 73 DE {MYCALL} <SK>"]


def _dock_widget(dock):
    w = QWidget()
    v = QVBoxLayout(w)
    dock.setWidget(w)
    return v


class DecodedText(QPlainTextEdit):
    """Texte reçu ; un double-clic sur un mot le propose comme indicatif du correspondant."""
    word = Signal(str)

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)
        w = self.textCursor().selectedText().strip().upper()
        if w:
            self.word.emit(w)


# --- CW au clavier ------------------------------------------------------------------------
class CwDock(QDockWidget):
    def __init__(self, win):
        super().__init__("CW au clavier", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("cwdock")
        self.keyer = None
        self.queue = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._next_chunk)
        s = win.settings
        v = _dock_widget(self)

        g = QGridLayout()
        self.cb_method = QComboBox()
        self.cb_method.addItems(["Mémoire 5 du keyer du poste (CAT)", "Ligne DTR du port Standard",
                                 "Ligne RTS du port Standard"])
        self.cb_method.setToolTip("CAT : rien à régler, mais la mémoire 5 du keyer du poste est réécrite.\n"
                                  "DTR / RTS : régler le menu PC KEYING du poste sur DTR (ou RTS).")
        self.cb_method.setCurrentIndex(int(s.value("cw_method", 0)))
        self.cb_method.currentIndexChanged.connect(self._method_changed)
        self.cb_kport = QComboBox()
        for p in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device):
            self.cb_kport.addItem(f"{p.device} — {p.description}", p.device)
            if "standard" in p.description.lower():
                self.cb_kport.setCurrentIndex(self.cb_kport.count() - 1)
        i = self.cb_kport.findData(s.value("cw_port", ""))
        if i >= 0:
            self.cb_kport.setCurrentIndex(i)
        self.ed_mycall = QLineEdit(s.value("mycall", ""))
        self.ed_mycall.setPlaceholderText("Mon indicatif")
        self.ed_call = QLineEdit()
        self.ed_call.setPlaceholderText("Correspondant")
        g.addWidget(QLabel("Émission"), 0, 0)
        g.addWidget(self.cb_method, 0, 1, 1, 3)
        g.addWidget(QLabel("Port"), 1, 0)
        g.addWidget(self.cb_kport, 1, 1, 1, 3)
        g.addWidget(QLabel("Indicatif"), 2, 0)
        g.addWidget(self.ed_mycall, 2, 1)
        g.addWidget(QLabel("Corresp."), 2, 2)
        g.addWidget(self.ed_call, 2, 3)
        # vitesse réglée ici quand le poste ne la donne pas par le CAT (FT-817/857/897)
        self.lb_wpm = QLabel("Vitesse")
        self.sp_wpm = QSpinBox()
        self.sp_wpm.setRange(5, 50)
        self.sp_wpm.setSuffix(" wpm")
        self.sp_wpm.setValue(int(s.value("cw_wpm", 20)))
        g.addWidget(self.lb_wpm, 3, 0)
        g.addWidget(self.sp_wpm, 3, 1)
        self.lb_key_hint = QLabel("Manipulation par la ligne DTR ou RTS d'une interface reliée à la prise "
                                  "KEY du poste (Digirig, interface CW série…). Ce port doit être différent "
                                  "du port CAT, sauf si l'interface le permet.")
        self.lb_key_hint.setObjectName("hint")
        self.lb_key_hint.setWordWrap(True)
        g.addWidget(self.lb_key_hint, 4, 0, 1, 4)
        self.lb_wpm.hide()
        self.sp_wpm.hide()
        self.lb_key_hint.hide()
        v.addLayout(g)

        self.ed_text = QLineEdit()
        self.ed_text.setPlaceholderText("Texte à émettre en CW, puis Entrée")
        self.ed_text.returnPressed.connect(lambda: self.send(self.ed_text.text(), clear=True))
        v.addWidget(self.ed_text)
        h = QHBoxLayout()
        b = QPushButton("Émettre")
        b.clicked.connect(lambda: self.send(self.ed_text.text(), clear=True))
        h.addWidget(b)
        b = QPushButton("Stop")
        b.clicked.connect(self.stop)
        h.addWidget(b)
        v.addLayout(h)

        t = QLabel("Messages programmables  ({MYCALL}, {CALL}, {NR}, <BT>, <SK>, <AR>, <KN>)")
        t.setObjectName("hint")
        v.addWidget(t)
        self.macros = []
        saved = json.loads(s.value("cw_macros", "null") or "null") or DEFAULT_MACROS
        mg = QGridLayout()
        for i in range(5):
            ed = QLineEdit(saved[i] if i < len(saved) else "")
            b = QPushButton(f"F{i + 1}")
            b.setToolTip(f"Émettre ce message (raccourci Alt+F{i + 1})")
            b.clicked.connect(lambda _c=False, e=ed: self.send(e.text()))
            mg.addWidget(b, i, 0)
            mg.addWidget(ed, i, 1)
            self.macros.append(ed)
        v.addLayout(mg)

        t = QLabel("Messages enregistrés dans le poste")
        t.setObjectName("hint")
        v.addWidget(t)
        self.rig_mem_widgets = [t]
        h = QHBoxLayout()
        for i in range(1, 6):
            b = QPushButton(f"Mém. {i}")
            b.setToolTip(f"Faire jouer la mémoire {i} du keyer du poste")
            b.clicked.connect(lambda _c=False, n=i: self.play_memory(n))
            h.addWidget(b)
            self.rig_mem_widgets.append(b)
        v.addLayout(h)
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)

        # --- CQ automatique ---
        h = QHBoxLayout()
        self.b_cq = QPushButton("CQ auto")
        self.b_cq.setCheckable(True)
        self.b_cq.setToolTip("Répète le message choisi, en écoutant entre deux appels.\n"
                             "S'arrête tout seul quand le décodeur entend un indicatif qui vous répond\n"
                             "(il passe alors dans Correspondant et dans le carnet).")
        self.b_cq.toggled.connect(self.toggle_cq)
        h.addWidget(self.b_cq)
        self.cb_cq = QComboBox()
        self.cb_cq.addItems([f"F{i + 1}" for i in range(5)])
        self.cb_cq.setToolTip("Message répété")
        h.addWidget(self.cb_cq)
        h.addWidget(QLabel("écoute"))
        self.sp_cq = QSpinBox()
        self.sp_cq.setRange(2, 60)
        self.sp_cq.setSuffix(" s")
        self.sp_cq.setValue(int(s.value("cq_listen", 8)))
        self.sp_cq.setToolTip("Durée d'écoute entre deux appels")
        h.addWidget(self.sp_cq)
        h.addWidget(QLabel("au plus"))
        self.sp_cqmax = QSpinBox()
        self.sp_cqmax.setRange(1, 100)
        self.sp_cqmax.setSuffix(" appels")
        self.sp_cqmax.setValue(int(s.value("cq_max", 20)))
        h.addWidget(self.sp_cqmax)
        h.addStretch()
        v.addLayout(h)
        self.cq_timer = QTimer(self)
        self.cq_timer.setSingleShot(True)
        self.cq_timer.timeout.connect(self._cq_next)
        self._cq_n = 0
        self._heard = ""

        # --- réception : décodeur CW ---
        t = QLabel("Réception : décodeur CW (audio USB du poste, comme la chute d'eau)")
        t.setObjectName("hint")
        v.addWidget(t)
        self.decoder = CwDecoder()
        h = QHBoxLayout()
        self.b_dec = QPushButton("Décoder")
        self.b_dec.setCheckable(True)
        self.b_dec.setToolTip("Décoder le morse reçu. Lance la chute d'eau si besoin.")
        self.b_dec.toggled.connect(self.toggle_decoder)
        h.addWidget(self.b_dec)
        self.ck_auto = QCheckBox("Note auto")
        self.ck_auto.setToolTip("Coché : suit le signal CW le plus fort (300 à 1500 Hz).\n"
                                "Décoché : décode sur la tonalité CW du poste (PITCH) ;\n"
                                "un clic sur un signal dans la chute d'eau l'y amène.")
        self.ck_auto.setChecked(s.value("cwdec_auto", "true") in (True, "true"))
        self.ck_auto.toggled.connect(lambda on: setattr(self.decoder, "auto", on))
        self.decoder.auto = self.ck_auto.isChecked()
        h.addWidget(self.ck_auto)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(10)
        self.bar.setMaximumWidth(70)
        self.bar.setToolTip("Signal décodé (le seuil s'adapte tout seul)")
        h.addWidget(self.bar)
        self.lb_dec = QLabel("")
        self.lb_dec.setObjectName("value")
        h.addWidget(self.lb_dec, 1)
        b = QPushButton("Effacer")
        b.clicked.connect(lambda: self.rx.clear())
        h.addWidget(b)
        v.addLayout(h)
        self.rx = DecodedText()
        self.rx.setReadOnly(True)
        self.rx.setMaximumBlockCount(500)
        self.rx.setMinimumHeight(70)
        self.rx.setPlaceholderText("Le texte reçu s'affiche ici. Double-clic sur un indicatif : "
                                   "il passe dans Correspondant et dans le carnet.")
        self.rx.word.connect(self.use_word)
        v.addWidget(self.rx, 1)
        self.dec_timer = QTimer(self)
        self.dec_timer.timeout.connect(self._dec_status)
        self._method_changed()

    # --- décodeur ---------------------------------------------------------------------
    def toggle_decoder(self, on):
        wf = self.win.wf
        if on:
            if not wf.running:
                self.win.b_wf.setChecked(True)
                if not wf.running:             # pas d'audio : on renonce
                    self.b_dec.blockSignals(True)
                    self.b_dec.setChecked(False)
                    self.b_dec.blockSignals(False)
                    self.lb_dec.setText("Choisissez l'entrée audio du poste (chute d'eau)")
                    return
            self.decoder.reset()
            if self._feed not in wf.listeners:
                wf.listeners.append(self._feed)
            self.dec_timer.start(200)
        else:
            if self._feed in wf.listeners:
                wf.listeners.remove(self._feed)
            self.dec_timer.stop()
            wf.cw_marker = None
            self.bar.setValue(0)
            self.lb_dec.setText("")

    def _transmitting(self):
        st = self.ctrl.snapshot() if self.ctrl.connected else None
        return bool((st and st.ptt) or (self.keyer and self.keyer.busy) or self.queue
                    or self.timer.isActive())

    # --- CQ automatique ------------------------------------------------------------------
    def toggle_cq(self, on):
        if on:
            if not self._ready():
                self.b_cq.blockSignals(True)
                self.b_cq.setChecked(False)
                self.b_cq.blockSignals(False)
                return
            if not self.b_dec.isChecked():
                self.b_dec.setChecked(True)          # pour entendre qui répond
            self._cq_n = 0
            self._cq_next()
        else:
            self.cq_timer.stop()
            if self._cq_n:
                self.lb.setText(f"CQ auto arrêté après {self._cq_n} appel{'s' if self._cq_n > 1 else ''}")

    def _cq_next(self):
        if not self.b_cq.isChecked():
            return
        if self._cq_n >= self.sp_cqmax.value():
            self.b_cq.setChecked(False)
            return
        text = normalize(self._expand(self.macros[self.cb_cq.currentIndex()].text()))
        if not text.strip():
            self.b_cq.setChecked(False)
            return
        self._cq_n += 1
        self.send(text)
        self._heard = ""
        busy = duration(text, self.wpm()) + 0.6
        self.lb.setText(f"CQ auto : appel {self._cq_n}/{self.sp_cqmax.value()}, "
                        f"puis {self.sp_cq.value()} s d'écoute")
        self.cq_timer.start(int((busy + self.sp_cq.value()) * 1000))

    def _check_reply(self, txt):
        """Pendant l'écoute du CQ auto : un indicatif qui répond arrête les appels."""
        import re
        if not self.b_cq.isChecked() or self._transmitting():
            return
        self._heard += txt
        mine = self.ed_mycall.text().strip().upper()
        words = re.findall(r"[A-Z0-9/]+", self._heard.upper())
        rx = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}\d[A-Z]{1,4}(/[A-Z0-9]{1,4})?$")
        for i, w in enumerate(words):
            if not rx.match(w) or w == mine or w.split("/")[0] == mine:
                continue
            twice = self._heard.upper().count(w) >= 2      # aussi dans « BOK1ABC » mal découpé
            after_de = i > 0 and (words[i - 1] == "DE" or words[i - 1].endswith(mine))
            after_de = after_de or (i + 1 < len(words) and words[i + 1] in ("K", "KN", "AR", "<KN>"))
            if twice or after_de:
                self.b_cq.setChecked(False)
                self.use_word(w)
                self.lb.setText(f"{w} vous répond ! CQ auto arrêté. F2 pour lui passer le report.")
                from PySide6.QtWidgets import QApplication
                QApplication.beep()
                return

    def _feed(self, x, sr):
        self.decoder.pitch = float(self.win.wf.marker or 700)
        if self._transmitting():           # pendant l'émission, l'audio reçu n'a pas de sens
            self._tx_hold = 4               # et on attend encore un peu après
            return
        if getattr(self, "_tx_hold", 0):
            self._tx_hold -= 1
            if not self._tx_hold:
                self.decoder.reset()
            return
        txt = self.decoder.feed(x, sr)
        if txt:
            self.rx.moveCursor(QTextCursor.End)
            self.rx.insertPlainText(txt)
            self.rx.moveCursor(QTextCursor.End)
            self._check_reply(txt)

    def _dec_status(self):
        d = self.decoder
        f = d.freq if d.auto else d.pitch
        self.win.wf.cw_marker = f
        if getattr(self, "_tx_hold", 0) or self._transmitting():
            self.bar.setValue(0)
            self.lb_dec.setText("en pause pendant l'émission")
            return
        ok = d.snr >= 9 and (d._n / max(1, d.sr)) - d._tone_t < 6.0
        self.bar.setValue(int(d.level * 100) if ok and d.key else 0)
        self.lb_dec.setText(f"{f:.0f} Hz · {d.wpm} mots/min · {d.snr:.0f} dB" if ok
                            else f"{f:.0f} Hz · pas de signal CW")

    def use_word(self, w):
        import re
        w = w.strip(".,?=")
        if not re.match(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}\d[A-Z]{1,4}(/[A-Z0-9]{1,4})?$", w):
            return
        self.ed_call.setText(w)
        log = getattr(self.win, "logdock", None)
        if log:
            log.ed_call.setText(w)
            log.on_call_edit(w)

    def save_settings(self, s):
        s.setValue("cwdec_auto", self.ck_auto.isChecked())
        s.setValue("cq_listen", self.sp_cq.value())
        s.setValue("cq_max", self.sp_cqmax.value())
        s.setValue("cw_method", self.cb_method.currentIndex())
        s.setValue("cw_wpm", self.sp_wpm.value())
        s.setValue("cw_port", self.cb_kport.currentData() or "")
        s.setValue("mycall", self.ed_mycall.text())
        s.setValue("cw_macros", json.dumps([e.text() for e in self.macros]))
        self.stop()
        if self.keyer:
            self.keyer.close()

    def adapt(self, drv):
        """Sans keyer pilotable par CAT : manipulation par DTR/RTS et vitesse réglée ici."""
        cat = getattr(drv, "has_cw_memory", True)
        item = self.cb_method.model().item(0)
        if item is not None:
            item.setEnabled(cat)
        if not cat and self.cb_method.currentIndex() == 0:
            self.cb_method.setCurrentIndex(1)
        for w in self.rig_mem_widgets:
            w.setVisible(cat)
        for w in (self.lb_wpm, self.sp_wpm, self.lb_key_hint):
            w.setVisible(not cat)
        self._own_wpm = not cat

    def _method_changed(self):
        self.cb_kport.setEnabled(self.cb_method.currentIndex() > 0)
        if self.keyer:
            self.keyer.close()
            self.keyer = None

    def _expand(self, text):
        log = getattr(self.win, "logdock", None)
        nr = f"{log.sp_serial.value():03d}" if log else "001"
        return (text.replace("{MYCALL}", self.ed_mycall.text().strip().upper())
                    .replace("{CALL}", self.ed_call.text().strip().upper()).replace("{NR}", nr))

    def _ready(self):
        if not self.ctrl.connected:
            self.lb.setText("Pas de poste connecté")
            return False
        st = self.ctrl.snapshot()
        if st.mode not in ("CW", "CWR"):
            if QMessageBox.question(self, "CW", "Le poste n'est pas en CW. Passer en CW ?") != QMessageBox.Yes:
                return False
            self.ctrl.set_mode("CW")
        if self.cb_method.currentIndex() > 0 and not st.p.get("bkin"):
            self.ctrl.set_param("bkin", True)        # sans BK-IN, la manipulation n'émet pas
        return True

    def wpm(self):
        if getattr(self, "_own_wpm", False):
            return self.sp_wpm.value()
        return int(self.ctrl.snapshot().p.get("wpm", 20))

    def send(self, text, clear=False):
        text = normalize(self._expand(text))
        if not text.strip() or not self._ready():
            return
        if clear:
            self.ed_text.clear()
        wpm = self.wpm()
        if self.cb_method.currentIndex() == 0:
            # découpage en morceaux de 50 caractères, en coupant entre les mots
            words, chunk, self.queue = text.split(), "", []
            for w in words:
                if len(chunk) + len(w) + 1 > CW_CHUNK and chunk:
                    self.queue.append(chunk)
                    chunk = ""
                chunk = f"{chunk} {w}".strip()
            if chunk:
                self.queue.append(chunk)
            self._next_chunk()
        else:
            try:
                if not self.keyer:
                    line = "RTS" if self.cb_method.currentIndex() == 2 else "DTR"
                    self.keyer = LineKeyer(self.cb_kport.currentData(), line)
            except Exception as e:
                QMessageBox.warning(self, "CW", f"Le port {self.cb_kport.currentData()} n'a pas pu être ouvert.\n\n{e}")
                return
            self.keyer.send(text, wpm)
        self.lb.setText(f"Émission ({wpm} wpm, ≈ {duration(text, wpm):.0f} s) : {text}")

    def _next_chunk(self):
        if not self.queue:
            return
        chunk = self.queue.pop(0)
        # la mémoire du keyer ne connaît pas les signes <..> : équivalents en un caractère
        cat = (chunk.replace("<BT>", "=").replace("<AR>", "+").replace("<KN>", "(")
                    .replace("<SK>", "SK").replace("<AS>", "AS"))
        self.ctrl.action("cw_text", cat)
        self.timer.start(int((duration(chunk, self.wpm()) + 0.4) * 1000))

    def play_memory(self, n):
        if self._ready():
            self.ctrl.action("cw_play", n)
            self.lb.setText(f"Mémoire {n} du keyer en cours d'émission")

    def stop(self):
        if self.b_cq.isChecked():
            self.b_cq.setChecked(False)
        self.queue = []
        self.timer.stop()
        if self.keyer:
            self.keyer.stop()
        self.lb.setText("Arrêt demandé (un message déjà transmis au poste se termine)"
                        if self.cb_method.currentIndex() == 0 else "Arrêté")


# --- audio d'émission -----------------------------------------------------------------------
class TxAudioDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Audio d'émission", win)
        self.setObjectName("txaudiodock")
        v = _dock_widget(self)
        g = QGridLayout()
        rows = [("mic_eq", "Égaliseur micro", None, None, None),
                ("proc", "Processeur", "proc_lvl", 0, 100),
                ("mon", "Moniteur", "mon_lvl", 0, 100),
                ("vox", "VOX", "vox_gain", 0, 100)]
        for r, (tkey, label, skey, lo, hi) in enumerate(rows):
            if tkey in win.toggles:          # déjà présent sur la face avant : on crée un double
                b = win._btn(label, checkable=True)
                b.clicked.connect(lambda c, k=tkey: win.ctrl.set_param(k, c))
                win.extra_toggles.append((tkey, b))
            else:
                b = win._toggle(tkey, label)
            g.addWidget(b, r, 0)
            if skey:
                s, val = win._slider(skey, lo, hi, lambda x: f"niveau {x}")
                val.setMinimumWidth(70)
                g.addWidget(s, r, 1)
                g.addWidget(val, r, 2)
        v.addLayout(g)
        t = QLabel("Réglage fin de l'égaliseur (fréquence, niveau et largeur des 3 bandes) "
                   "et des filtres d'émission : par les menus du poste.")
        t.setObjectName("hint")
        t.setWordWrap(True)
        v.addWidget(t)
        h = QHBoxLayout()
        b = win._btn("Menus de l'égaliseur…", lambda: win.open_menu_editor("EQ"))
        h.addWidget(b)
        b = win._btn("Tous les menus…", lambda: win.open_menu_editor(""))
        h.addWidget(b)
        v.addLayout(h)
        v.addStretch()


# --- éditeur des menus -------------------------------------------------------------------------
# Noms indicatifs (manuel du FT-991A). À vérifier sur l'écran du poste avant toute modification.
FT991A_MENU_NAMES = {
    "001": "AGC FAST DELAY", "002": "AGC MID DELAY", "003": "AGC SLOW DELAY", "004": "HOME FUNCTION",
    "005": "MY CALL INDICATION", "006": "DISPLAY COLOR", "007": "DIMMER LED", "008": "DIMMER TFT",
    "009": "BAR MTR PEAK HOLD", "010": "DVS RX OUT LEVEL", "011": "DVS TX OUT LEVEL",
    "012": "KEYER TYPE", "013": "KEYER DOT/DASH", "014": "CW WEIGHT", "015": "BEACON INTERVAL",
    "016": "NUMBER STYLE", "017": "CONTEST NUMBER", "018": "CW MEMORY 1", "019": "CW MEMORY 2",
    "020": "CW MEMORY 3", "021": "CW MEMORY 4", "022": "CW MEMORY 5", "023": "NB WIDTH",
    "024": "NB REJECTION", "025": "NB LEVEL", "026": "BEEP LEVEL", "027": "TIME ZONE",
    "028": "GPS/232C SELECT", "029": "232C RATE", "030": "232C TOT", "031": "CAT RATE",
    "032": "CAT TOT", "033": "CAT RTS", "034": "MEM GROUP", "035": "QUICK SPLIT FREQ",
    "036": "TX TOT", "037": "MIC SCAN", "038": "MIC SCAN RESUME", "039": "REF FREQ ADJ",
    "040": "CLAR MODE",
    "122": "PRMTRC EQ1 FREQ", "123": "PRMTRC EQ1 LEVEL", "124": "PRMTRC EQ1 BWTH",
    "125": "PRMTRC EQ2 FREQ", "126": "PRMTRC EQ2 LEVEL", "127": "PRMTRC EQ2 BWTH",
    "128": "PRMTRC EQ3 FREQ", "129": "PRMTRC EQ3 LEVEL", "130": "PRMTRC EQ3 BWTH",
    "131": "P-PRMTRC EQ1 FREQ", "132": "P-PRMTRC EQ1 LEVEL", "133": "P-PRMTRC EQ1 BWTH",
    "134": "P-PRMTRC EQ2 FREQ", "135": "P-PRMTRC EQ2 LEVEL", "136": "P-PRMTRC EQ2 BWTH",
    "137": "P-PRMTRC EQ3 FREQ", "138": "P-PRMTRC EQ3 LEVEL", "139": "P-PRMTRC EQ3 BWTH",
    "140": "HF TX MAX POWER", "141": "50M TX MAX POWER", "142": "144M TX MAX POWER",
    "143": "430M TX MAX POWER",
}


class MenuEditor(QDialog):
    def __init__(self, win, flt=""):
        super().__init__(win)
        self.win, self.ctrl = win, win.ctrl
        self.setWindowTitle("Menus du poste")
        self.resize(620, 640)
        self.values, self.modified = {}, set()
        self.names = FT991A_MENU_NAMES if self.ctrl.driver and self.ctrl.driver.name.endswith("991A") else {}
        self._filling = False
        self._backed_up = False
        v = QVBoxLayout(self)
        warn = QLabel("Les noms sont indicatifs : comparez avec le menu affiché sur le poste avant de "
                      "modifier. Une sauvegarde complète des menus est faite avant la première écriture. "
                      "Les valeurs sont celles du protocole CAT, pas toujours celles de l'écran.")
        warn.setWordWrap(True)
        warn.setObjectName("hint")
        v.addWidget(warn)
        h = QHBoxLayout()
        self.ed_filter = QLineEdit(flt)
        self.ed_filter.setPlaceholderText("Filtrer (numéro ou nom, ex. EQ, POWER, CW)")
        self.ed_filter.textChanged.connect(self.refresh)
        h.addWidget(self.ed_filter, 1)
        b = QPushButton("Lire depuis le poste")
        b.clicked.connect(lambda: self.ctrl.job("read_menus"))
        h.addWidget(b)
        v.addLayout(h)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Menu", "Nom (indicatif)", "Valeur CAT"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.itemChanged.connect(self.on_changed)
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        h.addWidget(self.lb, 1)
        b = QPushButton("Écrire les modifications")
        b.clicked.connect(self.write)
        h.addWidget(b)
        b = QPushButton("Fermer")
        b.clicked.connect(self.close)
        h.addWidget(b)
        v.addLayout(h)
        self.ctrl.job_done.connect(self.on_job)
        self.ctrl.job("read_menus")
        self.lb.setText("Lecture des menus…")

    def on_job(self, name, res):
        if not self.isVisible() or isinstance(res, Exception):
            return
        if name == "read_menus":
            self.values = dict(res)
            self.original = dict(res)
            self.modified.clear()
            self.refresh()
            self.lb.setText(f"{len(res)} menus lus")
        elif name == "write_menus":
            ok, bad = res["changed"], res["failed"]
            self.lb.setText(f"{len(ok)} menu(s) modifié(s)" + (f", échec : {', '.join(bad)}" if bad else ""))
            self.ctrl.job("read_menus")

    def refresh(self):
        flt = self.ed_filter.text().strip().upper()
        rows = [(mid, self.names.get(mid, ""), val) for mid, val in sorted(self.values.items())
                if not flt or flt in mid or flt in self.names.get(mid, "")]
        self._filling = True
        self.tbl.setRowCount(len(rows))
        for r, (mid, name, val) in enumerate(rows):
            dash = getattr(self.ctrl.driver, "menu_dash", True)
            label = mid
            if dash and len(mid) == 4:
                label = f"{mid[:2]}-{mid[2:]}"
            elif dash and len(mid) == 6:
                label = f"{mid[:2]}-{mid[2:4]}-{mid[4:]}"
            for c, txt in enumerate((label, name, val)):
                it = QTableWidgetItem(txt)
                it.setData(Qt.UserRole, mid)
                if c < 2 or mid in self.ctrl.driver.menu_skip:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if mid in self.modified:
                    it.setBackground(MODIFIED)
                self.tbl.setItem(r, c, it)
        self._filling = False

    def on_changed(self, it):
        if self._filling or it.column() != 2:
            return
        mid = it.data(Qt.UserRole)
        self.values[mid] = it.text().strip()
        if self.values[mid] != self.original.get(mid):
            self.modified.add(mid)
        else:
            self.modified.discard(mid)
        self.refresh()

    def write(self):
        if not self.modified:
            return
        todo = {m: self.values[m] for m in sorted(self.modified)}
        lst = "\n".join(f"{m}  {self.names.get(m, '')} : {self.original.get(m)} → {v}" for m, v in todo.items())
        if QMessageBox.question(self, "Écrire les menus", f"Modifier ces menus du poste ?\n\n{lst}") != QMessageBox.Yes:
            return
        if not self._backed_up:
            stamp = datetime.datetime.now()
            path = os.path.join(backup_dir(), f"menus_avant_modification_{stamp:%Y%m%d_%H%M%S}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"poste": self.ctrl.driver.name, "date": f"{stamp:%d/%m/%Y %H:%M}",
                           "menus": self.original}, f, ensure_ascii=False, indent=1)
            self._backed_up = True
        self.ctrl.job("write_menus", todo)
        self.lb.setText("Écriture en cours…")
