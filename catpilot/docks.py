"""Panneaux annexes : CW au clavier, audio d'émission, éditeur des menus du poste."""
import datetime
import json
import os

import serial.tools.list_ports
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDockWidget, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

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

        t = QLabel("Messages programmables  ({MYCALL}, {CALL}, <BT>, <SK>, <AR>, <KN>)")
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
        h = QHBoxLayout()
        for i in range(1, 6):
            b = QPushButton(f"Mém. {i}")
            b.setToolTip(f"Faire jouer la mémoire {i} du keyer du poste")
            b.clicked.connect(lambda _c=False, n=i: self.play_memory(n))
            h.addWidget(b)
        v.addLayout(h)
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        v.addStretch()
        self._method_changed()

    def save_settings(self, s):
        s.setValue("cw_method", self.cb_method.currentIndex())
        s.setValue("cw_port", self.cb_kport.currentData() or "")
        s.setValue("mycall", self.ed_mycall.text())
        s.setValue("cw_macros", json.dumps([e.text() for e in self.macros]))
        self.stop()
        if self.keyer:
            self.keyer.close()

    def _method_changed(self):
        self.cb_kport.setEnabled(self.cb_method.currentIndex() > 0)
        if self.keyer:
            self.keyer.close()
            self.keyer = None

    def _expand(self, text):
        return (text.replace("{MYCALL}", self.ed_mycall.text().strip().upper())
                    .replace("{CALL}", self.ed_call.text().strip().upper()))

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
            label = f"{mid[:2]}-{mid[2:]}" if len(mid) == 4 else mid
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
