"""Carnet de trafic : base SQLite, recherche HamQTH, import/export ADIF."""
import datetime
import os
import sqlite3
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, adif

FIELDS = ["call", "qso_date", "time_on", "freq", "band", "mode", "submode", "rst_sent", "rst_rcvd",
          "name", "qth", "gridsquare", "sig", "sig_info", "my_sig", "my_sig_info", "comment",
          "tx_pwr", "my_gridsquare", "station_callsign", "operator", "country"]

BAND_EDGES = [("2200m", 0.1357, 0.1378), ("630m", 0.472, 0.479), ("160m", 1.8, 2.0), ("80m", 3.5, 4.0),
              ("60m", 5.06, 5.45), ("40m", 7.0, 7.3), ("30m", 10.1, 10.15), ("20m", 14.0, 14.35),
              ("17m", 18.068, 18.168), ("15m", 21.0, 21.45), ("12m", 24.89, 24.99), ("10m", 28.0, 29.7),
              ("6m", 50.0, 54.0), ("4m", 70.0, 71.0), ("2m", 144.0, 148.0), ("70cm", 420.0, 450.0),
              ("23cm", 1240.0, 1300.0)]


def band_of_mhz(mhz):
    try:
        f = float(mhz)
    except (TypeError, ValueError):
        return ""
    return next((b for b, lo, hi in BAND_EDGES if lo <= f <= hi), "")


def data_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot")
    os.makedirs(d, exist_ok=True)
    return d


class Log(QObject):
    changed = Signal()

    def __init__(self, path=None):
        super().__init__()
        self.path = path or os.path.join(data_dir(), "carnet.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.Lock()
        cols = ", ".join(f"{f} TEXT" for f in FIELDS)
        with self.lock:
            self.db.execute(f"CREATE TABLE IF NOT EXISTS qso (id INTEGER PRIMARY KEY, {cols})")
            have = {r[1] for r in self.db.execute("PRAGMA table_info(qso)")}
            for f in FIELDS:
                if f not in have:
                    self.db.execute(f"ALTER TABLE qso ADD COLUMN {f} TEXT")
            self.db.execute("CREATE INDEX IF NOT EXISTS qso_call ON qso(call)")
            self.db.commit()

    def add(self, rec, notify=True):
        rec = {k: (str(v).strip() if v is not None else "") for k, v in rec.items() if k in FIELDS}
        rec["call"] = rec.get("call", "").upper()
        if not rec.get("band") and rec.get("freq"):
            rec["band"] = band_of_mhz(rec["freq"])
        keys = list(rec)
        with self.lock:
            self.db.execute(f"INSERT INTO qso ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                            [rec[k] for k in keys])
            self.db.commit()
        if notify:
            self.changed.emit()

    def delete(self, qid):
        with self.lock:
            self.db.execute("DELETE FROM qso WHERE id = ?", (qid,))
            self.db.commit()
        self.changed.emit()

    def is_dupe(self, rec, minutes=3):
        """Même indicatif, même bande, même mode, à quelques minutes près."""
        try:
            t = datetime.datetime.strptime(rec["qso_date"] + rec["time_on"][:4], "%Y%m%d%H%M")
        except (KeyError, ValueError):
            return False
        for r in self.query("call = ? AND qso_date = ? AND band = ?",
                            (rec.get("call", "").upper(), rec["qso_date"], rec.get("band", ""))):
            try:
                t2 = datetime.datetime.strptime(r["qso_date"] + r["time_on"][:4], "%Y%m%d%H%M")
            except ValueError:
                continue
            if abs((t - t2).total_seconds()) <= minutes * 60 and r.get("mode") == rec.get("mode"):
                return True
        return False

    def query(self, where="1", args=(), limit=None):
        sql = f"SELECT id, {', '.join(FIELDS)} FROM qso WHERE {where} ORDER BY qso_date DESC, time_on DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [dict(zip(["id"] + FIELDS, r)) for r in rows]

    def worked(self, call):
        """Bandes et modes déjà contactés avec cet indicatif."""
        rows = self.query("call = ?", (call.upper(),))
        return rows

    def count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM qso").fetchone()[0]

    def export_records(self, rows):
        out = []
        for r in rows:
            out.append({k: r.get(k) for k in FIELDS if r.get(k)})
        return out


class HamQTH(QObject):
    """Recherche d'indicatif sur HamQTH.com (compte gratuit nécessaire)."""
    result = Signal(str, object)          # indicatif, dict ou message d'erreur (str)

    URL = "https://www.hamqth.com/xml.php"
    NS = "{https://www.hamqth.com}"

    def __init__(self):
        super().__init__()
        self.user = self.password = ""
        self.session = None
        self.cache = {}

    def lookup(self, call):
        call = call.strip().upper()
        if not call:
            return
        if call in self.cache:
            self.result.emit(call, self.cache[call])
            return
        threading.Thread(target=self._lookup, args=(call,), daemon=True).start()

    def _get(self, params):
        url = self.URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": f"CATPilot/{__version__}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return ET.fromstring(r.read())

    def _text(self, root, tag):
        el = root.find(f".//{self.NS}{tag}")
        if el is None:
            el = root.find(f".//{tag}")
        return (el.text or "").strip() if el is not None else ""

    def _lookup(self, call):
        if not self.user or not self.password:
            self.result.emit(call, "Indiquez votre compte HamQTH (menu Carnet > Réglages)")
            return
        try:
            for attempt in range(2):
                if not self.session:
                    root = self._get({"u": self.user, "p": self.password})
                    self.session = self._text(root, "session_id") or None
                    if not self.session:
                        self.result.emit(call, "HamQTH : " + (self._text(root, "error") or "connexion refusée"))
                        return
                root = self._get({"id": self.session, "callsign": call, "prg": "CATPilot"})
                err = self._text(root, "error")
                if err and "session" in err.lower() and attempt == 0:
                    self.session = None
                    continue
                if err:
                    self.result.emit(call, f"HamQTH : {err}")
                    return
                info = {k: self._text(root, k) for k in
                        ("nick", "adr_name", "qth", "country", "grid", "itu", "cq", "lat", "lon")}
                info["name"] = info["nick"] or info["adr_name"].split(" ")[0]
                self.cache[call] = info
                self.result.emit(call, info)
                return
        except Exception as e:
            self.result.emit(call, f"HamQTH injoignable : {e}")


class LogDock(QDockWidget):
    def __init__(self, win, log):
        super().__init__("Carnet de trafic", win)
        self.win, self.ctrl, self.log = win, win.ctrl, log
        self.setObjectName("logdock")
        self.hamqth = HamQTH()
        s = win.settings
        self.hamqth.user = s.value("hamqth_user", "")
        self.hamqth.password = s.value("hamqth_pass", "")
        self.hamqth.result.connect(self.on_lookup)
        self.t_start = None

        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        self.ed_call = QLineEdit()
        self.ed_call.setPlaceholderText("Indicatif, puis Entrée")
        self.ed_call.returnPressed.connect(self.on_call_entered)
        self.ed_call.textEdited.connect(self.on_call_edit)
        self.ed_name, self.ed_qth, self.ed_grid = QLineEdit(), QLineEdit(), QLineEdit()
        self.ed_sent, self.ed_rcvd = QLineEdit("59"), QLineEdit("59")
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(adif.LOG_MODES)
        self.cb_mode.currentTextChanged.connect(self.on_mode)
        self.ed_ref = QLineEdit()
        self.ed_ref.setPlaceholderText("ex. FR-0123 ou F/AM-123")
        self.ed_myref = QLineEdit(s.value("log_myref", ""))
        self.ed_myref.setPlaceholderText("votre référence en activation")
        self.ed_comment = QLineEdit()
        self.lb_freq = QLabel("—")
        self.lb_freq.setObjectName("value")
        rows = [("Indicatif", self.ed_call), ("Nom", self.ed_name), ("QTH", self.ed_qth),
                ("Locator", self.ed_grid), ("RST envoyé", self.ed_sent), ("RST reçu", self.ed_rcvd),
                ("Mode", self.cb_mode), ("Fréquence", self.lb_freq),
                ("Sa réf. POTA/SOTA", self.ed_ref), ("Ma réf. (activation)", self.ed_myref),
                ("Commentaire", self.ed_comment)]
        for i, (label, wd) in enumerate(rows):
            g.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            g.addWidget(wd, i // 2, (i % 2) * 2 + 1)
        v.addLayout(g)
        self.lb_info = QLabel("")
        self.lb_info.setObjectName("value")
        self.lb_info.setWordWrap(True)
        v.addWidget(self.lb_info)
        h = QHBoxLayout()
        b = QPushButton("Enregistrer le QSO")
        b.setToolTip("Raccourci : Entrée dans le champ Commentaire, ou Ctrl+L")
        b.clicked.connect(self.save_qso)
        self.ed_comment.returnPressed.connect(self.save_qso)
        h.addWidget(b)
        b = QPushButton("Effacer")
        b.clicked.connect(self.clear_form)
        h.addWidget(b)
        v.addLayout(h)

        h = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Rechercher un indicatif dans le carnet")
        self.ed_search.textChanged.connect(self.refresh)
        h.addWidget(self.ed_search, 1)
        self.lb_count = QLabel("")
        self.lb_count.setObjectName("hint")
        h.addWidget(self.lb_count)
        v.addLayout(h)
        self.tbl = QTableWidget(0, 9)
        self.tbl.setHorizontalHeaderLabels(["Date", "UTC", "Indicatif", "Bande", "Mode", "Env.", "Reçu",
                                            "Nom", "Réf."])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        for label, slot in (("Supprimer", self.delete_selected), ("Importer ADIF", self.import_adif),
                            ("Exporter ADIF", self.export_adif), ("Exporter une activation", self.export_activation)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.setWidget(w)
        self.setMinimumWidth(520)
        self.log.changed.connect(self.refresh)
        self.ctrl.state_changed.connect(self.on_state)
        self._last = None
        self.refresh()

    # --- formulaire --------------------------------------------------------------------
    def on_state(self, st):
        self._last = st
        if self.isVisible():
            self.lb_freq.setText(f"{st.freq / 1e6:.4f} MHz".replace(".", ","))

    def suggest_mode(self, rig_mode, freq):
        if rig_mode in ("USB", "LSB"):
            return "SSB"
        if rig_mode in ("CW", "CWR"):
            return "CW"
        if rig_mode in ("RTTY", "RTTYR"):
            return "RTTY"
        if rig_mode in ("PKTUSB", "PKTLSB"):
            return "FT4" if any(abs(freq - f) < 3000 for f in
                                (7047500, 10140000, 14080000, 18104000, 21140000, 28180000)) else "FT8"
        return {"AM": "AM", "FM": "FM", "PKTFM": "FM", "C4FM": "C4FM"}.get(rig_mode, "SSB")

    def on_call_edit(self, txt):
        if self.t_start is None and txt.strip():
            self.t_start = datetime.datetime.now(datetime.timezone.utc)
            if self._last:
                self.cb_mode.setCurrentText(self.suggest_mode(self._last.mode, self._last.freq))
        self.ed_call.setText(txt.upper())
        prev = self.log.worked(txt.strip()) if len(txt.strip()) >= 3 else []
        if prev:
            bands = sorted({f"{r['band']} {r['mode']}" for r in prev})
            self.lb_info.setText(f"Déjà contacté {len(prev)} fois : " + ", ".join(bands[:8]))
        else:
            self.lb_info.setText("Nouvel indicatif" if len(txt.strip()) >= 3 else "")

    def on_call_entered(self):
        call = self.ed_call.text().strip().upper()
        if call:
            self.hamqth.lookup(call)
            self.ed_name.setFocus()

    def on_lookup(self, call, info):
        if call != self.ed_call.text().strip().upper():
            return
        if isinstance(info, str):
            self.lb_info.setText(info)
            return
        for ed, key in ((self.ed_name, "name"), (self.ed_qth, "qth"), (self.ed_grid, "grid")):
            if not ed.text() and info.get(key):
                ed.setText(info[key])
        extra = " — ".join(x for x in (info.get("country"), info.get("qth")) if x)
        pos = getattr(self.win, "station", None)
        if pos and info.get("grid"):
            from .geo import distance_bearing, from_locator
            try:
                d, b = distance_bearing(*pos, *from_locator(info["grid"][:6]))
                extra += f" — {d:.0f} km, cap {b:.0f}°"
            except ValueError:
                pass
        self.lb_info.setText(f"{call} : {extra}" if extra else f"{call} trouvé")

    def on_mode(self, mode):
        self.ed_sent.setText(adif.default_rst(mode))
        self.ed_rcvd.setText(adif.default_rst(mode))

    def prefill(self, call, ref="", mode=None):
        """Appelé depuis un spot : prépare le QSO."""
        self.clear_form()
        self.ed_call.setText(call.upper())
        self.on_call_edit(call)
        if ref:
            self.ed_ref.setText(ref)
        if mode:
            self.cb_mode.setCurrentText(mode)

    def clear_form(self):
        for ed in (self.ed_call, self.ed_name, self.ed_qth, self.ed_grid, self.ed_ref, self.ed_comment):
            ed.clear()
        self.lb_info.clear()
        self.t_start = None
        self.on_mode(self.cb_mode.currentText())
        self.ed_call.setFocus()

    def save_qso(self):
        call = self.ed_call.text().strip().upper()
        if not call:
            self.lb_info.setText("Indicatif manquant")
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        t = self.t_start or now
        st = self._last
        mode, sub = adif.ADIF_MODES.get(self.cb_mode.currentText(), (self.cb_mode.currentText(), ""))
        ref, myref = self.ed_ref.text().strip().upper(), self.ed_myref.text().strip().upper()
        kind = lambda r: "SOTA" if "/" in r else "POTA"
        rec = {"call": call, "qso_date": t.strftime("%Y%m%d"), "time_on": t.strftime("%H%M%S"),
               "freq": f"{st.freq / 1e6:.6f}" if st and st.freq else "", "mode": mode, "submode": sub,
               "rst_sent": self.ed_sent.text(), "rst_rcvd": self.ed_rcvd.text(),
               "name": self.ed_name.text(), "qth": self.ed_qth.text(), "gridsquare": self.ed_grid.text(),
               "comment": self.ed_comment.text(),
               "tx_pwr": str(st.p.get("pwr", "")) if st else "",
               "station_callsign": self.win.settings.value("mycall", "").upper(),
               "my_gridsquare": self.win.b_loc.text().split()[0] if getattr(self.win, "station", None) else ""}
        if ref:
            rec["sig"], rec["sig_info"] = kind(ref), ref
        if myref:
            rec["my_sig"], rec["my_sig_info"] = kind(myref), myref
        self.log.add(rec)
        self.win.statusBar().showMessage(f"QSO avec {call} enregistré")
        self.clear_form()

    # --- tableau -----------------------------------------------------------------------------
    def refresh(self):
        q = self.ed_search.text().strip().upper()
        rows = self.log.query("call LIKE ?", (f"%{q}%",), limit=500) if q else self.log.query(limit=300)
        self.rows = rows
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            d = r["qso_date"] or ""
            vals = [f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else d, (r["time_on"] or "")[:4],
                    r["call"], r["band"], r["submode"] or r["mode"], r["rst_sent"], r["rst_rcvd"],
                    r["name"], r["sig_info"] or r["my_sig_info"]]
            for c, val in enumerate(vals):
                self.tbl.setItem(i, c, QTableWidgetItem(val or ""))
        self.lb_count.setText(f"{self.log.count()} QSO")

    def delete_selected(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()})
        if not rows:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer {len(rows)} QSO du carnet ?") != QMessageBox.Yes:
            return
        for r in rows:
            self.log.delete(self.rows[r]["id"])

    def import_adif(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer un fichier ADIF", "", "ADIF (*.adi *.adif)")
        if not path:
            return
        with open(path, encoding="utf-8", errors="replace") as f:
            recs = adif.parse(f.read())
        n = dup = 0
        for r in recs:
            if not r.get("call"):
                continue
            if not r.get("band"):
                r["band"] = band_of_mhz(r.get("freq"))
            if self.log.is_dupe(r):
                dup += 1
                continue
            self.log.add(r, notify=False)
            n += 1
        self.log.changed.emit()
        QMessageBox.information(self, "Import ADIF", f"{n} QSO importés, {dup} doublons ignorés.")

    def _save_adif(self, rows, default):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en ADIF", os.path.join(data_dir(), default),
                                              "ADIF (*.adi)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(adif.write(self.log.export_records(rows), "CAT Pilot", __version__))
        self.win.statusBar().showMessage(f"{len(rows)} QSO exportés dans {path}")

    def export_adif(self):
        self._save_adif(self.log.query(), "carnet_catpilot.adi")

    def export_activation(self):
        """Export au format attendu par POTA/SOTA : une référence, une date."""
        myref = self.ed_myref.text().strip().upper()
        if not myref:
            QMessageBox.information(self, "Activation", "Indiquez votre référence dans « Ma réf. (activation) ».")
            return
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        rows = self.log.query("my_sig_info = ? AND qso_date = ?", (myref, today))
        if not rows:
            QMessageBox.information(self, "Activation", f"Aucun QSO aujourd'hui (UTC) depuis {myref}.")
            return
        call = (self.win.settings.value("mycall", "") or "INDICATIF").upper().replace("/", "-")
        self._save_adif(rows, f"{call}@{myref.replace('/', '-')}-{today}.adi")

    def save_settings(self, s):
        s.setValue("log_myref", self.ed_myref.text())


class HamQTHDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("Réglages du carnet")
        f = QFormLayout(self)
        s = win.settings
        self.ed_call = QLineEdit(s.value("mycall", ""))
        self.ed_user = QLineEdit(s.value("hamqth_user", ""))
        self.ed_pass = QLineEdit(s.value("hamqth_pass", ""))
        self.ed_pass.setEchoMode(QLineEdit.Password)
        f.addRow("Mon indicatif", self.ed_call)
        f.addRow("Compte HamQTH", self.ed_user)
        f.addRow("Mot de passe HamQTH", self.ed_pass)
        t = QLabel("Compte gratuit sur hamqth.com. Le mot de passe est enregistré sur ce PC.")
        t.setObjectName("hint")
        t.setWordWrap(True)
        f.addRow(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
