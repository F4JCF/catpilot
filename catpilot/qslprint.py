"""Étiquettes QSL à coller au dos des cartes papier : PDF prêt à imprimer sur planches A4.

Une étiquette par correspondant (jusqu'à 4 QSO), avec le « QSL via » du manager s'il est connu.
"""
import datetime
import os

from PySide6.QtCore import QMarginsF, QRectF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QSpinBox, QVBoxLayout,
)

from .logbook import data_dir

# nom, colonnes, lignes, largeur, hauteur, marge gauche, marge haute, écart horizontal, écart vertical (mm)
FORMATS = [
    ("3 × 8 — 70 × 37 mm (24 par page)", 3, 8, 70.0, 37.0, 0.0, 0.5, 0.0, 0.0),
    ("3 × 7 — 63,5 × 38,1 mm (Avery L7160, 21 par page)", 3, 7, 63.5, 38.1, 7.2, 15.1, 2.5, 0.0),
    ("2 × 7 — 99,1 × 38,1 mm (Avery L7163, 14 par page)", 2, 7, 99.1, 38.1, 4.7, 15.1, 2.5, 0.0),
    ("3 × 10 — 70 × 29,7 mm (30 par page)", 3, 10, 70.0, 29.7, 0.0, 0.0, 0.0, 0.0),
]
PER_LABEL = 4


def group_labels(recs):
    """Regroupe les QSO par indicatif (et manager), 4 au plus par étiquette, du plus ancien au plus récent."""
    recs = sorted(recs, key=lambda r: (r.get("call") or "", r.get("qso_date") or "", r.get("time_on") or ""))
    out, cur, key = [], [], None
    for r in recs:
        k = ((r.get("call") or "").upper(), (r.get("qsl_via") or "").upper())
        if k != key or len(cur) >= PER_LABEL:
            if cur:
                out.append(cur)
            cur, key = [], k
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def make_pdf(path, labels, fmt, start=1, mycall="", footer=""):
    name, cols, rows, w, h, left, top, hgap, vgap = fmt
    pdf = QPdfWriter(path)
    pdf.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0),
                                  QPageLayout.Millimeter))
    pdf.setResolution(300)
    pdf.setCreator("CAT Pilot")
    pdf.setTitle("Étiquettes QSL")
    mm = 300 / 25.4
    p = QPainter(pdf)
    per_page = cols * rows
    slot = max(0, start - 1)
    for lab in labels:
        if slot >= per_page:
            pdf.newPage()
            slot = 0
        c, r = slot % cols, slot // cols
        x = (left + c * (w + hgap)) * mm
        y = (top + r * (h + vgap)) * mm
        _draw(p, QRectF(x, y, w * mm, h * mm), lab, mm, mycall, footer)
        slot += 1
    p.end()


def _draw(p, box, recs, mm, mycall, footer):
    pad = 2.6 * mm
    inner = box.adjusted(pad, pad * 0.8, -pad, -pad * 0.8)
    call = (recs[0].get("call") or "").upper()
    via = (recs[0].get("qsl_via") or "").upper()
    f = QFont("Arial")
    f.setPixelSize(int(4.0 * mm))
    f.setBold(True)
    p.setFont(f)
    p.setPen(Qt.black)
    head = f"To Radio {call}" + (f"  via {via}" if via else "")
    hh = 5.0 * mm
    p.drawText(QRectF(inner.left(), inner.top(), inner.width(), hh), Qt.AlignLeft | Qt.AlignVCenter, head)
    # tableau
    small = QFont("Arial")
    small.setPixelSize(int(2.55 * mm))
    heads = ["Date", "UTC", "MHz", "Mode", "RST"]
    widths = [0.27, 0.15, 0.22, 0.2, 0.16]
    y = inner.top() + hh + 0.6 * mm
    row_h = 3.3 * mm
    xs, acc = [], inner.left()
    for wf in widths:
        xs.append(acc)
        acc += wf * inner.width()
    small.setBold(True)
    p.setFont(small)
    for i, t in enumerate(heads):
        p.drawText(QRectF(xs[i], y, widths[i] * inner.width(), row_h), Qt.AlignLeft | Qt.AlignVCenter, t)
    p.setPen(QPen(Qt.black, max(1, int(0.2 * mm))))
    p.drawLine(int(inner.left()), int(y + row_h), int(inner.right()), int(y + row_h))
    small.setBold(False)
    p.setFont(small)
    y += row_h + 0.3 * mm
    for r in recs:
        d = r.get("qso_date") or ""
        try:
            mhz = f"{float(r.get('freq')):.3f}" if r.get("freq") else (r.get("band") or "")
        except ValueError:
            mhz = r.get("band") or ""
        vals = [f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else d, (r.get("time_on") or "")[:4],
                mhz, r.get("submode") or r.get("mode") or "", r.get("rst_sent") or ""]
        for i, t in enumerate(vals):
            p.drawText(QRectF(xs[i], y, widths[i] * inner.width(), row_h), Qt.AlignLeft | Qt.AlignVCenter, t)
        y += row_h
    # pied
    got = all((r.get("qsl_rcvd") or "").upper() == "Y" for r in recs)
    foot = footer or ("TNX QSL" if got else "PSE QSL")
    if mycall:
        foot += f" — 73 de {mycall}"
    small.setBold(True)
    p.setFont(small)
    p.drawText(QRectF(inner.left(), inner.bottom() - row_h, inner.width(), row_h), Qt.AlignLeft | Qt.AlignVCenter, foot)


class LabelDialog(QDialog):
    def __init__(self, win, recs=None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Étiquettes QSL")
        if recs is None:
            recs = win.log.query("qsl_sent IN ('R', 'Q')")
            self.src = "toutes les cartes « à envoyer »"
        else:
            self.src = "les QSO sélectionnés"
        self.recs = recs
        self.labels = group_labels(recs)
        v = QVBoxLayout(self)
        t = QLabel(f"{len(recs)} QSO ({self.src}) → {len(self.labels)} étiquette{'s' if len(self.labels) > 1 else ''}."
                   "\nUne étiquette par correspondant, 4 QSO au plus, avec son manager QSL s'il est connu.")
        t.setWordWrap(True)
        v.addWidget(t)
        f = QFormLayout()
        s = win.settings
        self.cb_fmt = QComboBox()
        for fm in FORMATS:
            self.cb_fmt.addItem(fm[0])
        self.cb_fmt.setCurrentIndex(int(s.value("qsl_label_fmt", 0) or 0))
        f.addRow("Planche", self.cb_fmt)
        self.sp_start = QSpinBox()
        self.sp_start.setRange(1, 30)
        self.sp_start.setToolTip("Pour réutiliser une planche entamée : numéro de la première étiquette libre "
                                 "(de gauche à droite, puis ligne par ligne)")
        f.addRow("Commencer à l'étiquette n°", self.sp_start)
        self.ed_foot = QLineEdit(s.value("qsl_label_foot", ""))
        self.ed_foot.setPlaceholderText("automatique : PSE QSL, ou TNX QSL si la sienne est reçue")
        f.addRow("Mention en bas", self.ed_foot)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        b = bb.addButton("Créer le PDF et l'ouvrir", QDialogButtonBox.AcceptRole)
        b.setDefault(True)
        bb.accepted.connect(self.go)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if not recs:
            b.setEnabled(False)
            t.setText("Aucune carte à envoyer. Dans le carnet, sélectionnez des QSO, clic droit, "
                      "« Carte à envoyer », puis revenez ici.")

    def go(self):
        s = self.win.settings
        s.setValue("qsl_label_fmt", self.cb_fmt.currentIndex())
        s.setValue("qsl_label_foot", self.ed_foot.text())
        d = os.path.join(data_dir(), "etiquettes")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"etiquettes_QSL_{datetime.datetime.now():%Y%m%d_%H%M%S}.pdf")
        try:
            make_pdf(path, self.labels, FORMATS[self.cb_fmt.currentIndex()], self.sp_start.value(),
                     (s.value("mycall", "") or "").upper(), self.ed_foot.text().strip())
        except Exception as e:
            QMessageBox.warning(self, "Étiquettes QSL", f"Le PDF n'a pas pu être créé.\n\n{e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        box = QMessageBox(self)
        box.setWindowTitle("Étiquettes QSL")
        box.setText(f"PDF créé : {path}\n\nFaut-il marquer ces {len(self.recs)} QSO comme « carte envoyée » ?")
        b_bur = box.addButton("Oui, par le bureau", QMessageBox.YesRole)
        b_dir = box.addButton("Oui, en direct", QMessageBox.YesRole)
        box.addButton("Pas encore", QMessageBox.NoRole)
        box.exec()
        via = {b_bur: "B", b_dir: "D"}.get(box.clickedButton())
        if via:
            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
            for r in self.recs:
                self.win.log.update(r["id"], {"qsl_sent": "Y", "qsl_sent_via": via, "qslsdate": today}, notify=False)
            self.win.log.changed.emit()
        self.accept()
