"""Fenêtres du carnet : envoi en ligne (QRZ.com, eQSL, Club Log, LoTW) et diplômes / statistiques."""
import collections

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import cty
from .upload import SERVICES, find_tqsl

BANDS = ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m", "4m", "2m", "70cm"]


# --- envoi en ligne --------------------------------------------------------------------------
class UploadDialog(QDialog):
    FIELDS = {
        "qrz": [("qrz_logkey", "Clé API du carnet QRZ", False)],
        "eqsl": [("eqsl_user", "Utilisateur eQSL", False), ("eqsl_pass", "Mot de passe eQSL", True)],
        "clublog": [("clublog_email", "E-mail Club Log", False), ("clublog_pass", "Mot de passe Club Log", True),
                    ("clublog_api", "Clé API Club Log", False)],
        "lotw": [("tqsl_path", "Chemin de tqsl.exe", False), ("tqsl_location", "Lieu de station TQSL", False)],
    }
    HELP = {
        "qrz": "Sur qrz.com : Logbook > Settings > « API Access Key ».",
        "eqsl": "Votre compte eqsl.cc (gratuit).",
        "clublog": "Club Log demande une clé API par logiciel : demandez-la sur clublog.org (Help > API), "
                   "puis collez-la ici.",
        "lotw": "Installez TQSL (ARRL), votre certificat et un « Station Location » : CAT Pilot lui confie la "
                "signature et l'envoi. Indiquez le nom exact du lieu de station.",
    }

    def __init__(self, win):
        super().__init__(win)
        self.win, self.s = win, win.settings
        self.setWindowTitle("Envoi des QSO en ligne")
        self.resize(640, 0)
        v = QVBoxLayout(self)
        self.edits, self.autos, self.lb_pending = {}, {}, {}
        counts = win.log.upload_counts()
        for svc, name in SERVICES.items():
            gb = QGroupBox(name)
            f = QFormLayout(gb)
            for key, label, pwd in self.FIELDS[svc]:
                ed = QLineEdit(self.s.value(key, "") or "")
                if pwd:
                    ed.setEchoMode(QLineEdit.Password)
                if key == "tqsl_path":
                    ed.setPlaceholderText(find_tqsl() or "C:\\Program Files (x86)\\TrustedQSL\\tqsl.exe")
                f.addRow(label, ed)
                self.edits[key] = ed
            t = QLabel(self.HELP[svc])
            t.setObjectName("hint")
            t.setWordWrap(True)
            f.addRow(t)
            h = QHBoxLayout()
            ck = QCheckBox("Envoyer chaque QSO dès son enregistrement")
            ck.setChecked(self.s.value(f"auto_{svc}", "false") in (True, "true"))
            self.autos[svc] = ck
            h.addWidget(ck)
            h.addStretch()
            lb = QLabel(f"{counts.get(svc, 0)} en attente")
            lb.setObjectName("value")
            self.lb_pending[svc] = lb
            h.addWidget(lb)
            b = QPushButton("Envoyer maintenant")
            b.clicked.connect(lambda _c=False, sv=svc: self.send_now(sv))
            h.addWidget(b)
            b = QPushButton("Tout renvoyer…")
            b.setToolTip("Marque tout le carnet comme « à envoyer » à ce service")
            b.clicked.connect(lambda _c=False, sv=svc: self.reset(sv))
            h.addWidget(b)
            f.addRow(h)
            v.addWidget(gb)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        v.addWidget(bb)
        win.uploader.progress.connect(self.lb.setText)
        win.uploader.finished.connect(self._done)

    def save(self):
        for key, ed in self.edits.items():
            self.s.setValue(key, ed.text().strip() if "pass" not in key else ed.text())
        for svc, ck in self.autos.items():
            self.s.setValue(f"auto_{svc}", "true" if ck.isChecked() else "false")

    def send_now(self, svc):
        self.save()
        if not self.win.uploader.configured(svc):
            self.lb.setText(f"{SERVICES[svc]} : renseignez d'abord les champs ci-dessus"
                            + (" (TQSL introuvable)" if svc == "lotw" and not find_tqsl(self.edits['tqsl_path'].text()) else ""))
            return
        self.win.uploader.send(svc)

    def reset(self, svc):
        if QMessageBox.question(self, SERVICES[svc], f"Renvoyer tout le carnet ({self.win.log.count()} QSO) "
                                f"à {SERVICES[svc]} au prochain envoi ?\n\nLes doublons sont ignorés par le "
                                "service.") == QMessageBox.Yes:
            self.win.log.reset_upload(svc)
            self._refresh()

    def _done(self, svc, ok, err):
        self.lb.setText(f"{SERVICES[svc]} : {ok} QSO envoyé{'s' if ok > 1 else ''}"
                        + (f", {err} en erreur" if err else ""))
        self._refresh()

    def _refresh(self):
        counts = self.win.log.upload_counts()
        for svc, lb in self.lb_pending.items():
            lb.setText(f"{counts.get(svc, 0)} en attente")

    def done(self, r):
        self.save()
        try:
            self.win.uploader.progress.disconnect(self.lb.setText)
            self.win.uploader.finished.disconnect(self._done)
        except (RuntimeError, TypeError):
            pass
        super().done(r)


# --- diplômes et statistiques -----------------------------------------------------------------
def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSortingEnabled(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    return t


def _fill(t, rows, mark_cols=()):
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem("" if val is None else str(val))
            if c in mark_cols:
                it.setTextAlignment(Qt.AlignCenter)
                if val:
                    it.setBackground(QColor(76, 175, 80, 90))
            t.setItem(i, c, it)
    t.setSortingEnabled(True)


class AwardsDialog(QDialog):
    """DXCC, continents (WAC), zones CQ (WAZ) et ITU, carrés locator, parcs POTA, bandes et modes."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Diplômes et statistiques")
        self.resize(900, 620)
        v = QVBoxLayout(self)
        rows = win.log.query()
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        from .logbook import french_name
        ent = {}                      # préfixe -> infos, bandes, modes, nb
        conts, cqz, ituz = collections.Counter(), collections.Counter(), collections.Counter()
        grids = collections.defaultdict(set)
        parks, myparks = collections.Counter(), collections.Counter()
        bandmode = collections.Counter()
        for r in rows:
            band = r.get("band") or ""
            mode = r.get("submode") or r.get("mode") or ""
            bandmode[(band, mode)] += 1
            e = cty.dxcc(r["call"] or "")
            info = cty.lookup(r["call"] or "")
            if e:
                d = ent.setdefault(e["prefix"], {"e": e, "bands": set(), "modes": set(), "n": 0, "first": ""})
                d["bands"].add(band)
                d["modes"].add(mode)
                d["n"] += 1
                if not d["first"] or (r["qso_date"] or "") < d["first"]:
                    d["first"] = r["qso_date"] or ""
            if info:
                conts[info["cont"]] += 1
                cqz[int(info["cq"])] += 1
                ituz[int(info["itu"])] += 1
            g = (r.get("gridsquare") or "")[:4].upper()
            if len(g) == 4:
                grids[g].add(band)
            if (r.get("sig") or "").upper() == "POTA" and r.get("sig_info"):
                parks[r["sig_info"].upper()] += 1
            if (r.get("my_sig") or "").upper() == "POTA" and r.get("my_sig_info"):
                myparks[r["my_sig_info"].upper()] += 1

        total_ent = len(cty.entities())
        # DXCC
        t = _table(["Préfixe", "Pays", "Continent", "QSO", "1er QSO"] + BANDS)
        data = []
        for pre, d in sorted(ent.items(), key=lambda x: french_name(x[1]["e"])):
            f = d["first"]
            data.append([pre, french_name(d["e"]), d["e"]["cont"], d["n"],
                         f"{f[6:8]}/{f[4:6]}/{f[:4]}" if len(f) == 8 else f] + ["✓" if b in d["bands"] else "" for b in BANDS])
        _fill(t, data, mark_cols=range(5, 5 + len(BANDS)))
        tabs.addTab(t, f"DXCC ({len(ent)})")
        # bandes DXCC
        per_band = {b: sum(1 for d in ent.values() if b in d["bands"]) for b in BANDS}
        # continents
        names = {"EU": "Europe", "AF": "Afrique", "AS": "Asie", "NA": "Amérique du Nord",
                 "SA": "Amérique du Sud", "OC": "Océanie"}
        t = _table(["Continent", "QSO", "Contacté"])
        _fill(t, [[n, conts.get(k, 0), "✓" if conts.get(k) else ""] for k, n in names.items()], mark_cols=(2,))
        tabs.addTab(t, f"Continents WAC ({sum(1 for k in names if conts.get(k))}/6)")
        # zones CQ
        t = _table(["Zone CQ", "QSO", "Contactée"])
        _fill(t, [[z, cqz.get(z, 0), "✓" if cqz.get(z) else ""] for z in range(1, 41)], mark_cols=(2,))
        tabs.addTab(t, f"Zones CQ WAZ ({len(cqz)}/40)")
        t = _table(["Zone ITU", "QSO", "Contactée"])
        _fill(t, [[z, ituz.get(z, 0), "✓" if ituz.get(z) else ""] for z in range(1, 91)], mark_cols=(2,))
        tabs.addTab(t, f"Zones ITU ({len(ituz)}/90)")
        # locators
        t = _table(["Carré", "Bandes"])
        _fill(t, [[g, ", ".join(sorted(b for b in bs if b))] for g, bs in sorted(grids.items())])
        vhf = {b: sum(1 for bs in grids.values() if b in bs) for b in ("6m", "2m", "70cm")}
        tabs.addTab(t, f"Carrés locator ({len(grids)})")
        # POTA
        w = QWidget()
        h = QHBoxLayout(w)
        t1 = _table(["Parc chassé", "QSO"])
        _fill(t1, sorted(parks.items()))
        t2 = _table(["Parc activé", "QSO"])
        _fill(t2, sorted(myparks.items()))
        h.addWidget(t1)
        h.addWidget(t2)
        tabs.addTab(w, f"POTA ({len(parks)} chassés, {len(myparks)} activés)")
        # bandes / modes
        modes = sorted({m for _b, m in bandmode})
        bands = [b for b in BANDS if any(bb == b for bb, _m in bandmode)] + \
                sorted({b for b, _m in bandmode if b not in BANDS})
        t = _table(["Bande"] + modes + ["Total", "Pays DXCC"])
        _fill(t, [[b or "?"] + [bandmode.get((b, m), "") or "" for m in modes]
                  + [sum(bandmode.get((b, m), 0) for m in modes), per_band.get(b, "")] for b in bands])
        tabs.addTab(t, "Bandes et modes")

        best = ", ".join(f"{b} {n}" for b, n in per_band.items() if n)
        self.lb.setText(
            f"{len(rows)} QSO · {len(ent)} pays DXCC sur {total_ent} (DXCC : 100) · "
            f"{sum(1 for k in names if conts.get(k))}/6 continents · {len(cqz)}/40 zones CQ · "
            f"{len(grids)} carrés locator"
            + (f" (VUCC 50 : 6 m {vhf['6m']}, 2 m {vhf['2m']}, 70 cm {vhf['70cm']})" if any(vhf.values()) else "")
            + (f"\nPays par bande : {best}" if best else "")
            + "\nComptes « contactés » : les confirmations (QSL, LoTW) ne sont pas encore relevées.")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        b = bb.addButton("Exporter en CSV…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.export_csv(tabs))
        v.addWidget(bb)

    def export_csv(self, tabs):
        import csv
        import os
        from .logbook import data_dir
        w = tabs.currentWidget()
        tables = [w] if isinstance(w, QTableWidget) else w.findChildren(QTableWidget)
        name = tabs.tabText(tabs.currentIndex()).split(" (")[0].replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en CSV", os.path.join(data_dir(), f"{name}.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f, delimiter=";")
            for t in tables:
                wr.writerow([t.horizontalHeaderItem(c).text() for c in range(t.columnCount())])
                for r in range(t.rowCount()):
                    wr.writerow([(t.item(r, c).text() if t.item(r, c) else "") for c in range(t.columnCount())])
