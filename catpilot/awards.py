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
        "eqsl": [("eqsl_user", "Utilisateur eQSL", False), ("eqsl_pass", "Mot de passe eQSL", True),
                 ("eqsl_nick", "Surnom du QTH eQSL (facultatif)", False)],
        "clublog": [("clublog_email", "E-mail Club Log", False), ("clublog_pass", "Mot de passe Club Log", True),
                    ("clublog_api", "Clé API Club Log", False)],
        "lotw": [("tqsl_path", "Chemin de tqsl.exe", False), ("tqsl_location", "Lieu de station TQSL", False),
                 ("lotw_user", "Identifiant du site LoTW", False), ("lotw_pass", "Mot de passe du site LoTW", True)],
    }
    HELP = {
        "qrz": "Sur qrz.com : Logbook > Settings > « API Access Key ».",
        "eqsl": "Votre compte eqsl.cc (gratuit).",
        "clublog": "Club Log demande une clé API par logiciel : demandez-la sur clublog.org (Help > API), "
                   "puis collez-la ici.",
        "lotw": "Installez TQSL (ARRL), votre certificat et un « Station Location » : CAT Pilot lui confie la "
                "signature et l'envoi. Indiquez le nom exact du lieu de station. L'identifiant et le mot de passe "
                "du site lotw.arrl.org servent à relever les confirmations reçues.",
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
        gb = QGroupBox("Confirmations reçues (QSL eQSL et LoTW)")
        h = QHBoxLayout(gb)
        self.ck_qsl = QCheckBox("Relever chaque jour au démarrage")
        self.ck_qsl.setChecked(self.s.value("qsl_auto", "true") in (True, "true"))
        h.addWidget(self.ck_qsl)
        h.addStretch()
        cc = win.log.confirmed_counts()
        self.lb_conf = QLabel(f"confirmés : eQSL {cc['eqsl']}, LoTW {cc['lotw']}")
        self.lb_conf.setObjectName("value")
        h.addWidget(self.lb_conf)
        b = QPushButton("Relever maintenant")
        b.clicked.connect(self.sync_now)
        h.addWidget(b)
        v.addWidget(gb)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        v.addWidget(bb)
        win.qsl_sync.progress.connect(self.lb.setText)
        win.qsl_sync.finished.connect(self._sync_done)
        win.uploader.progress.connect(self.lb.setText)
        win.uploader.finished.connect(self._done)

    def save(self):
        for key, ed in self.edits.items():
            self.s.setValue(key, ed.text().strip() if "pass" not in key else ed.text())
        for svc, ck in self.autos.items():
            self.s.setValue(f"auto_{svc}", "true" if ck.isChecked() else "false")
        self.s.setValue("qsl_auto", "true" if self.ck_qsl.isChecked() else "false")

    def sync_now(self):
        self.save()
        if not any(self.win.qsl_sync.configured().values()):
            self.lb.setText("Renseignez le compte eQSL et/ou l'identifiant et le mot de passe du site LoTW")
            return
        if not self.win.qsl_sync.run():
            self.lb.setText("Relevé déjà en cours…")

    def _sync_done(self, msg):
        self.lb.setText(msg)
        cc = self.win.log.confirmed_counts()
        self.lb_conf.setText(f"confirmés : eQSL {cc['eqsl']}, LoTW {cc['lotw']}")

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
            self.win.qsl_sync.progress.disconnect(self.lb.setText)
            self.win.qsl_sync.finished.disconnect(self._sync_done)
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
                d = ent.setdefault(e["prefix"], {"e": e, "bands": set(), "modes": set(), "n": 0, "first": "",
                                                 "conf": set()})
                if "Y" in ((r.get("lotw_qsl_rcvd") or "") + (r.get("eqsl_qsl_rcvd") or "")).upper():
                    d["conf"].add(band)
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
        t = _table(["Préfixe", "Pays", "Continent", "QSO", "1er QSO", "Confirmé"] + BANDS)
        data = []
        for pre, d in sorted(ent.items(), key=lambda x: french_name(x[1]["e"])):
            f = d["first"]
            data.append([pre, french_name(d["e"]), d["e"]["cont"], d["n"],
                         f"{f[6:8]}/{f[4:6]}/{f[:4]}" if len(f) == 8 else f, "✔" if d["conf"] else ""]
                        + [("✔" if b in d["conf"] else "✓") if b in d["bands"] else "" for b in BANDS])
        _fill(t, data, mark_cols=range(5, 6 + len(BANDS)))
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

        tabs.insertTab(0, self._charts(rows, bandmode, conts, names), "Graphiques")
        tabs.setCurrentIndex(0)

        best = ", ".join(f"{b} {n}" for b, n in per_band.items() if n)
        self.lb.setText(
            f"{len(rows)} QSO · {len(ent)} pays DXCC sur {total_ent} (DXCC : 100) · "
            f"{sum(1 for k in names if conts.get(k))}/6 continents · {len(cqz)}/40 zones CQ · "
            f"{len(grids)} carrés locator"
            + (f" (VUCC 50 : 6 m {vhf['6m']}, 2 m {vhf['2m']}, 70 cm {vhf['70cm']})" if any(vhf.values()) else "")
            + (f"\nPays par bande : {best}" if best else "")
            + f"\n{sum(1 for d in ent.values() if d['conf'])} pays DXCC confirmés par eQSL ou LoTW "
              "(✔ confirmé, ✓ contacté ; Carnet > Relever les confirmations).")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        b = bb.addButton("Exporter en CSV…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.export_csv(tabs))
        v.addWidget(bb)

    def _charts(self, rows, bandmode, conts, names):
        import datetime
        from .charts import BarChart
        w = QWidget()
        g = QGridLayout(w)
        today = datetime.date.today()
        months = []
        y, m = today.year, today.month
        for _ in range(12):
            months.append(f"{y:04d}{m:02d}")
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        months.reverse()
        per_month = collections.Counter((r.get("qso_date") or "")[:6] for r in rows)
        mois = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        c1 = BarChart("QSO par mois (12 derniers mois)")
        c1.set_data([(mois[int(k[4:]) - 1], per_month.get(k, 0), f"{mois[int(k[4:]) - 1]} {k[:4]}") for k in months])
        days = [(today - datetime.timedelta(days=i)) for i in range(29, -1, -1)]
        per_day = collections.Counter(r.get("qso_date") or "" for r in rows)
        c2 = BarChart("QSO par jour (30 derniers jours)")
        c2.set_data([(d.strftime("%d/%m"), per_day.get(d.strftime("%Y%m%d"), 0), d.strftime("%d/%m/%Y")) for d in days])
        per_band = collections.Counter()
        per_mode = collections.Counter()
        for (b, md), n in bandmode.items():
            per_band[b or "?"] += n
            per_mode[md or "?"] += n
        c3 = BarChart("QSO par bande")
        c3.set_data([(b, per_band[b]) for b in BANDS if per_band.get(b)]
                    + [(b, n) for b, n in per_band.items() if b not in BANDS])
        c4 = BarChart("QSO par mode")
        c4.set_data(sorted(per_mode.items(), key=lambda x: -x[1])[:12])
        c5 = BarChart("QSO par continent")
        c5.set_data([(k, conts.get(k, 0), n) for k, n in names.items()])
        g.addWidget(c1, 0, 0)
        g.addWidget(c2, 0, 1)
        g.addWidget(c3, 1, 0)
        g.addWidget(c4, 1, 1)
        g.addWidget(c5, 2, 0)
        b = QPushButton("Voir mes QSO sur la carte")
        b.clicked.connect(self._show_map)
        g.addWidget(b, 2, 1, Qt.AlignCenter)
        return w

    def _show_map(self):
        mp = getattr(self.win, "mapdock", None)
        if not mp:
            return
        mp.ck["log"].setChecked(True)
        mp.cb_log.setCurrentIndex(3)
        btn = getattr(self.win, "b_map", None)
        if btn:
            btn.setChecked(True)
        mp.show()
        mp.raise_()
        self.accept()

    def export_csv(self, tabs):
        import csv
        import os
        from .logbook import data_dir
        w = tabs.currentWidget()
        tables = [w] if isinstance(w, QTableWidget) else w.findChildren(QTableWidget)
        if not tables:
            QMessageBox.information(self, "Exporter", "Choisissez un onglet avec un tableau (DXCC, zones…).")
            return
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
