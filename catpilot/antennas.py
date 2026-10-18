"""Profils d'antenne : pour chaque bande, l'antenne utilisée, la puissance à ne pas dépasser et un
rappel (réglage de la boîte d'accord, commutateur…). Au changement de bande, CAT Pilot l'affiche
(et l'annonce si demandé) et ramène la puissance sous le maximum.
"""
import json
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)


class Antennas:
    def __init__(self, win):
        self.win = win
        self.load()
        self.band = None
        self._last_clamp = 0.0
        self._pending = QTimer(win)
        self._pending.setSingleShot(True)
        self._pending.timeout.connect(self._band_changed)

    def load(self):
        try:
            self.prof = json.loads(self.win.settings.value("antennas", "{}") or "{}")
        except ValueError:
            self.prof = {}

    def save(self):
        self.win.settings.setValue("antennas", json.dumps(self.prof, ensure_ascii=False))

    def get(self, band):
        p = self.prof.get(band or "", {})
        return p if any(p.get(k) for k in ("ant", "max", "note")) else None

    def label(self):
        p = self.get(self.band)
        return p.get("ant", "") if p else ""

    def describe(self, band):
        p = self.get(band)
        if not p:
            return ""
        parts = [p.get("ant") or "antenne non précisée"]
        if p.get("max"):
            parts.append(f"{p['max']} W max")
        if p.get("note"):
            parts.append(p["note"])
        return " — ".join(parts)

    def on_state(self, st):
        if not self.win.ctrl.connected or not st.freq:
            return
        band = self.win.band_of(st.freq)
        if band != self.band:
            self.band = band
            self._pending.start(1500)            # laisser la puissance mémorisée par bande s'appliquer
            return
        p = self.get(band)
        mx = int(p.get("max") or 0) if p else 0
        pwr = st.p.get("pwr")
        if mx and pwr is not None and pwr > mx and time.monotonic() - self._last_clamp > 3 and not self._pending.isActive():
            self._last_clamp = time.monotonic()
            self.win.ctrl.set_power(mx)
            self.win.statusBar().showMessage(f"Puissance ramenée à {mx} W : maximum de l'antenne sur {band} "
                                             f"({p.get('ant') or 'profil d antenne'})", 8000)

    def _band_changed(self):
        band = self.band
        txt = self.describe(band)
        if not txt:
            return
        self.win.statusBar().showMessage(f"{band} : {txt}", 15000)
        if self.win.settings.value("speak_band", "false") in (True, "true") and hasattr(self.win, "speaker"):
            self.win.speaker.say(f"{band.replace('m', ' mètres').replace('c ', 'centi')}. {txt.replace(' W', ' watts')}")
        st = self.win.ctrl.snapshot()
        p = self.get(band)
        mx = int(p.get("max") or 0)
        if mx and st.p.get("pwr") is not None and st.p["pwr"] > mx:
            self._last_clamp = time.monotonic()
            self.win.ctrl.set_power(mx)


class AntennaDialog(QDialog):
    COLS = ["Bande", "Antenne", "Puissance max", "Rappel (boîte d'accord, commutateur…)"]

    def __init__(self, win):
        super().__init__(win)
        self.win, self.ant = win, win.antennas
        self.setWindowTitle("Profils d'antenne")
        self.resize(820, 560)
        v = QVBoxLayout(self)
        t = QLabel("Pour chaque bande : l'antenne, la puissance à ne pas dépasser (0 = pas de limite) et un rappel. "
                   "Au changement de bande, CAT Pilot l'affiche en bas de la fenêtre (et l'annonce si « Affichage > "
                   "Annonces vocales > Bande et antenne » est coché), et ramène la puissance sous le maximum.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        v.addWidget(t)
        from .gui import BANDS
        drv = win.ctrl.driver
        hi = getattr(drv, "max_freq", 470_000_000) if drv else 470_000_000
        self.bands = [b[0] for b in BANDS if b[1] <= hi]
        tb = QTableWidget(len(self.bands), len(self.COLS))
        tb.setHorizontalHeaderLabels(self.COLS)
        tb.verticalHeader().setVisible(False)
        tb.setSelectionMode(QAbstractItemView.NoSelection)
        hh = tb.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Fixed)
        hh.setStretchLastSection(True)
        for c, wd in ((0, 60), (1, 260), (2, 110)):
            tb.setColumnWidth(c, wd)
        self.ed = []
        top = getattr(drv, "max_power", 100) if drv else 100
        for i, b in enumerate(self.bands):
            p = self.ant.prof.get(b, {})
            it = QTableWidgetItem(b)
            tb.setItem(i, 0, it)
            e_ant = QLineEdit(p.get("ant", ""))
            e_ant.setPlaceholderText("ex. dipôle 40 m, verticale, Yagi 3 él.")
            sp = QSpinBox()
            sp.setRange(0, max(200, top))
            sp.setSuffix(" W")
            sp.setSpecialValueText("—")
            sp.setValue(int(p.get("max") or 0))
            e_note = QLineEdit(p.get("note", ""))
            e_note.setPlaceholderText("ex. boîte : C1 = 45, L = 12 · commutateur position 2")
            tb.setCellWidget(i, 1, e_ant)
            tb.setCellWidget(i, 2, sp)
            tb.setCellWidget(i, 3, e_note)
            self.ed.append((b, e_ant, sp, e_note))
        v.addWidget(tb, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def accept(self):
        prof = {}
        for b, e_ant, sp, e_note in self.ed:
            if e_ant.text().strip() or sp.value() or e_note.text().strip():
                prof[b] = {"ant": e_ant.text().strip(), "max": sp.value(), "note": e_note.text().strip()}
        self.ant.prof = prof
        self.ant.save()
        self.ant.band = None                  # réappliquer tout de suite à la bande actuelle
        super().accept()
