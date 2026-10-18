"""Programmateur : régler tout seul le poste sur une fréquence à une heure donnée
(réseau ADRASEC, balise, rendez-vous…), avec un rappel quelques minutes avant.
"""
import datetime
import json

from PySide6.QtCore import QTime, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTimeEdit,
    QVBoxLayout,
)

DAYS = ["Tous les jours", "Lundi au vendredi", "Samedi et dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi",
        "Vendredi", "Samedi", "Dimanche", "Une seule fois"]


def day_ok(rule, d):
    wd = d.weekday()
    if rule == "Tous les jours" or rule == "Une seule fois":
        return True
    if rule == "Lundi au vendredi":
        return wd < 5
    if rule == "Samedi et dimanche":
        return wd >= 5
    return DAYS.index(rule) - 3 == wd


class Scheduler:
    def __init__(self, win):
        self.win = win
        try:
            self.items = json.loads(win.settings.value("schedule", "[]") or "[]")
        except ValueError:
            self.items = []
        self.done = set()
        t = QTimer(win)
        t.timeout.connect(self.check)
        t.start(15000)

    def save(self):
        self.win.settings.setValue("schedule", json.dumps(self.items))

    def check(self):
        now = datetime.datetime.now()
        for i, it in enumerate(self.items):
            if not it.get("on", True) or not day_ok(it["days"], now):
                continue
            h, m = map(int, it["time"].split(":"))
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            key_go, key_warn = (i, t.date(), "go"), (i, t.date(), "warn")
            lead = int(it.get("remind", 5))
            if lead and 0 <= (t - now).total_seconds() <= lead * 60 and key_warn not in self.done:
                self.done.add(key_warn)
                self._notify(f"Dans {lead} min : {it['label'] or 'rendez-vous'} sur {it['mhz']} MHz {it['mode']}")
            if 0 <= (now - t).total_seconds() < 60 and key_go not in self.done:
                self.done.add(key_go)
                self.go(it)
                if it["days"] == "Une seule fois":
                    it["on"] = False
                    self.save()

    def _notify(self, text):
        self.win.statusBar().showMessage(text, 30000)
        QApplication.beep()
        if getattr(self.win, "speak_schedule", True) and hasattr(self.win, "speaker"):
            self.win.speaker.say(text.replace(".", " virgule "))

    def go(self, it):
        ctrl = self.win.ctrl
        label = it["label"] or "rendez-vous"
        if not ctrl.connected:
            self._notify(f"{label} : poste non connecté, fréquence {it['mhz']} MHz non réglée")
            return
        try:
            ctrl.set_freq(int(round(float(it["mhz"].replace(",", ".")) * 1e6)))
            if it["mode"] and ctrl.driver and it["mode"] in ctrl.driver.modes:
                ctrl.set_mode(it["mode"])
        except ValueError:
            return
        self._notify(f"{label} : poste réglé sur {it['mhz']} MHz {it['mode']}")


class SchedulerDialog(QDialog):
    COLS = ["Actif", "Heure", "Jours", "Fréquence (MHz)", "Mode", "Rappel (min)", "Nom"]

    def __init__(self, win):
        super().__init__(win)
        self.win, self.sch = win, win.scheduler
        self.setWindowTitle("Programmateur")
        self.resize(820, 420)
        v = QVBoxLayout(self)
        t = QLabel("À l'heure dite (heure du PC), CAT Pilot règle le poste et vous prévient ; un rappel "
                   "peut sonner quelques minutes avant. Le logiciel doit rester ouvert.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        v.addWidget(t)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        for label, slot in (("Ajouter", self.add), ("Ajouter la fréquence actuelle", self.add_current),
                            ("Supprimer", self.remove)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            h.addWidget(b)
        h.addStretch()
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for it in self.sch.items:
            self._row(it)

    def _modes(self):
        drv = self.win.ctrl.driver
        from .gui import MODE_BUTTONS
        return [m for m, _l in MODE_BUTTONS] if not drv else list(drv.modes)

    def _row(self, it):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        ck = QCheckBox()
        ck.setChecked(it.get("on", True))
        self.tbl.setCellWidget(r, 0, ck)
        te = QTimeEdit(QTime.fromString(it.get("time", "20:00"), "HH:mm"))
        te.setDisplayFormat("HH:mm")
        self.tbl.setCellWidget(r, 1, te)
        cd = QComboBox()
        cd.addItems(DAYS)
        cd.setCurrentText(it.get("days", "Tous les jours"))
        self.tbl.setCellWidget(r, 2, cd)
        ed = QLineEdit(it.get("mhz", "3.600"))
        self.tbl.setCellWidget(r, 3, ed)
        cm = QComboBox()
        cm.addItems([""] + self._modes())
        cm.setCurrentText(it.get("mode", ""))
        self.tbl.setCellWidget(r, 4, cm)
        sp = QSpinBox()
        sp.setRange(0, 60)
        sp.setValue(int(it.get("remind", 5)))
        self.tbl.setCellWidget(r, 5, sp)
        self.tbl.setItem(r, 6, QTableWidgetItem(it.get("label", "")))

    def add(self):
        self._row({"time": "20:00", "days": "Tous les jours", "mhz": "3.600", "mode": "LSB", "remind": 5,
                   "label": "Réseau"})

    def add_current(self):
        st = self.win._last
        if st and self.win.ctrl.connected:
            self._row({"time": QTime.currentTime().addSecs(3600).toString("HH:mm"), "days": "Une seule fois",
                       "mhz": f"{st.freq / 1e6:.4f}", "mode": st.mode, "remind": 5, "label": ""})
        else:
            self.add()

    def remove(self):
        r = self.tbl.currentRow()
        if r >= 0:
            self.tbl.removeRow(r)

    def accept(self):
        items = []
        for r in range(self.tbl.rowCount()):
            g = self.tbl.cellWidget
            items.append({"on": g(r, 0).isChecked(), "time": g(r, 1).time().toString("HH:mm"),
                          "days": g(r, 2).currentText(), "mhz": g(r, 3).text().strip(), "mode": g(r, 4).currentText(),
                          "remind": g(r, 5).value(), "label": (self.tbl.item(r, 6).text() if self.tbl.item(r, 6) else "")})
        self.sch.items = items
        self.sch.save()
        self.sch.done.clear()
        super().accept()
