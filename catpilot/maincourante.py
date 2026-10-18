"""Main courante (ADRASEC, sécurité civile) : journal horodaté des messages d'une opération.

Chaque opération ou exercice a sa propre liste, numérotée. Saisie rapide (l'heure se fige
au premier caractère tapé, le moyen radio vient du poste), recherche, export PDF et CSV.
Base : Documents/CATPilot/main_courante.sqlite
"""
import csv
import datetime
import html
import json
import os
import sqlite3
import threading

from PySide6.QtCore import QMarginsF, Qt, QTimer
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDockWidget, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .logbook import data_dir

COLS = ["n", "ts", "utc", "sens", "type", "de", "a", "moyen", "prio", "message", "suite", "operateur"]
HEAD = ["N°", "Date et heure", "UTC", "Sens", "Type", "De", "À", "Moyen", "Priorité", "Message", "Suite donnée",
        "Opérateur"]
TYPES = ["Message", "Information", "Ordre", "Demande", "Compte rendu", "Point de situation", "Bilan", "Alerte",
         "Contrôle radio", "Accusé de réception", "Relève", "Autre"]
CORRESP = ["PC ADRASEC 06", "COD 06", "CODIS 06", "SDIS 06", "Préfecture 06", "SAMU 06", "Gendarmerie", "Police",
           "Mairie", "PC opérationnel", "Station mobile", "Station fixe", "Toutes stations"]
MOYENS = ["VHF", "UHF", "HF", "Relais", "Téléphone", "SMS", "Courriel", "Message porté"]
TEMPLATE_TYPE = {"Arrivée sur zone": "Compte rendu", "Contrôle radio": "Contrôle radio", "Position": "Information",
                 "Point de situation": "Point de situation", "Bilan radio": "Bilan", "Demande de moyens": "Demande",
                 "Relève": "Relève", "Fin de mission": "Compte rendu"}


class HistCombo(QComboBox):
    """Liste modifiable qui retient les saisies (les plus récentes en tête) en plus des valeurs habituelles."""

    def __init__(self, settings, key, defaults, placeholder="", upper=False):
        super().__init__()
        self.s, self.key, self.defaults, self.upper = settings, key, list(defaults), upper
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.lineEdit().setPlaceholderText(placeholder)
        from PySide6.QtWidgets import QCompleter
        self.setMaxVisibleItems(20)
        try:
            self.hist = json.loads(settings.value(key, "[]") or "[]")
        except ValueError:
            self.hist = []
        self._fill()
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)

    def _fill(self, extra=()):
        cur = self.currentText()
        self.blockSignals(True)
        super().clear()
        seen = set()
        for v in list(extra) + self.hist + self.defaults:
            if v and v.upper() not in seen:
                seen.add(v.upper())
                self.addItem(v)
        self.setEditText(cur)
        self.blockSignals(False)

    def text(self):
        t = self.currentText().strip()
        return t.upper() if self.upper and not any(c.islower() for c in t[1:]) else t

    def setText(self, t):
        self.setEditText(t)

    def remember(self, extra=()):
        t = self.currentText().strip()
        if t:
            self.hist = [t] + [h for h in self.hist if h.upper() != t.upper()]
            del self.hist[60:]
            self.s.setValue(self.key, json.dumps(self.hist))
        self._fill(extra)

PRIOS = ["Routine", "Urgent", "Très urgent"]
SENS = ["Reçu", "Émis", "Info"]
PRIO_COLORS = {"Urgent": "#ff9800", "Très urgent": "#f44336"}
DEFAULT_TEMPLATES = [
    ("Arrivée sur zone", "Arrivée sur zone à {HEURE}. Position {LOC}. Station en place, écoute sur {MOYEN}."),
    ("Contrôle radio", "Contrôle radio : reçu 5 sur 5. Comment me recevez-vous ?"),
    ("Position", "Position de la station : locator {LOC} ({LAT}, {LON})."),
    ("Point de situation", "Point de situation à {HEURE} : RAS / préciser…\nMoyens engagés : …\nProchain point : …"),
    ("Bilan radio", "Bilan radio à {HEURE} : liaison avec … qualité …/5. Stations en écoute : …"),
    ("Demande de moyens", "Demande de moyens : …\nLieu : …\nMotif : …\nDélai souhaité : …"),
    ("Relève", "Relève de l'opérateur à {HEURE} : {OPERATEUR} remplacé par …"),
    ("Fin de mission", "Fin de mission à {HEURE}. Matériel replié, retour à la base."),
]


class Journal:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "main_courante.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS operation (id INTEGER PRIMARY KEY, nom TEXT, lieu TEXT, "
                            "responsable TEXT, debut TEXT, fin TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS message (id INTEGER PRIMARY KEY, op INTEGER, "
                            + ", ".join(f"{c} TEXT" for c in COLS) + ")")
            have = {r[1] for r in self.db.execute("PRAGMA table_info(message)")}
            for c in COLS:
                if c not in have:
                    self.db.execute(f"ALTER TABLE message ADD COLUMN {c} TEXT")
            self.db.commit()

    def operations(self):
        with self.lock:
            return self.db.execute("SELECT id, nom, lieu, responsable, debut, fin FROM operation "
                                   "ORDER BY id DESC").fetchall()

    def new_operation(self, nom, lieu="", responsable=""):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with self.lock:
            cur = self.db.execute("INSERT INTO operation (nom, lieu, responsable, debut) VALUES (?, ?, ?, ?)",
                                  (nom, lieu, responsable, now))
            self.db.commit()
            return cur.lastrowid

    def close_operation(self, op):
        with self.lock:
            self.db.execute("UPDATE operation SET fin = ? WHERE id = ?",
                            (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), op))
            self.db.commit()

    def operation(self, op):
        with self.lock:
            return self.db.execute("SELECT id, nom, lieu, responsable, debut, fin FROM operation WHERE id = ?",
                                   (op,)).fetchone()

    def messages(self, op, q=""):
        sql = f"SELECT id, {', '.join(COLS)} FROM message WHERE op = ?"
        args = [op]
        if q:
            sql += " AND (message LIKE ? OR de LIKE ? OR a LIKE ? OR suite LIKE ?)"
            args += [f"%{q}%"] * 4
        with self.lock:
            rows = self.db.execute(sql + " ORDER BY CAST(n AS INTEGER)", args).fetchall()
        return [dict(zip(["id"] + COLS, r)) for r in rows]

    def add(self, op, rec):
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM message WHERE op = ?", (op,)).fetchone()[0] + 1
            rec = dict(rec, n=str(n))
            self.db.execute(f"INSERT INTO message (op, {', '.join(COLS)}) VALUES (?, {', '.join('?' * len(COLS))})",
                            [op] + [rec.get(c, "") for c in COLS])
            self.db.commit()
        return n

    def update(self, mid, col, value):
        if col not in COLS or col in ("n", "ts", "utc"):
            return
        with self.lock:
            self.db.execute(f"UPDATE message SET {col} = ? WHERE id = ?", (value, mid))
            self.db.commit()


class MainCouranteDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Main courante", win)
        self.win = win
        self.setObjectName("maincourante")
        self.journal = Journal()
        s = win.settings
        self.t0 = None
        w = QWidget()
        v = QVBoxLayout(w)

        h = QHBoxLayout()
        h.addWidget(QLabel("Opération"))
        self.cb_op = QComboBox()
        self.cb_op.setMinimumWidth(240)
        self.cb_op.currentIndexChanged.connect(self.refresh)
        h.addWidget(self.cb_op, 1)
        for label, slot, tip in (("Nouvelle…", self.new_op, "Ouvrir une main courante pour une opération ou un exercice"),
                                 ("Clôturer", self.close_op, "Note l'heure de fin de l'opération")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.lb_op = QLabel("")
        self.lb_op.setObjectName("hint")
        v.addWidget(self.lb_op)

        g = QGridLayout()
        self.cb_sens = QComboBox()
        self.cb_sens.addItems(SENS)
        self.ed_de = HistCombo(s, "mc_hist_de", CORRESP, "indicatif, poste ou service", upper=True)
        self.ed_a = HistCombo(s, "mc_hist_a", CORRESP, "indicatif, poste ou service", upper=True)
        self.ed_moyen = HistCombo(s, "mc_hist_moyen", MOYENS, "fréquence, canal, téléphone…")
        self.cb_type = HistCombo(s, "mc_hist_type", TYPES, "type de message")
        self.cb_type.setText("Message")
        self.cb_prio = QComboBox()
        self.cb_prio.addItems(PRIOS)
        self.ed_op = HistCombo(s, "mc_hist_op", [], "opérateur", upper=True)
        self.ed_op.setText(s.value("mc_operateur", "") or s.value("mycall", ""))
        self.ed_msg = QPlainTextEdit()
        self.ed_msg.setPlaceholderText("Texte du message. Ctrl+Entrée pour enregistrer.")
        self.ed_msg.setMaximumHeight(70)
        self.ed_msg.textChanged.connect(self._start_clock)
        for cb in (self.ed_de, self.ed_a, self.ed_moyen):
            cb.editTextChanged.connect(lambda _t: self._start_clock())
        self.cb_type.editTextChanged.connect(lambda _t: self._start_clock())
        self.ed_suite = QLineEdit()
        self.ed_suite.setPlaceholderText("suite donnée, observations")
        self.lb_time = QLabel("—")
        self.lb_time.setObjectName("value")
        b_now = QPushButton("Remettre à l'heure")
        b_now.setToolTip("L'heure se fige toute seule dès la première saisie ; ce bouton reprend l'heure actuelle")
        b_now.clicked.connect(lambda: self._start_clock(force=True))
        g.addWidget(QLabel("Heure"), 0, 0)
        hh = QHBoxLayout()
        hh.addWidget(self.lb_time)
        hh.addWidget(b_now)
        hh.addStretch()
        g.addLayout(hh, 0, 1)
        g.addWidget(QLabel("Sens"), 0, 2)
        sh = QHBoxLayout()
        sh.addWidget(self.cb_sens, 1)
        sh.addWidget(QLabel("Type"))
        sh.addWidget(self.cb_type, 2)
        g.addLayout(sh, 0, 3)
        g.addWidget(QLabel("De"), 1, 0)
        g.addWidget(self.ed_de, 1, 1)
        g.addWidget(QLabel("À"), 1, 2)
        g.addWidget(self.ed_a, 1, 3)
        g.addWidget(QLabel("Moyen"), 2, 0)
        g.addWidget(self.ed_moyen, 2, 1)
        g.addWidget(QLabel("Priorité"), 2, 2)
        g.addWidget(self.cb_prio, 2, 3)
        mv = QVBoxLayout()
        mv.addWidget(QLabel("Message"))
        self.cb_tpl = QComboBox()
        self.cb_tpl.setToolTip("Modèles de messages ADRASEC : choisir pour remplir le texte")
        self.cb_tpl.activated.connect(self._use_template)
        mv.addWidget(self.cb_tpl)
        mv.addStretch()
        g.addLayout(mv, 3, 0)
        g.addWidget(self.ed_msg, 3, 1, 1, 3)
        try:
            self.templates = json.loads(s.value("mc_templates", "null") or "null") or DEFAULT_TEMPLATES
        except ValueError:
            self.templates = DEFAULT_TEMPLATES
        self._fill_templates()
        g.addWidget(QLabel("Suite"), 4, 0)
        g.addWidget(self.ed_suite, 4, 1, 1, 2)
        g.addWidget(self.ed_op, 4, 3)
        v.addLayout(g)
        h = QHBoxLayout()
        b = QPushButton("Enregistrer le message")
        b.setToolTip("Raccourci : Ctrl+Entrée dans le texte")
        b.clicked.connect(self.save)
        h.addWidget(b)
        b = QPushButton("Effacer")
        b.clicked.connect(self.clear_form)
        h.addWidget(b)
        v.addLayout(h)
        from PySide6.QtGui import QKeySequence, QShortcut
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self.ed_msg, activated=self.save)

        h = QHBoxLayout()
        self.ed_q = QLineEdit()
        self.ed_q.setPlaceholderText("Rechercher dans les messages")
        self.ed_q.textChanged.connect(self.refresh)
        h.addWidget(self.ed_q, 1)
        self.lb_count = QLabel("")
        self.lb_count.setObjectName("hint")
        h.addWidget(self.lb_count)
        v.addLayout(h)
        self.tbl = QTableWidget(0, len(HEAD))
        self.tbl.setHorizontalHeaderLabels(HEAD)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.tbl.setWordWrap(True)
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(8, QHeaderView.Stretch)
        self.tbl.setToolTip("Double-clic sur « Suite donnée » (ou un autre champ) pour le compléter")
        self.tbl.itemChanged.connect(self._edited)
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        for label, slot in (("Exporter en PDF…", self.export_pdf), ("Exporter en CSV…", self.export_csv)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        h = QHBoxLayout()
        from PySide6.QtWidgets import QCheckBox
        self.ck_qso = QCheckBox("Noter aussi les QSO du carnet dans cette main courante")
        self.ck_qso.setToolTip("Chaque QSO enregistré (carnet, FT8…) s'ajoute ici, horodaté, tant que l'opération est en cours")
        self.ck_qso.setChecked(s.value("mc_qso", "false") in (True, "true"))
        h.addWidget(self.ck_qso)
        h.addStretch()
        v.addLayout(h)
        self.setWidget(w)
        self.setMinimumWidth(620)
        win.log.added.connect(self._qso_added)
        self.reload_ops(select=int(s.value("mc_op", 0) or 0))
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._live_clock)
        self._clock.start(1000)
        self._live_clock()

    # --- opérations -----------------------------------------------------------------------
    def reload_ops(self, select=None):
        self.cb_op.blockSignals(True)
        self.cb_op.clear()
        for oid, nom, lieu, resp, debut, fin in self.journal.operations():
            self.cb_op.addItem(f"{nom} — {debut[:10]}" + (" (close)" if fin else ""), oid)
        if select:
            i = self.cb_op.findData(select)
            if i >= 0:
                self.cb_op.setCurrentIndex(i)
        self.cb_op.blockSignals(False)
        self.refresh()

    def current_op(self):
        return self.cb_op.currentData()

    def new_op(self):
        nom, ok = QInputDialog.getText(self, "Nouvelle main courante", "Nom de l'opération ou de l'exercice :",
                                       text=f"Exercice du {datetime.date.today():%d/%m/%Y}")
        if not ok or not nom.strip():
            return
        lieu, _ = QInputDialog.getText(self, "Nouvelle main courante", "Lieu (facultatif) :")
        resp, _ = QInputDialog.getText(self, "Nouvelle main courante", "Responsable / chef de poste (facultatif) :")
        oid = self.journal.new_operation(nom.strip(), lieu.strip(), resp.strip())
        self.reload_ops(select=oid)

    def close_op(self):
        op = self.current_op()
        if op and QMessageBox.question(self, "Main courante", "Clôturer cette opération (heure de fin) ?") == QMessageBox.Yes:
            self.journal.close_operation(op)
            self.reload_ops(select=op)

    # --- saisie ---------------------------------------------------------------------------
    def _live_clock(self):
        """Tant que rien n'est saisi, l'heure affichée avance ; elle se fige à la première saisie."""
        if self.t0 is None:
            now = datetime.datetime.now().astimezone()
            self.lb_time.setText(now.strftime("%d/%m/%Y %H:%M:%S") +
                                 now.astimezone(datetime.timezone.utc).strftime("  (%H:%M UTC)") + "  · se fige à la saisie")
            self.lb_time.setStyleSheet("color: #8a8a8a;")

    def _start_clock(self, force=False):
        if getattr(self, "_filling", False):
            return
        if self.t0 is None or force:
            self.t0 = datetime.datetime.now().astimezone()
            self.lb_time.setStyleSheet("")
            self.lb_time.setText(self.t0.strftime("%d/%m/%Y %H:%M:%S") +
                                 self.t0.astimezone(datetime.timezone.utc).strftime("  (%H:%M UTC)"))
            if not self.ed_moyen.text():
                self.ed_moyen.setText(self._rig_moyen())

    def _rig_moyen(self):
        st = getattr(self.win, "_last", None)
        if st and self.win.ctrl.connected and st.freq:
            from .gui import MODE_LABELS
            return f"{st.freq / 1e6:.4f} MHz {MODE_LABELS.get(st.mode, st.mode)}".replace(".", ",")
        return ""

    def save(self):
        op = self.current_op()
        if not op:
            QMessageBox.information(self, "Main courante", "Créez d'abord une opération (bouton « Nouvelle… »).")
            return
        msg = self.ed_msg.toPlainText().strip()
        if not msg:
            return
        if self.t0 is None:
            self._start_clock(force=True)
        rec = {"ts": self.t0.strftime("%d/%m/%Y %H:%M:%S"),
               "utc": self.t0.astimezone(datetime.timezone.utc).strftime("%H:%M"),
               "sens": self.cb_sens.currentText(), "type": self.cb_type.text(), "de": self.ed_de.text(),
               "a": self.ed_a.text(), "moyen": self.ed_moyen.text(),
               "prio": self.cb_prio.currentText(), "message": msg, "suite": self.ed_suite.text().strip(),
               "operateur": self.ed_op.text().strip()}
        n = self.journal.add(op, rec)
        rig = [self._rig_moyen()] if self._rig_moyen() else []
        for cb in (self.ed_de, self.ed_a, self.cb_type, self.ed_op):
            cb.remember()
        self.ed_moyen.remember(rig)
        self.win.statusBar().showMessage(f"Main courante : message n° {n} enregistré")
        self.clear_form()
        self.refresh()

    def clear_form(self):
        self.ed_msg.blockSignals(True)
        self.ed_msg.clear()
        self.ed_msg.blockSignals(False)
        self._filling = True
        for ed in (self.ed_de, self.ed_a, self.ed_suite, self.ed_moyen):
            ed.setText("")
        self.cb_type.setText("Message")
        self._filling = False
        self.cb_prio.setCurrentIndex(0)
        self.t0 = None
        self._live_clock()
        self.ed_msg.setFocus()

    # --- tableau --------------------------------------------------------------------------
    def refresh(self):
        op = self.current_op()
        info = self.journal.operation(op) if op else None
        if info:
            _id, nom, lieu, resp, debut, fin = info
            self.lb_op.setText(" · ".join(x for x in (f"Début {debut}", f"fin {fin}" if fin else "en cours",
                                                     lieu and f"lieu : {lieu}", resp and f"responsable : {resp}") if x))
        else:
            self.lb_op.setText("Aucune opération : cliquez sur « Nouvelle… »")
        rows = self.journal.messages(op, self.ed_q.text().strip()) if op else []
        self.rows = rows
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for c, key in enumerate(COLS):
                it = QTableWidgetItem(r.get(key) or "")
                if key in ("n", "ts", "utc"):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if r.get("prio") in PRIO_COLORS:
                    it.setForeground(QColor(PRIO_COLORS[r["prio"]]))
                self.tbl.setItem(i, c, it)
        self.tbl.resizeRowsToContents()
        self.tbl.blockSignals(False)
        self.tbl.scrollToBottom()
        self.lb_count.setText(f"{len(rows)} message{'s' if len(rows) > 1 else ''}")

    def _edited(self, it):
        r = self.rows[it.row()] if it.row() < len(self.rows) else None
        if r:
            self.journal.update(r["id"], COLS[it.column()], it.text())

    # --- exports --------------------------------------------------------------------------
    def _fname(self, ext):
        info = self.journal.operation(self.current_op())
        base = "".join(c if c.isalnum() or c in "-_" else "_" for c in (info[1] if info else "main_courante"))
        return os.path.join(data_dir(), f"Main_courante_{base}.{ext}")

    def export_csv(self):
        op = self.current_op()
        if not op:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en CSV", self._fname("csv"), "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=";")
            wr.writerow(HEAD)
            for r in self.journal.messages(op):
                wr.writerow([r.get(c) or "" for c in COLS])
        self.win.statusBar().showMessage(f"Main courante exportée dans {path}")

    def to_html(self, op):
        _id, nom, lieu, resp, debut, fin = self.journal.operation(op)
        e = html.escape
        rows = self.journal.messages(op)
        out = [f"<h2 style='margin:0'>Main courante — {e(nom)}</h2>",
               f"<p style='margin:4px 0 10px 0'>Début : {e(debut)} &nbsp;·&nbsp; Fin : {e(fin or 'en cours')}"
               + (f" &nbsp;·&nbsp; Lieu : {e(lieu)}" if lieu else "")
               + (f" &nbsp;·&nbsp; Responsable : {e(resp)}" if resp else "")
               + f" &nbsp;·&nbsp; {len(rows)} messages</p>",
               "<table border='1' cellspacing='0' cellpadding='3' width='100%' style='border-collapse:collapse;"
               "font-size:8pt'>", "<tr style='background:#dddddd'>" + "".join(f"<th>{h}</th>" for h in HEAD) + "</tr>"]
        for r in rows:
            col = {"Urgent": "#fff3e0", "Très urgent": "#ffebee"}.get(r.get("prio"), "")
            out.append(f"<tr{f' style=\"background:{col}\"' if col else ''}>"
                       + "".join(f"<td>{e(r.get(c) or '').replace(chr(10), '<br>')}</td>" for c in COLS) + "</tr>")
        out.append("</table>")
        out.append(f"<p style='margin-top:18px'>Édité le {datetime.datetime.now():%d/%m/%Y à %H:%M} par CAT Pilot."
                   "&nbsp;&nbsp;&nbsp; Visa du responsable : ______________________</p>")
        return "\n".join(out)

    def export_pdf(self):
        op = self.current_op()
        if not op:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en PDF", self._fname("pdf"), "PDF (*.pdf)")
        if not path:
            return
        self.write_pdf(op, path)
        self.win.statusBar().showMessage(f"Main courante exportée dans {path}")
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def write_pdf(self, op, path):
        pdf = QPdfWriter(path)
        pdf.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape, QMarginsF(12, 12, 12, 12),
                                      QPageLayout.Millimeter))
        pdf.setResolution(300)
        pdf.setTitle("Main courante")
        doc = QTextDocument()
        doc.documentLayout().setPaintDevice(pdf)        # tailles de police à la résolution du PDF
        f = doc.defaultFont()
        f.setPointSizeF(9)
        doc.setDefaultFont(f)
        doc.setHtml(self.to_html(op))
        doc.setPageSize(pdf.pageLayout().paintRectPixels(pdf.resolution()).size().toSizeF())
        doc.print_(pdf)

    # --- modèles et QSO ----------------------------------------------------------------------
    def _fill_templates(self):
        self.cb_tpl.clear()
        self.cb_tpl.addItem("Modèle…")
        for name, _t in self.templates:
            self.cb_tpl.addItem(name)
        self.cb_tpl.addItem("Gérer les modèles…")

    def _use_template(self, i):
        if i == 0:
            return
        if i == self.cb_tpl.count() - 1:
            self._manage_templates()
        else:
            name, text = self.templates[i - 1]
            st = getattr(self.win, "station", None)
            now = datetime.datetime.now()
            text = (text.replace("{HEURE}", now.strftime("%H h %M"))
                    .replace("{MOYEN}", self._rig_moyen() or "…")
                    .replace("{LOC}", self.win.b_loc.text().split()[0] if st else "…")
                    .replace("{LAT}", f"{st[0]:.5f}" if st else "…").replace("{LON}", f"{st[1]:.5f}" if st else "…")
                    .replace("{MYCALL}", (self.win.settings.value("mycall", "") or "").upper())
                    .replace("{OPERATEUR}", self.ed_op.text() or "…"))
            self.ed_msg.setPlainText(text)
            if name in TEMPLATE_TYPE:
                self.cb_type.setText(TEMPLATE_TYPE[name])
            self.ed_msg.setFocus()
        self.cb_tpl.setCurrentIndex(0)

    def _manage_templates(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget
        d = QDialog(self)
        d.setWindowTitle("Modèles de messages")
        d.resize(620, 380)
        v = QVBoxLayout(d)
        hl = QHBoxLayout()
        lst = QListWidget()
        ed_name = QLineEdit()
        ed_txt = QPlainTextEdit()
        items = [list(t) for t in self.templates]
        for n, _t in items:
            lst.addItem(n)
        right = QVBoxLayout()
        right.addWidget(QLabel("Nom"))
        right.addWidget(ed_name)
        right.addWidget(QLabel("Texte ({HEURE}, {MOYEN}, {LOC}, {LAT}, {LON}, {MYCALL}, {OPERATEUR})"))
        right.addWidget(ed_txt, 1)
        hl.addWidget(lst, 1)
        hl.addLayout(right, 2)
        v.addLayout(hl, 1)

        def sel(row):
            if 0 <= row < len(items):
                ed_name.setText(items[row][0])
                ed_txt.setPlainText(items[row][1])

        def store():
            row = lst.currentRow()
            if 0 <= row < len(items):
                items[row] = [ed_name.text().strip() or items[row][0], ed_txt.toPlainText()]
                lst.item(row).setText(items[row][0])
        lst.currentRowChanged.connect(sel)
        ed_name.editingFinished.connect(store)
        ed_txt.textChanged.connect(store)
        bh = QHBoxLayout()
        b = QPushButton("Nouveau")
        b.clicked.connect(lambda: (items.append(["Nouveau modèle", ""]), lst.addItem("Nouveau modèle"),
                                   lst.setCurrentRow(len(items) - 1)))
        bh.addWidget(b)
        b = QPushButton("Supprimer")
        b.clicked.connect(lambda: (lst.currentRow() >= 0) and (items.pop(lst.currentRow()), lst.takeItem(lst.currentRow())))
        bh.addWidget(b)
        b = QPushButton("Modèles d'origine")
        b.clicked.connect(lambda: (items.clear(), items.extend([list(t) for t in DEFAULT_TEMPLATES]), lst.clear(),
                                   [lst.addItem(n) for n, _t in items]))
        bh.addWidget(b)
        bh.addStretch()
        v.addLayout(bh)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        lst.setCurrentRow(0)
        if d.exec():
            store()
            self.templates = [tuple(t) for t in items if t[0]]
            self.win.settings.setValue("mc_templates", json.dumps(self.templates))
            self._fill_templates()

    def _qso_added(self, qid):
        op = self.current_op()
        if not self.ck_qso.isChecked() or not op:
            return
        info = self.journal.operation(op)
        if not info or info[5]:                       # opération close
            return
        rows = self.win.log.query("id = ?", (qid,))
        if not rows:
            return
        r = rows[0]
        moyen = ""
        try:
            moyen = f"{float(r['freq']):.4f} MHz {r.get('submode') or r.get('mode') or ''}".replace(".", ",")
        except (TypeError, ValueError):
            moyen = r.get("mode") or ""
        now = datetime.datetime.now().astimezone()
        rec = {"ts": now.strftime("%d/%m/%Y %H:%M:%S"), "utc": now.astimezone(datetime.timezone.utc).strftime("%H:%M"),
               "sens": "Info", "type": "QSO", "de": (r.get("station_callsign") or "").upper(), "a": r["call"], "moyen": moyen,
               "prio": "Routine",
               "message": f"QSO avec {r['call']}" + (f" ({r['name']})" if r.get("name") else "")
                          + f", report envoyé {r.get('rst_sent') or '-'}, reçu {r.get('rst_rcvd') or '-'}",
               "suite": "", "operateur": self.ed_op.text().strip()}
        self.journal.add(op, rec)
        self.refresh()

    def save_settings(self, s):
        s.setValue("mc_qso", self.ck_qso.isChecked())
        s.setValue("mc_operateur", self.ed_op.text())
        s.setValue("mc_op", self.current_op() or 0)
