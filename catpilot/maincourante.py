"""Main courante (ADRASEC, sécurité civile) : journal horodaté des messages d'une opération.

Chaque opération ou exercice a sa propre liste, numérotée. Saisie rapide (l'heure se fige
au premier caractère tapé, le moyen radio vient du poste), recherche, export PDF et CSV.
Base : Documents/CATPilot/main_courante.sqlite
"""
import csv
import datetime
import html
import os
import sqlite3
import threading

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDockWidget, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .logbook import data_dir

COLS = ["n", "ts", "utc", "sens", "de", "a", "moyen", "prio", "message", "suite", "operateur"]
HEAD = ["N°", "Date et heure", "UTC", "Sens", "De", "À", "Moyen", "Priorité", "Message", "Suite donnée", "Opérateur"]
PRIOS = ["Routine", "Urgent", "Très urgent"]
SENS = ["Reçu", "Émis", "Info"]
PRIO_COLORS = {"Urgent": "#ff9800", "Très urgent": "#f44336"}


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
        self.ed_de = QLineEdit()
        self.ed_de.setPlaceholderText("indicatif, poste ou service")
        self.ed_a = QLineEdit()
        self.ed_a.setPlaceholderText("indicatif, poste ou service")
        self.ed_moyen = QLineEdit()
        self.ed_moyen.setPlaceholderText("fréquence, canal, téléphone…")
        self.cb_prio = QComboBox()
        self.cb_prio.addItems(PRIOS)
        self.ed_op = QLineEdit(s.value("mc_operateur", "") or s.value("mycall", ""))
        self.ed_op.setPlaceholderText("opérateur")
        self.ed_msg = QPlainTextEdit()
        self.ed_msg.setPlaceholderText("Texte du message. Ctrl+Entrée pour enregistrer.")
        self.ed_msg.setMaximumHeight(70)
        self.ed_msg.textChanged.connect(self._start_clock)
        self.ed_suite = QLineEdit()
        self.ed_suite.setPlaceholderText("suite donnée, observations")
        self.lb_time = QLabel("—")
        self.lb_time.setObjectName("value")
        b_now = QPushButton("Maintenant")
        b_now.setToolTip("Reprendre l'heure actuelle")
        b_now.clicked.connect(lambda: self._start_clock(force=True))
        g.addWidget(QLabel("Heure"), 0, 0)
        hh = QHBoxLayout()
        hh.addWidget(self.lb_time)
        hh.addWidget(b_now)
        hh.addStretch()
        g.addLayout(hh, 0, 1)
        g.addWidget(QLabel("Sens"), 0, 2)
        g.addWidget(self.cb_sens, 0, 3)
        g.addWidget(QLabel("De"), 1, 0)
        g.addWidget(self.ed_de, 1, 1)
        g.addWidget(QLabel("À"), 1, 2)
        g.addWidget(self.ed_a, 1, 3)
        g.addWidget(QLabel("Moyen"), 2, 0)
        g.addWidget(self.ed_moyen, 2, 1)
        g.addWidget(QLabel("Priorité"), 2, 2)
        g.addWidget(self.cb_prio, 2, 3)
        g.addWidget(QLabel("Message"), 3, 0)
        g.addWidget(self.ed_msg, 3, 1, 1, 3)
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
        self.setWidget(w)
        self.setMinimumWidth(620)
        self.reload_ops(select=int(s.value("mc_op", 0) or 0))

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
    def _start_clock(self, force=False):
        if self.t0 is None or force:
            if not force and not self.ed_msg.toPlainText().strip():
                return
            self.t0 = datetime.datetime.now().astimezone()
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
               "sens": self.cb_sens.currentText(), "de": self.ed_de.text().strip().upper(),
               "a": self.ed_a.text().strip().upper(), "moyen": self.ed_moyen.text().strip(),
               "prio": self.cb_prio.currentText(), "message": msg, "suite": self.ed_suite.text().strip(),
               "operateur": self.ed_op.text().strip()}
        n = self.journal.add(op, rec)
        self.win.statusBar().showMessage(f"Main courante : message n° {n} enregistré")
        self.clear_form()
        self.refresh()

    def clear_form(self):
        self.ed_msg.blockSignals(True)
        self.ed_msg.clear()
        self.ed_msg.blockSignals(False)
        for ed in (self.ed_de, self.ed_a, self.ed_suite, self.ed_moyen):
            ed.clear()
        self.cb_prio.setCurrentIndex(0)
        self.t0 = None
        self.lb_time.setText("—")
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

    def save_settings(self, s):
        s.setValue("mc_operateur", self.ed_op.text())
        s.setValue("mc_op", self.current_op() or 0)
