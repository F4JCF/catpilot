"""Compléments du carnet JCFLog intégré à CAT Pilot.

- Colonnes « Mon indicatif » et « Mon activité » (références de mes activations POTA, SOTA,
  BOTA, WWFF…), et colonnes POTA/SOTA/WWFF remplies aussi avec les références saisies dans
  CAT Pilot (champs SIG / SIG_INFO).
- « Compléter les QSO (lookup)… » : nom, QTH, locator, département et QSL via ajoutés aux QSO
  existants, avec la recherche d'indicatif de CAT Pilot (QRZ.com, HamQTH, QRZCQ, callook…).
"""
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressDialog, QRadioButton,
    QVBoxLayout,
)

MY_COLS = [("station_callsign", "Mon indicatif", "time_on"), ("my_sig_info", "Mon activité", "gridsquare")]


def patch_columns():
    """À appeler avant la création de la fenêtre JCFLog : colonnes et champs supplémentaires."""
    from .jcflog import main as jm
    from .jcflog.db import FIELDS
    for f in ("my_sig", "my_sig_info", "my_pota_ref", "my_sota_ref", "my_wwff_ref"):
        if f not in FIELDS:
            FIELDS.append(f)
    keys = [k for k, _ in jm.COLS]
    for key, title, after in MY_COLS:
        if key in keys:
            continue
        pos = keys.index(after) + 1 if after in keys else len(keys)
        jm.COLS.insert(pos, (key, title))
        keys.insert(pos, key)


def display(row, key):
    """Texte affiché pour les colonnes ajoutées ou complétées (None = affichage normal)."""
    if key == "my_sig_info":
        refs = []
        sig, info = (row.get("my_sig") or "").upper(), (row.get("my_sig_info") or "").strip()
        if info:
            refs.append(f"{sig} {info}".strip())
        for k, lab in (("my_pota_ref", "POTA"), ("my_sota_ref", "SOTA"), ("my_wwff_ref", "WWFF")):
            v = (row.get(k) or "").strip()
            if v and v not in info:
                refs.append(f"{lab} {v}")
        return " · ".join(refs)
    if key == "station_callsign":
        return (row.get("station_callsign") or row.get("operator") or "").upper()
    if key in ("pota_ref", "sota_ref", "wwff_ref"):
        v = row.get(key) or ""
        if not v and (row.get("sig") or "").upper() == key[:4].upper():
            v = row.get("sig_info") or ""
        return v
    return None


# --- compléter les QSO existants --------------------------------------------------------------
def _missing(r, fields):
    return any(not (r.get(f) or "").strip() for f in fields)


class Filler(QObject):
    progress = Signal(int, int, str)       # fait, total, indicatif
    done = Signal(int, int, str)           # QSO complétés, indicatifs sans fiche, message

    def __init__(self, win, rows, fields, overwrite):
        super().__init__()
        self.win, self.rows, self.fields, self.overwrite = win, rows, fields, overwrite
        self.stop = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        from .departements import for_station
        hq = self.win.logdock.hamqth
        log = self.win.log
        calls = []
        for r in self.rows:
            c = (r.get("call") or "").strip().upper()
            if c and c not in calls:
                calls.append(c)
        by_call = {}
        for r in self.rows:
            by_call.setdefault((r.get("call") or "").strip().upper(), []).append(r)
        updated = notfound = 0
        err = ""
        for i, call in enumerate(calls):
            if self.stop:
                break
            self.progress.emit(i, len(calls), call)
            cached = call in hq.cache
            try:
                info = hq.lookup_now(call)
                if (not isinstance(info, dict) or not info.get("name")) and "/" in call:
                    base = max(call.split("/"), key=len)
                    alt = hq.lookup_now(base)
                    if isinstance(alt, dict):
                        info = alt
            except Exception as e:
                info, err = None, str(e)
            if not isinstance(info, dict):
                notfound += 1
                if isinstance(info, str) and not err:
                    err = info
                continue
            grid = str(info.get("grid") or "")
            if grid:
                grid = grid[:2].upper() + grid[2:4] + grid[4:6].lower()
            vals = {"name": info.get("name") or "", "qth": info.get("qth") or "", "gridsquare": grid,
                    "qsl_via": str(info.get("qsl_via") or "").upper()}
            if "state" in self.fields:
                code, _n = for_station(call, info.get("zip", ""), info.get("lat"), info.get("lon"), grid)
                vals["state"] = code
            for r in by_call.get(call, []):
                upd = {}
                for f in self.fields:
                    v = vals.get(f, "")
                    if v and (self.overwrite or not (r.get(f) or "").strip()) and v != (r.get(f) or ""):
                        upd[f] = v
                if upd:
                    log.update(r["id"], upd, notify=False)
                    updated += 1
            if not cached:
                time.sleep(0.4)             # ne pas surcharger les sites de recherche
        self.progress.emit(len(calls), len(calls), "")
        self.done.emit(updated, notfound, err)


class FillDialog(QDialog):
    FIELDS = [("name", "Nom"), ("qth", "QTH"), ("gridsquare", "Locator"), ("state", "Département (France)"),
              ("qsl_via", "QSL via")]

    def __init__(self, parent, n_sel, n_missing):
        super().__init__(parent)
        self.setWindowTitle("Compléter les QSO (lookup)")
        v = QVBoxLayout(self)
        t = QLabel("Recherche chaque indicatif (QRZ.com, HamQTH, QRZCQ, callook.info, page publique QRZCQ, "
                   "commune pour la France) et complète les QSO du carnet. Une recherche par indicatif, "
                   "environ 2 par seconde.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        v.addWidget(t)
        self.r_sel = QRadioButton(f"Les QSO sélectionnés ({n_sel})")
        self.r_all = QRadioButton(f"Tous les QSO auxquels il manque une information ({n_missing})")
        g = QButtonGroup(self)
        g.addButton(self.r_sel)
        g.addButton(self.r_all)
        (self.r_sel if n_sel > 1 else self.r_all).setChecked(True)
        self.r_sel.setEnabled(n_sel > 0)
        v.addWidget(self.r_sel)
        v.addWidget(self.r_all)
        v.addWidget(QLabel("Informations à ajouter :"))
        self.cks = {}
        for k, lab in self.FIELDS:
            ck = QCheckBox(lab)
            ck.setChecked(True)
            v.addWidget(ck)
            self.cks[k] = ck
        self.ck_over = QCheckBox("Remplacer aussi les informations déjà présentes")
        v.addWidget(self.ck_over)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Lancer")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def fields(self):
        return [k for k, ck in self.cks.items() if ck.isChecked()]


class Tools:
    def __init__(self, dock, jcf):
        self.dock, self.win, self.j = dock, dock.win, jcf
        self.filler = None
        a = QAction("Compléter les QSO (lookup : nom, QTH, locator, département)…", jcf)
        a.triggered.connect(self.fill)
        added = False
        for act in jcf.menuBar().actions():
            menu = act.menu()
            if menu and act.text().replace("&", "").startswith("Carnet"):
                menu.addSeparator()
                menu.addAction(a)
                added = True
                break
        if not added:
            jcf.menuBar().addAction(a)
        b = QAction("Compléter ces QSO (lookup)…", jcf.table)
        b.triggered.connect(self.fill)
        jcf.table.addAction(b)

    def fill(self):
        if self.filler is not None:
            QMessageBox.information(self.j, "Compléter les QSO", "Une recherche est déjà en cours.")
            return
        if getattr(self.win.logdock, "hamqth", None) is None:
            return
        sel = self.j.sel_rows()
        d = FillDialog(self.j, len(sel), 0)
        fields_all = [k for k, _l in FillDialog.FIELDS]
        allrows = self.j.db.query()
        d.r_all.setText(f"Tous les QSO auxquels il manque une information "
                        f"({sum(1 for r in allrows if _missing(r, ['name', 'qth', 'gridsquare']))})")
        if d.exec() != QDialog.Accepted:
            return
        fields = d.fields()
        if not fields:
            return
        rows = sel if d.r_sel.isChecked() else [r for r in allrows if _missing(r, fields)]
        if not d.ck_over.isChecked():
            rows = [r for r in rows if _missing(r, fields)]
        if not rows:
            QMessageBox.information(self.j, "Compléter les QSO", "Rien à compléter : ces QSO sont déjà renseignés.")
            return
        n_calls = len({(r.get("call") or "").upper() for r in rows})
        if n_calls > 300 and QMessageBox.question(
                self.j, "Compléter les QSO",
                f"{n_calls} indicatifs à rechercher (environ {n_calls // 120 + 1} min). Continuer ?") != QMessageBox.Yes:
            return
        self.pd = QProgressDialog("Recherche des indicatifs…", "Arrêter", 0, n_calls, self.j)
        self.pd.setWindowTitle("Compléter les QSO")
        self.pd.setWindowModality(Qt.WindowModal)
        self.pd.setMinimumDuration(0)
        self.filler = Filler(self.win, rows, fields, d.ck_over.isChecked())
        self.filler.progress.connect(self._progress)
        self.filler.done.connect(self._done)
        self.pd.canceled.connect(lambda: setattr(self.filler, "stop", True) if self.filler else None)
        self.filler.start()

    def _progress(self, i, n, call):
        if self.pd:
            self.pd.setMaximum(n)
            self.pd.setValue(i)
            if call:
                self.pd.setLabelText(f"Recherche de {call}  ({i + 1} / {n})")

    def _done(self, updated, notfound, err):
        self.filler = None
        if self.pd:
            self.pd.close()
            self.pd = None
        self.win.log.changed.emit()
        try:
            self.j.apply_filter()
        except Exception:
            pass
        msg = f"{updated} QSO complété{'s' if updated > 1 else ''}."
        if notfound:
            msg += f"\n{notfound} indicatif{'s' if notfound > 1 else ''} sans fiche trouvée."
        if err and not updated:
            msg += f"\n\n{err}"
        if not (self.win.settings.value("hamqth_user", "") or self.win.settings.value("qrz_user", "")
                or self.win.settings.value("qrzcq_user", "")):
            msg += ("\n\nAstuce : avec un compte gratuit HamQTH ou QRZCQ (Carnet > Réglages de CAT Pilot), "
                    "les noms et locators sont beaucoup plus souvent trouvés.")
        QMessageBox.information(self.j, "Compléter les QSO", msg)
