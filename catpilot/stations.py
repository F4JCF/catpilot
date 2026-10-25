"""Indicatifs et matériel : à chaque indicatif (F4JCF, F4JCF/P, FR/F4JCF/P…) son poste,
son port, sa vitesse et, si besoin, son locator. Choisir l'indicatif dans le carnet
(« Je trafique en ») change le poste piloté.
"""
import json
import sys

import serial.tools.list_ports
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

KEEP = "— poste actuel (ne rien changer)"
BAUDS = ["4800", "9600", "19200", "38400", "57600", "115200"]


def load(settings):
    try:
        return json.loads(settings.value("call_profiles", "{}") or "{}")
    except ValueError:
        return {}


def save(settings, prof):
    settings.setValue("call_profiles", json.dumps(prof, ensure_ascii=False))


def ports():
    out = []
    for p in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device):
        if sys.platform != "win32" and not (p.vid or "USB" in p.device or "ACM" in p.device):
            continue
        out.append((p.device, f"{p.device} — {p.description}"))
    return out


def apply(win, call):
    """Règle le poste de cet indicatif. Renvoie un message (ou "")."""
    from .drivers import DRIVERS
    prof = load(win.settings).get(call) or {}
    msg = []
    loc = (prof.get("loc") or "").strip()
    if loc:
        try:
            from .geo import from_locator
            win.set_station(*from_locator(loc), f"locator de {call}")
            win._call_loc = True
            msg.append(f"locator {loc}")
        except ValueError:
            pass
    elif getattr(win, "_call_loc", False):         # retour à la position habituelle
        win._call_loc = False
        win.load_position()
    rig = prof.get("rig")
    if not rig or rig not in DRIVERS:
        return " · ".join(msg)
    port, baud, stop = prof.get("port", ""), str(prof.get("baud", "")), str(prof.get("stop", ""))
    same = (win.cb_rig.currentText() == rig and (not port or win.cb_port.currentData() == port)
            and (not baud or win.cb_baud.currentText() == baud) and (not stop or win.cb_stop.currentText() == stop))
    if same:
        return " · ".join(msg + [rig])
    if win._last and win._last.ptt:
        return "poste en émission : changement de poste annulé"
    was = win.ctrl.connected
    if was:
        win.ctrl.disconnect_rig()            # sans éteindre le poste précédent
    win.cb_rig.setCurrentText(rig)           # remet vitesse et stop par défaut du modèle…
    if port:
        win.refresh_ports()
        i = win.cb_port.findData(port)
        if i < 0:
            win.cb_port.addItem(f"{port} — (non branché)", port)
            i = win.cb_port.count() - 1
        win.cb_port.setCurrentIndex(i)
    if baud:                                 # … puis ceux de l'indicatif
        win.cb_baud.setCurrentText(baud)
    if stop:
        win.cb_stop.setCurrentText(stop)
    where = f"{rig}" + (f" sur {port}" if port else "")
    if was:
        win.toggle_connection()
        msg.append(f"poste changé : {where}" if win.ctrl.connected else f"{where} : connexion impossible")
    else:
        msg.append(f"poste réglé : {where} (cliquez sur Connecter)")
    return " · ".join(msg)


class StationsDialog(QDialog):
    COLS = ["Indicatif", "Poste", "Port", "Vitesse", "Stop", "Locator (facultatif)"]

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Indicatifs et matériel")
        self.resize(980, 420)
        v = QVBoxLayout(self)
        t = QLabel("Pour chaque indicatif, le poste utilisé. Quand vous choisissez l'indicatif dans le carnet "
                   "(« Je trafique en »), CAT Pilot passe sur ce poste (et ce port), et se reconnecte s'il était "
                   "connecté. Le locator, s'il est rempli, devient la position de la station (utile en portable). "
                   "« Poste actuel » : l'indicatif ne change pas de matériel.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        v.addWidget(t)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for c, w in enumerate((150, 220, 300, 90, 60)):
            self.tbl.setColumnWidth(c, w)
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        for label, slot in (("Ajouter un indicatif", self.add), ("Copier le réglage actuel sur la ligne", self.copy_current),
                            ("Supprimer la ligne", self.remove)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            h.addWidget(b)
        h.addStretch()
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        from .logbook import my_calls
        self.ports = ports()
        prof = load(win.settings)
        for call in my_calls(win.settings):
            self._row(call, prof.get(call, {}))
        if not self.tbl.rowCount():
            self.add()

    def _row(self, call, p):
        from .drivers import DRIVERS
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        self.tbl.setItem(r, 0, QTableWidgetItem(call))
        cb = QComboBox()
        cb.addItem(KEEP)
        cb.addItems([k for k in DRIVERS if not k.startswith("Poste distant")])
        cb.setCurrentText(p.get("rig") or KEEP)
        self.tbl.setCellWidget(r, 1, cb)
        cp = QComboBox()
        cp.setEditable(True)
        cp.addItem("", "")
        for dev, label in self.ports:
            cp.addItem(label, dev)
        port = p.get("port", "")
        i = cp.findData(port)
        if i >= 0:
            cp.setCurrentIndex(i)
        else:
            cp.setEditText(port)
        self.tbl.setCellWidget(r, 2, cp)
        cbd = QComboBox()
        cbd.addItems([""] + BAUDS)
        cbd.setCurrentText(str(p.get("baud", "")))
        self.tbl.setCellWidget(r, 3, cbd)
        cs = QComboBox()
        cs.addItems(["", "1", "2"])
        cs.setCurrentText(str(p.get("stop", "")))
        self.tbl.setCellWidget(r, 4, cs)
        ed = QLineEdit(p.get("loc", ""))
        ed.setPlaceholderText("ex. JN33LP (sinon : position habituelle)")
        self.tbl.setCellWidget(r, 5, ed)

        def model_changed(name, row=r):
            cls = DRIVERS.get(name)
            if cls and not self.tbl.cellWidget(row, 3).currentText():
                self.tbl.cellWidget(row, 3).setCurrentText(str(cls.default_baud))
                self.tbl.cellWidget(row, 4).setCurrentText(str(cls.default_stopbits))
        cb.currentTextChanged.connect(model_changed)

    def add(self):
        self._row("", {})
        self.tbl.setCurrentCell(self.tbl.rowCount() - 1, 0)
        self.tbl.editItem(self.tbl.item(self.tbl.rowCount() - 1, 0))

    def copy_current(self):
        r = self.tbl.currentRow()
        if r < 0:
            QMessageBox.information(self, "Indicatifs", "Cliquez d'abord sur la ligne de l'indicatif.")
            return
        w = self.win
        self.tbl.cellWidget(r, 1).setCurrentText(w.cb_rig.currentText())
        cp = self.tbl.cellWidget(r, 2)
        i = cp.findData(w.cb_port.currentData())
        if i >= 0:
            cp.setCurrentIndex(i)
        else:
            cp.setEditText(w.cb_port.currentData() or "")
        self.tbl.cellWidget(r, 3).setCurrentText(w.cb_baud.currentText())
        self.tbl.cellWidget(r, 4).setCurrentText(w.cb_stop.currentText())

    def remove(self):
        r = self.tbl.currentRow()
        if r >= 0:
            self.tbl.removeRow(r)

    def accept(self):
        from .logbook import CALL_RE
        calls, prof = [], {}
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            call = (it.text() if it else "").strip().upper().replace(" ", "")
            if not call:
                continue
            if not CALL_RE.match(call):
                QMessageBox.warning(self, "Indicatif", f"« {call} » ne ressemble pas à un indicatif.")
                return
            if call in calls:
                continue
            calls.append(call)
            rig = self.tbl.cellWidget(r, 1).currentText()
            cp = self.tbl.cellWidget(r, 2)
            port = cp.currentData() if cp.currentText() == cp.itemText(cp.currentIndex()) and cp.currentData() \
                else cp.currentText().split(" — ")[0].strip()
            p = {"rig": "" if rig == KEEP else rig, "port": port if rig != KEEP else "",
                 "baud": self.tbl.cellWidget(r, 3).currentText() if rig != KEEP else "",
                 "stop": self.tbl.cellWidget(r, 4).currentText() if rig != KEEP else "",
                 "loc": self.tbl.cellWidget(r, 5).text().strip().upper()[:2] + self.tbl.cellWidget(r, 5).text().strip()[2:4]
                 + self.tbl.cellWidget(r, 5).text().strip()[4:].lower()}
            if any(p.values()):
                prof[call] = p
        s = self.win.settings
        s.setValue("mycalls", json.dumps(calls))
        save(s, prof)
        cur = (s.value("mycall", "") or "").upper()
        if cur not in calls and calls:
            s.setValue("mycall", calls[0])
        self.win.logdock.fill_mycalls()
        super().accept()
