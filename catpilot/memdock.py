"""Panneau « Mémoires et scan » : lecture, édition, import/export CSV,
écriture dans le poste avec sauvegarde automatique, et scan logiciel."""
import csv
import datetime
import os
import time
import unicodedata

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDockWidget, QFileDialog, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Libellé affiché <-> code de mode du FT-991A
MEM_MODES = [("USB", "2"), ("LSB", "1"), ("CW", "3"), ("CW-R", "7"), ("AM", "5"), ("AM-N", "D"),
             ("FM", "4"), ("FM-N", "B"), ("C4FM", "E"), ("DATA-U", "C"), ("DATA-L", "8"),
             ("DATA-FM", "A"), ("RTTY-L", "6"), ("RTTY-U", "9")]
LABEL_TO_CODE = dict(MEM_MODES)
CODE_TO_LABEL = {c: l for l, c in MEM_MODES}
SHIFTS = ["", "+", "−"]
TONES = ["", "TSQ", "Tone", "DCS"]
COLS = ["Canal", "Nom", "Fréquence", "Mode", "Relais", "Tonalité"]
S_THRESHOLDS = [("S1", 12), ("S3", 40), ("S5", 65), ("S7", 95), ("S9", 130), ("S9+20", 172)]
SCAN_STEPS = [("12,5 kHz", 12500), ("25 kHz", 25000), ("5 kHz", 5000), ("1 kHz", 1000), ("100 Hz", 100)]
MODIFIED = QColor("#3a2f00")


def backup_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot", "sauvegardes")
    os.makedirs(d, exist_ok=True)
    return d


def clean_tag(txt):
    """Nom de mémoire : 12 caractères ASCII maximum (le poste n'affiche pas les accents)."""
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return txt[:12]


def parse_freq(txt):
    t = txt.strip().replace(" ", "")
    if not t:
        raise ValueError("fréquence vide")
    if "," in t and "." in t:             # format affiché : 145,600.000
        return int(t.replace(",", "").replace(".", ""))
    val = float(t.replace(",", "."))
    hz = val * 1e6 if val < 1000 else val * 1e3 if val < 1e6 else val
    hz = int(round(hz))
    if not 30_000 <= hz <= 470_000_000:
        raise ValueError(f"fréquence hors limites : {txt}")
    return hz


def fmt_freq(hz):
    mhz, rest = divmod(int(hz), 1_000_000)
    return f"{mhz},{rest // 1000:03d}.{rest % 1000:03d}"


def mem_label(m):
    if m.get("code"):
        return CODE_TO_LABEL.get(m["code"], "FM")
    raw = m.get("raw", "")
    if len(raw) > 19 and raw[19] in CODE_TO_LABEL:
        return CODE_TO_LABEL[raw[19]]
    return m.get("mode_label") or {"USB": "USB", "LSB": "LSB", "CW": "CW", "CWR": "CW-R", "AM": "AM",
                                   "FM": "FM", "PKTUSB": "DATA-U", "PKTLSB": "DATA-L", "PKTFM": "DATA-FM",
                                   "RTTY": "RTTY-L", "RTTYR": "RTTY-U", "C4FM": "C4FM"}.get(m.get("mode"), "FM")


class ComboDelegate(QStyledItemDelegate):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items

    def createEditor(self, parent, _opt, _idx):
        c = QComboBox(parent)
        c.addItems(self.items)
        c.activated.connect(lambda: self.commitData.emit(c))
        return c

    def setEditorData(self, editor, idx):
        i = editor.findText(idx.data() or "")
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, idx):
        model.setData(idx, editor.currentText())


class MemoryDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Mémoires et scan", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("memdock")
        self.memories = []        # canaux tels que lus ou édités
        self.read_copy = []       # copie du dernier état lu sur le poste
        self.modified = set()
        self._filling = False
        self.scanning = False

        w = QWidget()
        v = QVBoxLayout(w)
        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                 | QAbstractItemView.AnyKeyPressed)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        self.tbl.setItemDelegateForColumn(3, ComboDelegate([l for l, _c in MEM_MODES], self.tbl))
        self.tbl.setItemDelegateForColumn(4, ComboDelegate(SHIFTS, self.tbl))
        self.tbl.setItemDelegateForColumn(5, ComboDelegate(TONES, self.tbl))
        self.tbl.itemChanged.connect(self.on_item_changed)
        self.tbl.cellDoubleClicked.connect(self.on_double_click)
        self.tbl.setToolTip("Double-clic sur le numéro : rappeler la mémoire.\n"
                            "Double-clic sur une autre colonne : modifier.")
        v.addWidget(self.tbl, 1)

        g = QGridLayout()
        self.buttons = []

        def btn(label, slot, r, c, tip=""):
            b = QPushButton(label)
            b.clicked.connect(slot)
            b.setToolTip(tip)
            g.addWidget(b, r, c)
            self.buttons.append(b)
            return b

        btn("Lire les mémoires", lambda: self.ctrl.job("read_memories"), 0, 0)
        btn("Rappeler", lambda: self.recall(self.tbl.currentRow()), 0, 1)
        btn("Ajouter un canal", self.add_channel, 0, 2, "Nouveau canal libre avec la fréquence et le mode actuels")
        self.b_write = btn("Écrire dans le poste", self.write_to_radio, 1, 0,
                           "Envoie au poste les lignes modifiées (en jaune)")
        btn("Importer CSV", self.import_csv, 1, 1)
        btn("Exporter CSV", self.export_csv, 1, 2)
        v.addLayout(g)
        self.lb_info = QLabel("")
        self.lb_info.setObjectName("hint")
        v.addWidget(self.lb_info)

        # --- scan ---
        t = QLabel("Scan")
        t.setObjectName("ptitle")
        v.addWidget(t)
        sg = QGridLayout()
        self.cb_scan = QComboBox()
        self.cb_scan.addItems(["Mémoires du tableau", "Plage de fréquences"])
        self.ed_from = QLineEdit("145.200")
        self.ed_to = QLineEdit("145.800")
        self.cb_sstep = QComboBox()
        for label, val in SCAN_STEPS:
            self.cb_sstep.addItem(label, val)
        self.cb_thr = QComboBox()
        for label, raw in S_THRESHOLDS:
            self.cb_thr.addItem(label, raw)
        self.cb_thr.setCurrentIndex(1)
        self.sp_hold = QSpinBox()
        self.sp_hold.setRange(0, 60)
        self.sp_hold.setValue(5)
        self.sp_hold.setSuffix(" s")
        self.sp_hold.setToolTip("Temps d'écoute sur un signal avant de repartir (0 = arrêt sur le signal)")
        self.b_scan = QPushButton("Démarrer le scan")
        self.b_scan.setCheckable(True)
        self.b_scan.toggled.connect(self.toggle_scan)
        sg.addWidget(self.cb_scan, 0, 0, 1, 2)
        sg.addWidget(QLabel("De (MHz)"), 1, 0)
        sg.addWidget(self.ed_from, 1, 1)
        sg.addWidget(QLabel("À (MHz)"), 2, 0)
        sg.addWidget(self.ed_to, 2, 1)
        sg.addWidget(QLabel("Pas"), 3, 0)
        sg.addWidget(self.cb_sstep, 3, 1)
        sg.addWidget(QLabel("Seuil"), 1, 2)
        sg.addWidget(self.cb_thr, 1, 3)
        sg.addWidget(QLabel("Écoute"), 2, 2)
        sg.addWidget(self.sp_hold, 2, 3)
        sg.addWidget(self.b_scan, 3, 2, 1, 2)
        v.addLayout(sg)
        self.lb_scan = QLabel("")
        self.lb_scan.setObjectName("value")
        v.addWidget(self.lb_scan)

        self.setWidget(w)
        self.setMinimumWidth(500)
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.scan_tick)
        self.scan_timer.start(100)
        self.ctrl.job_done.connect(self.on_job)
        self._update_info()

    # --- tableau ------------------------------------------------------------------
    def set_memories(self, mems, from_radio=True):
        for m in mems:
            m.setdefault("code", LABEL_TO_CODE.get(mem_label(m), "4"))
        self.memories = sorted(mems, key=lambda m: m["ch"])
        if from_radio:
            self.read_copy = [dict(m) for m in self.memories]
            self.modified.clear()
        self.refresh_table()

    def refresh_table(self):
        self._filling = True
        self.tbl.setRowCount(len(self.memories))
        for r, m in enumerate(self.memories):
            cells = [f"{m['ch']:03d}", m.get("tag", ""), fmt_freq(m["freq"]), mem_label(m),
                     SHIFTS[m.get("shift", 0)] if m.get("shift", 0) in (0, 1, 2) else "",
                     TONES[m.get("ctcss", 0)] if m.get("ctcss", 0) in (0, 1, 2, 3) else ""]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if c == 1 else Qt.AlignCenter)
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if m["ch"] in self.modified:
                    it.setBackground(MODIFIED)
                self.tbl.setItem(r, c, it)
        self._filling = False
        self._update_info()

    def _update_info(self):
        n = len(self.modified)
        self.lb_info.setText(f"{len(self.memories)} canaux" +
                             (f" — {n} modifié(s), à écrire dans le poste" if n else ""))

    def on_item_changed(self, it):
        if self._filling:
            return
        r, c = it.row(), it.column()
        m = self.memories[r]
        txt = it.text()
        try:
            if c == 1:
                m["tag"] = clean_tag(txt)
            elif c == 2:
                m["freq"] = parse_freq(txt)
            elif c == 3:
                m["code"] = LABEL_TO_CODE.get(txt, m.get("code", "4"))
            elif c == 4:
                m["shift"] = SHIFTS.index(txt) if txt in SHIFTS else 0
            elif c == 5:
                m["ctcss"] = TONES.index(txt) if txt in TONES else 0
        except ValueError as e:
            QMessageBox.warning(self, "Valeur refusée", str(e))
        self.modified.add(m["ch"])
        self.refresh_table()

    def on_double_click(self, row, col):
        if col == 0:
            self.recall(row)

    def recall(self, row):
        if 0 <= row < len(self.memories):
            self.ctrl.action("mem_recall", self.memories[row]["ch"])

    def add_channel(self):
        used = {m["ch"] for m in self.memories}
        free = next((c for c in range(1, 100) if c not in used), None)
        if free is None:
            QMessageBox.information(self, "Plus de place", "Les canaux 001 à 099 sont tous occupés.")
            return
        st = self.ctrl.snapshot()
        code = {"USB": "2", "LSB": "1", "CW": "3", "CWR": "7", "AM": "5", "FM": "4", "PKTUSB": "C",
                "PKTLSB": "8", "PKTFM": "A", "RTTY": "6", "RTTYR": "9", "C4FM": "E"}.get(st.mode, "4")
        self.memories.append({"ch": free, "freq": st.freq or 145500000, "code": code, "tag": "",
                              "shift": 0, "ctcss": 0, "clar": 0})
        self.memories.sort(key=lambda m: m["ch"])
        self.modified.add(free)
        self.refresh_table()

    # --- import / export --------------------------------------------------------------
    def export_csv(self, path=None):
        if not self.memories:
            QMessageBox.information(self, "Aucune mémoire", "Lisez d'abord les mémoires du poste.")
            return
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Exporter les mémoires",
                                                  "memoires_ft991a.csv", "CSV (*.csv)")
            if not path:
                return
        self._write_csv(path, self.memories)
        self.win.statusBar().showMessage(f"Mémoires exportées dans {path}")

    @staticmethod
    def _write_csv(path, mems):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Canal", "Nom", "Fréquence (MHz)", "Mode", "Relais", "Tonalité"])
            for m in mems:
                w.writerow([m["ch"], m.get("tag", ""), f"{m['freq'] / 1e6:.6f}", mem_label(m),
                            SHIFTS[m.get("shift", 0)] if m.get("shift", 0) in (0, 1, 2) else "",
                            TONES[m.get("ctcss", 0)] if m.get("ctcss", 0) in (0, 1, 2, 3) else ""])

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer des mémoires", "", "CSV (*.csv *.txt)")
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                sample = f.read(2048)
                f.seek(0)
                dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
                rows = list(csv.reader(f, dialect))
        except Exception as e:
            QMessageBox.warning(self, "Import impossible", f"Fichier illisible :\n{e}")
            return
        by_ch = {m["ch"]: m for m in self.memories}
        n, errors = 0, []
        for i, row in enumerate(rows, 1):
            if not row or not row[0].strip().isdigit():
                continue                     # en-tête ou ligne vide
            try:
                ch = int(row[0])
                if not 1 <= ch <= 117:
                    raise ValueError(f"canal {ch} hors limites (1 à 117)")
                m = by_ch.get(ch, {"ch": ch, "clar": 0})
                m["tag"] = clean_tag(row[1] if len(row) > 1 else "")
                m["freq"] = parse_freq(row[2])
                mode = (row[3].strip().upper() if len(row) > 3 else "FM").replace("CWR", "CW-R")
                m["code"] = next((c for l, c in MEM_MODES if l.upper() == mode), "4")
                sh = row[4].strip() if len(row) > 4 else ""
                m["shift"] = {"": 0, "0": 0, "+": 1, "1": 1, "-": 2, "−": 2, "2": 2}.get(sh, 0)
                tn = row[5].strip().upper() if len(row) > 5 else ""
                m["ctcss"] = {"": 0, "0": 0, "TSQ": 1, "1": 1, "TONE": 2, "2": 2, "DCS": 3, "3": 3}.get(tn, 0)
                by_ch[ch] = m
                self.modified.add(ch)
                n += 1
            except (ValueError, IndexError) as e:
                errors.append(f"ligne {i} : {e}")
        self.memories = sorted(by_ch.values(), key=lambda m: m["ch"])
        self.refresh_table()
        msg = f"{n} canaux importés. Ils sont en jaune : cliquez sur « Écrire dans le poste » pour les envoyer."
        if errors:
            msg += "\n\nLignes ignorées :\n" + "\n".join(errors[:15])
        QMessageBox.information(self, "Import terminé", msg)

    # --- écriture dans le poste ------------------------------------------------------
    def write_to_radio(self):
        if not self.ctrl.connected:
            return
        if not self.read_copy:
            QMessageBox.information(self, "Lecture nécessaire",
                                    "Lisez d'abord les mémoires du poste : elles servent de modèle "
                                    "pour l'écriture et sont sauvegardées avant toute modification.")
            return
        todo = [m for m in self.memories if m["ch"] in self.modified]
        if not todo:
            QMessageBox.information(self, "Rien à écrire", "Aucune ligne modifiée.")
            return
        listing = "\n".join(f"{m['ch']:03d}  {m.get('tag', ''):<12}  {fmt_freq(m['freq'])}  {mem_label(m)}"
                            for m in todo[:12])
        if len(todo) > 12:
            listing += f"\n… et {len(todo) - 12} autres"
        if QMessageBox.question(self, "Écrire dans le poste",
                                f"Écrire {len(todo)} canal(aux) dans le FT-991A ?\n\n{listing}\n\n"
                                "Les mémoires actuelles du poste seront d'abord sauvegardées.") \
                != QMessageBox.Yes:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(backup_dir(), f"memoires_avant_ecriture_{stamp}.csv")
        self._write_csv(path, self.read_copy)
        template = self.read_copy[0].get("raw", "")
        self.ctrl.job("write_memories", [dict(m) for m in todo], template)
        self.win.statusBar().showMessage(f"Sauvegarde faite dans {path} — écriture en cours…")

    def on_job(self, name, res):
        if isinstance(res, Exception):
            if name in ("read_memories", "write_memories"):
                QMessageBox.warning(self, "Erreur", f"{name} : {res}")
            return
        if name == "read_memories":
            self.set_memories(res)
            self.win.statusBar().showMessage(f"{len(res)} mémoires lues sur le poste")
            self.show()
        elif name == "write_memories":
            bad = [ch for ch, ok in res if not ok]
            ok = len(res) - len(bad)
            msg = f"{ok} canal(aux) écrit(s) et vérifié(s)."
            if bad:
                msg += ("\n\nÉchec ou vérification impossible pour : "
                        + ", ".join(f"{c:03d}" for c in bad))
            QMessageBox.information(self, "Écriture terminée", msg)
            self.ctrl.job("read_memories")

    # --- scan ---------------------------------------------------------------------
    def toggle_scan(self, on):
        if on:
            if not self.ctrl.connected:
                self._stop_scan("Pas de poste connecté")
                return
            if self.cb_scan.currentIndex() == 0:
                if not self.memories:
                    self._stop_scan("Lisez d'abord les mémoires")
                    return
                self.scan_idx = -1
            else:
                try:
                    self.scan_from = parse_freq(self.ed_from.text())
                    self.scan_to = parse_freq(self.ed_to.text())
                except ValueError as e:
                    self._stop_scan(str(e))
                    return
                if self.scan_to < self.scan_from:
                    self.scan_from, self.scan_to = self.scan_to, self.scan_from
                self.scan_f = self.scan_from - self.cb_sstep.currentData()
            self.scanning = True
            self.hold_until = 0
            self.b_scan.setText("Arrêter le scan")
            self.scan_next()
        else:
            self._stop_scan("Scan arrêté")

    def _stop_scan(self, msg):
        self.scanning = False
        self.b_scan.blockSignals(True)
        self.b_scan.setChecked(False)
        self.b_scan.blockSignals(False)
        self.b_scan.setText("Démarrer le scan")
        self.lb_scan.setText(msg)

    def scan_next(self):
        if self.cb_scan.currentIndex() == 0:
            self.scan_idx = (self.scan_idx + 1) % len(self.memories)
            m = self.memories[self.scan_idx]
            self.ctrl.action("mem_recall", m["ch"])
            self.lb_scan.setText(f"Scan : {m['ch']:03d} {m.get('tag', '')}  {fmt_freq(m['freq'])}")
        else:
            self.scan_f += self.cb_sstep.currentData()
            if self.scan_f > self.scan_to:
                self.scan_f = self.scan_from
            self.ctrl.set_freq(self.scan_f)
            self.lb_scan.setText(f"Scan : {fmt_freq(self.scan_f)}")
        self.tuned_at = time.monotonic()

    def scan_tick(self):
        if not self.scanning:
            return
        st, now = self.win._last, time.monotonic()
        if not self.ctrl.connected or (st and st.ptt):
            self._stop_scan("Scan arrêté (émission ou liaison coupée)")
            return
        if self.hold_until:
            if now < self.hold_until:
                return
            self.hold_until = 0
            self.scan_next()
            return
        # attendre que le S-mètre ait été relu après le changement de fréquence
        if now - self.tuned_at < 0.45 or self.win._state_time < self.tuned_at + 0.3 or not st:
            return
        if st.smeter * 255 >= self.cb_thr.currentData():
            hold = self.sp_hold.value()
            where = self.lb_scan.text().replace("Scan : ", "")
            if hold == 0:
                self._stop_scan(f"Signal trouvé : {where} ({st.s_text})")
            else:
                self.hold_until = now + hold
                self.lb_scan.setText(f"Écoute : {where} ({st.s_text})")
            return
        self.scan_next()
