"""Modifier une même colonne pour plusieurs QSO du carnet JCFLog intégré.

- Sélectionner plusieurs QSO (Ctrl+clic, Maj+clic), puis clic droit > « Modifier la colonne … pour
  les QSO sélectionnés » : une seule valeur, appliquée à tous (date, heure, fréquence, mode,
  « Mon activité », « Mon indicatif », références POTA/SOTA, QSL…).
- Ou F2 sur une cellule : si plusieurs QSO sont sélectionnés, la nouvelle valeur peut être
  appliquée à tous.
- Les valeurs sont remises au format du carnet : date AAAAMMJJ, heure HHMMSS, fréquence en MHz
  (la bande suit), indicatifs et locators en majuscules, références d'activité rangées dans
  les bons champs ADIF (MY_SIG / MY_SIG_INFO, SIG / SIG_INFO).
"""
import re

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QMessageBox, QVBoxLayout,
)

from .logbook import guess_activity

UPPER = {"call", "station_callsign", "operator", "mode", "submode", "qsl_via", "iota", "cont",
         "pota_ref", "sota_ref", "wwff_ref", "sig", "sig_info", "my_sig", "my_sig_info", "state"}
QSL_KEYS = {"qsl_sent", "qsl_rcvd", "lotw_qsl_rcvd", "eqsl_qsl_rcvd", "lotw_qsl_sent", "eqsl_qsl_sent"}
ACT_KEYS = {"pota_ref": "POTA", "sota_ref": "SOTA", "wwff_ref": "WWFF"}
KNOWN_SIGS = ("POTA", "SOTA", "WWFF", "BOTA", "IOTA", "COTA", "LLOTA", "GMA", "HEMA", "SIOTA")


def _date(t):
    t = t.strip()
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", t) or None
    if m:
        y, mo, d = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", t)
        if not m:
            raise ValueError("date attendue sous la forme 2026-11-06 ou 06/11/2026")
        d, mo, y = m.groups()
    import datetime
    try:
        datetime.date(int(y), int(mo), int(d))        # vérifie que la date existe
    except ValueError:
        raise ValueError("cette date n'existe pas")
    return f"{int(y):04d}{int(mo):02d}{int(d):02d}"


def _time(t):
    digits = re.sub(r"\D", "", t)
    if len(digits) in (3, 5):
        digits = "0" + digits
    if len(digits) not in (4, 6):
        raise ValueError("heure attendue sous la forme 14:32 ou 14:32:05 (UTC)")
    digits = (digits + "00")[:6]
    h, mi, s = int(digits[:2]), int(digits[2:4]), int(digits[4:])
    if h > 23 or mi > 59 or s > 59:
        raise ValueError("heure impossible")
    return digits


def _freq(t):
    s = t.strip().lower().replace(",", ".").replace(" ", "")
    unit = 1.0
    for suf, u in (("ghz", 1000.0), ("mhz", 1.0), ("khz", 0.001), ("hz", 1e-6)):
        if s.endswith(suf):
            s, unit = s[:-len(suf)], u
            break
    try:
        f = float(s) * unit
    except ValueError:
        raise ValueError("fréquence attendue en MHz, par exemple 14.074")
    if unit == 1.0 and f > 1000 and not t.lower().strip().endswith("mhz"):
        from .jcflog import geo
        if not geo.band_of(f) and geo.band_of(f / 1000.0):
            f /= 1000.0                                # 14074 tapé en kHz → 14.074 MHz
    if f <= 0:
        raise ValueError("fréquence impossible")
    return f


def _split_ref(text):
    """« SOTA F/AM-123 » → ("SOTA", "F/AM-123") ; « FR-0019 » → ("POTA", "FR-0019")."""
    t = text.strip().upper()
    if not t:
        return "", ""
    parts = t.split(None, 1)
    if len(parts) == 2 and parts[0] in KNOWN_SIGS:
        return parts[0], parts[1].strip()
    return guess_activity(t), t


def convert(key, text, row):
    """Valeur saisie → champs à écrire dans le carnet (dict). ValueError si la valeur est fausse."""
    t = "" if text is None else str(text).strip()
    if key == "qso_date":
        if not t:
            raise ValueError("la date ne peut pas être vide")
        return {"qso_date": _date(t)}
    if key in ("time_on", "time_off"):
        if not t:
            if key == "time_on":
                raise ValueError("l'heure ne peut pas être vide")
            return {key: ""}
        return {key: _time(t)}
    if key == "freq":
        if not t:
            return {"freq": ""}
        from .jcflog import geo
        f = _freq(t)
        upd = {"freq": "%.6f" % f}
        b = geo.band_of(f)
        if b:
            upd["band"] = b
        return upd
    if key == "band":
        return {"band": t.lower().replace(" ", "")}
    if key == "gridsquare" or key == "my_gridsquare":
        g = t.replace(" ", "")
        return {key: g[:2].upper() + g[2:4] + g[4:6].lower() + g[6:]}
    if key == "my_sig_info":                           # colonne « Mon activité »
        sig, ref = _split_ref(t)
        upd = {"my_sig": sig, "my_sig_info": ref, "my_pota_ref": "", "my_sota_ref": "", "my_wwff_ref": ""}
        col = {"POTA": "my_pota_ref", "SOTA": "my_sota_ref", "WWFF": "my_wwff_ref"}.get(sig)
        if col:
            upd[col] = ref
        return upd
    if key == "station_callsign":                      # colonne « Mon indicatif »
        return {"station_callsign": t.upper()}
    if key in ACT_KEYS:                                # références du correspondant
        v = t.upper()
        upd = {key: v}
        sig = ACT_KEYS[key]
        if v:
            if not row.get("sig") or (row.get("sig") or "").upper() == sig:
                upd.update(sig=sig, sig_info=v)
        elif (row.get("sig") or "").upper() == sig:
            upd.update(sig="", sig_info="")
        return upd
    if key in QSL_KEYS:
        v = t[:1].upper()
        if v and v not in "YNRIQV":
            raise ValueError("QSL : Y (oui), N (non), R (demandée), Q (en file) ou I (ignorer)")
        return {key: v}
    return {key: t.upper() if key in UPPER else t}


class MultiEdit(QObject):
    def __init__(self, dock, jcf, proxy):
        super().__init__(jcf)
        self.dock, self.win, self.j, self.proxy = dock, dock.win, jcf, proxy
        self._col = None
        self._keep, self._keep_n = [], 0
        from .jcflog.main import COLS
        self.cols = COLS
        if proxy is not None:
            proxy.on_edit = self.on_cell_edit
        jcf.table.viewport().installEventFilter(self)
        self.act = QAction("Modifier une colonne pour les QSO sélectionnés…", jcf.table)
        self.act.triggered.connect(self.edit_column)
        acts = jcf.table.actions()
        jcf.table.insertAction(acts[1] if len(acts) > 1 else None, self.act)
        jcf.model.modelReset.connect(self._reselect)

    # --- repérer la colonne du clic droit -----------------------------------------------------
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonPress:
            idx = self.j.table.indexAt(ev.position().toPoint())
            if idx.isValid():
                self._col = idx.column()
                self._update_label()
        return False

    def _update_label(self):
        n = len(self.j.sel_rows())
        col = self._current_col()
        title = self.cols[col][1] if col is not None else "…"
        self.act.setText(f"Modifier la colonne « {title} » pour {'les ' + str(n) + ' QSO sélectionnés' if n > 1 else 'ce QSO'}…")

    def _current_col(self):
        if self._col is not None and self._col < len(self.cols):
            return self._col
        c = self.j.table.currentIndex().column()
        return c if 0 <= c < len(self.cols) else None

    # --- F2 sur une cellule ------------------------------------------------------------------
    def on_cell_edit(self, row, key, value):
        cur = (self.display(row, key) or "")
        if value in (cur, row.get(key) or ""):
            return True
        sel = self.j.sel_rows()
        ids = [r["id"] for r in sel]
        # la question est posée après la fermeture de l'éditeur de cellule
        QTimer.singleShot(0, lambda: self._ask_cell(row, key, value, sel if row["id"] in ids else [row]))
        return True

    def _ask_cell(self, row, key, value, rows):
        title = dict(self.cols).get(key, key)
        if len(rows) > 1:
            mb = QMessageBox(QMessageBox.Question, "Modifier plusieurs QSO",
                             f"Mettre « {value or '(vide)'} » dans la colonne « {title} » de :", parent=self.j)
            b_all = mb.addButton(f"Les {len(rows)} QSO sélectionnés", QMessageBox.YesRole)
            b_one = mb.addButton("Ce QSO seulement", QMessageBox.NoRole)
            mb.addButton("Annuler", QMessageBox.RejectRole)
            mb.exec()
            if mb.clickedButton() is b_one:
                rows = [row]
            elif mb.clickedButton() is not b_all:
                return
        self.apply(rows, key, value)

    # --- clic droit > Modifier une colonne ---------------------------------------------------
    def edit_column(self):
        rows = self.j.sel_rows()
        if not rows:
            QMessageBox.information(self.j, "Modifier une colonne", "Sélectionnez d'abord un ou plusieurs QSO.")
            return
        d = QDialog(self.j)
        d.setWindowTitle("Modifier une colonne")
        v = QVBoxLayout(d)
        v.addWidget(QLabel(f"{len(rows)} QSO sélectionné{'s' if len(rows) > 1 else ''}."))
        f = QFormLayout()
        cb_col = QComboBox()
        for _k, lab in self.cols:
            cb_col.addItem(lab)
        cur = self._current_col()
        cb_col.setCurrentIndex(cur if cur is not None else 0)
        cb_val = QComboBox()
        cb_val.setEditable(True)
        cb_val.setMinimumWidth(260)
        cb_val.setInsertPolicy(QComboBox.NoInsert)
        hint = QLabel()
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("Colonne", cb_col)
        f.addRow("Nouvelle valeur", cb_val)
        v.addLayout(f)
        v.addWidget(hint)
        HINTS = {
            "qso_date": "Date UTC : 2026-11-06 ou 06/11/2026.",
            "time_on": "Heure UTC : 14:32 ou 14:32:05.",
            "freq": "Fréquence en MHz (14.074) ; la bande est mise à jour avec.",
            "my_sig_info": "Votre activation : « SOTA F/AM-123 », « POTA FR-0019 », « BOTA B/F-0123 »… "
                           "Une référence seule suffit si son type se devine. Vide = aucune activation.",
            "station_callsign": "L'indicatif que vous utilisiez (F4JCF, F4JCF/P…).",
            "pota_ref": "Référence POTA du correspondant (FR-0019…).",
            "sota_ref": "Référence SOTA du correspondant (F/AM-123…).",
        }

        def fill(i):
            key = self.cols[i][0]
            seen = []
            first = self.display(rows[0], key) or ""
            for r in rows + self.j.model.rows:
                t = self.display(r, key) or ""
                if t and t not in seen:
                    seen.append(t)
                if len(seen) >= 150:
                    break
            cb_val.clear()
            cb_val.addItems(seen)
            cb_val.setEditText(first)
            same = all((self.display(r, key) or "") == first for r in rows)
            h = HINTS.get(key, "Laisser vide pour effacer.")
            if QSL_KEYS & {key}:
                h = "Y = oui, N = non, R = demandée, Q = en file, I = ignorer."
            if not same:
                h += "  (Les QSO sélectionnés ont aujourd'hui des valeurs différentes.)"
            hint.setText(h)

        cb_col.currentIndexChanged.connect(fill)
        fill(cb_col.currentIndex())
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(f"Appliquer à {len(rows)} QSO")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        cb_val.setFocus()
        if d.exec() != QDialog.Accepted:
            return
        self.apply(rows, self.cols[cb_col.currentIndex()][0], cb_val.currentText())

    # --- écriture ----------------------------------------------------------------------------
    def display(self, row, key):
        from .jcflogtools import display
        t = display(row, key)
        if t is not None:
            return t
        v = row.get(key) or ""
        if key == "qso_date" and len(v) == 8:
            return f"{v[:4]}-{v[4:6]}-{v[6:]}"
        if key in ("time_on", "time_off") and len(v) >= 4:
            return f"{v[:2]}:{v[2:4]}" + (f":{v[4:6]}" if len(v) >= 6 and v[4:6] != "00" else "")
        return v

    def apply(self, rows, key, value):
        from .jcflog.db import FIELDS
        title = dict(self.cols).get(key, key)
        changes = []
        try:
            for r in rows:
                upd = {k: v for k, v in convert(key, value, r).items() if k in FIELDS}
                upd = {k: v for k, v in upd.items() if (r.get(k) or "") != v}
                if upd:
                    changes.append((r["id"], upd))
        except ValueError as e:
            QMessageBox.warning(self.j, "Modifier une colonne", f"« {value} » : {e}.")
            return
        if not changes:
            self.j.statusBar().showMessage("Rien à modifier : les QSO avaient déjà cette valeur.", 4000)
            return
        db = self.j.db
        with db.c:
            for qid, upd in changes:
                db.c.execute(f"UPDATE qso SET {', '.join(k + ' = ?' for k in upd)} WHERE id = ?",
                             list(upd.values()) + [qid])
        self._keep, self._keep_n = [r["id"] for r in rows], 3
        try:
            self.win.log.changed.emit()      # carte, diplômes, envois… de CAT Pilot
        except Exception:
            pass
        self.j.apply_filter()
        n = len(changes)
        self.j.statusBar().showMessage(f"Colonne « {title} » modifiée pour {n} QSO.", 6000)

    def _reselect(self):
        """Après le rechargement du tableau, les mêmes QSO restent sélectionnés."""
        if not self._keep or self._keep_n <= 0:
            return
        self._keep_n -= 1
        QTimer.singleShot(0, self._do_reselect)

    def _do_reselect(self):
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        t, m = self.j.table, self.j.table.model()
        keep = set(self._keep)
        sel = QItemSelection()
        rows = self.j.model.rows
        first = None
        for i, r in enumerate(rows):
            if r.get("id") in keep:
                a, b = m.index(i, 0), m.index(i, m.columnCount() - 1)
                sel.select(a, b)
                first = first if first is not None else i
        if first is None:
            return
        sm = t.selectionModel()
        sm.select(sel, QItemSelectionModel.ClearAndSelect)
        col = self._current_col() or 0
        sm.setCurrentIndex(m.index(first, col), QItemSelectionModel.NoUpdate)
        t.scrollTo(m.index(first, col))
