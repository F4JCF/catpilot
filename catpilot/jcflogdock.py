"""Onglet « Carnet » : le carnet de trafic JCFLog intégré à CAT Pilot.

- Une seule base de QSO : JCFLog travaille directement dans Documents/CATPilot/carnet.sqlite,
  la même table que le reste de CAT Pilot (FT8/FT4, WSJT-X, envois QRZ/eQSL/Club Log/LoTW,
  diplômes, carte, étiquettes QSL, sauvegardes).
- Le poste reste piloté par CAT Pilot seul : JCFLog n'ouvre pas le port série, il reçoit
  la fréquence et le mode de CAT Pilot, et ses boutons QSY/bandes passent par CAT Pilot.
- L'écoute WSJT-X de JCFLog est désactivée (CAT Pilot a déjà la sienne, même port UDP).
"""
import os
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QDockWidget, QLabel, QVBoxLayout, QWidget

from .logbook import data_dir, guess_activity

_ACTIVITY_COLS = {"POTA": "pota_ref", "SOTA": "sota_ref", "WWFF": "wwff_ref", "IOTA": "iota"}


def shared_db_class():
    """Base JCFLog branchée sur le carnet de CAT Pilot (et ses signaux)."""
    from .jcflog.db import DB, FIELDS

    class SharedDB(DB):
        def __init__(self, log):
            self.log = log
            super().__init__(log.path)

        @staticmethod
        def _mirror(q):
            """Références POTA/SOTA/WWFF de JCFLog → champs SIG/SIG_INFO lus par CAT Pilot."""
            if q.get("sig"):
                return q
            for sig, col in (("POTA", "pota_ref"), ("SOTA", "sota_ref"), ("WWFF", "wwff_ref")):
                if q.get(col):
                    q = dict(q, sig=sig, sig_info=q[col])
                    break
            return q

        def add(self, q):
            qid = super().add(self._mirror(q))
            if qid:
                self.log.changed.emit()
                self.log.added.emit(qid)     # envoi automatique QRZ/eQSL/Club Log/LoTW de CAT Pilot
            return qid

        def add_many(self, qsos, skip_dupes=True):
            last = self.c.execute("SELECT COALESCE(MAX(id), 0) FROM qso").fetchone()[0]
            n = super().add_many([self._mirror(q) for q in qsos], skip_dupes)
            if n:
                # QSO importés : déjà dans les carnets en ligne, CAT Pilot ne les renvoie pas
                self.c.execute("UPDATE qso SET up_qrz = 'import', up_eqsl = 'import', up_clublog = 'import', "
                               "up_lotw = 'import' WHERE id > ?", (last,))
                self.c.commit()
                self.log.changed.emit()
            return n

        def update(self, qid, q):
            super().update(qid, q)
            self.log.changed.emit()

        def delete(self, ids):
            super().delete(ids)
            self.log.changed.emit()

    SharedDB.FIELDS = FIELDS
    return SharedDB


class RigBridge(QObject):
    """Remplace la liaison CAT de JCFLog : tout passe par CAT Pilot."""
    status = Signal(float, str, str)   # MHz, mode, puissance
    state = Signal(bool, str)

    def __init__(self, win):
        super().__init__()
        self.win = win

    def start(self, cfg=None):
        self.state.emit(True, "Piloté par CAT Pilot")

    def stop(self):
        pass

    def set_freq(self, mhz):
        try:
            self.win.ctrl.set_freq(int(round(float(mhz) * 1e6)))
        except Exception:
            pass

    def set_mode(self, mode):
        try:
            self.win.ctrl.set_mode(mode)
        except Exception:
            pass

    def ptt(self, on):
        try:
            self.win.ctrl.set_ptt(bool(on))
        except Exception:
            pass

    def on_state(self, st):
        pwr = st.p.get("pwr") if isinstance(st.p, dict) else None
        if st.freq:
            self.status.emit(st.freq / 1e6, st.mode or "", str(pwr) if pwr else "")


class NoWsjtx(QObject):
    """L'écoute WSJT-X est faite par CAT Pilot (onglet WSJT-X)."""
    status = Signal(dict)
    decode = Signal(dict)
    logged = Signal(str)

    def start(self, *a, **k):
        pass

    def stop(self):
        pass

    def reply(self, *a):
        pass


class JCFLogDock(QDockWidget):
    """Panneau « Carnet » : la fenêtre JCFLog complète, créée à la première ouverture."""

    def __init__(self, win):
        super().__init__("Carnet (JCFLog)", win)
        self.setObjectName("dock_jcflog")
        self.win = win
        self.jcf = None
        self.bridge = RigBridge(win)
        self._pending = None
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        self._wait = QLabel("Ouverture du carnet…")
        self._wait.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._wait)
        self._lay = lay
        self.setWidget(holder)
        self._refresh = QTimer(self, singleShot=True, interval=300)
        self._refresh.timeout.connect(self._reload)
        win.ctrl.state_changed.connect(self.bridge.on_state)
        win.log.changed.connect(lambda: self.jcf and self._refresh.start())
        self.visibilityChanged.connect(lambda v: v and self.ensure())

    # --- création de la fenêtre JCFLog -----------------------------------------------------
    def ensure(self):
        if self.jcf is not None:
            return self.jcf
        from .jcflog import main as jm
        SharedDB = shared_db_class()
        db = SharedDB(self.win.log)
        self._default_profile(db)
        saved = {k: getattr(jm, k) for k in ("DB", "Rig", "WSJTX")}
        jm.DB = lambda *a, **k: db
        jm.Rig = lambda *a, **k: self.bridge
        jm.WSJTX = NoWsjtx
        # pas de carte web intégrée : CAT Pilot a déjà son onglet Carte
        web = sys.modules.get("PySide6.QtWebEngineWidgets", False)
        sys.modules["PySide6.QtWebEngineWidgets"] = None
        try:
            jcf = jm.Main()
        finally:
            for k, v in saved.items():
                setattr(jm, k, v)
            if web is False:
                sys.modules.pop("PySide6.QtWebEngineWidgets", None)
            else:
                sys.modules["PySide6.QtWebEngineWidgets"] = web
        jcf.setWindowFlags(Qt.Widget)
        jcf._start_max = False            # intégré au panneau : jamais en plein écran
        # le panneau « Transceiver » de JCFLog est remplacé par la face avant de CAT Pilot
        for d in jcf.docks:
            if d.objectName() == "Transceiver":
                d.hide()
                d.toggleViewAction().setVisible(False)
        if not db.get("geometry"):
            # premier affichage : horloge et cluster déjà présents dans CAT Pilot (UTC, onglet Spots)
            # → masqués pour laisser la place au carnet ; menu « Fenêtre » de JCFLog pour les rouvrir
            for d in jcf.docks:
                if d.objectName() in ("Horloge", "DX Cluster"):
                    d.hide()
        self._wait.hide()
        self._lay.addWidget(jcf)
        jcf.show()
        self.jcf = jcf
        self.bridge.start()
        st = getattr(self.win, "_last", None)
        if st is not None:
            self.bridge.on_state(st)
        if self._pending:
            self.prefill(*self._pending)
            self._pending = None
        return jcf

    def _default_profile(self, db):
        """Premier lancement : profil de station repris des réglages de CAT Pilot."""
        if db.get("profiles"):
            return
        s = self.win.settings
        call = (s.value("mycall", "") or "").upper()
        if not call:
            return
        grid = (s.value("my_locator", "") or "").upper()
        db.set("profiles", [{"name": call, "station_callsign": call, "operator": call, "my_gridsquare": grid}])

    def _reload(self):
        if self.jcf:
            try:
                self.jcf.apply_filter()
            except Exception:
                pass

    # --- appels depuis CAT Pilot (spots, FT8, menus…) ----------------------------------------
    def prefill(self, call, ref="", mode=None):
        if self.jcf is None:
            self._pending = (call, ref, mode)
            return
        j = self.jcf
        j.reset()
        j.e_call.setText(call.upper())
        j.call_edited(call.upper())
        if ref:
            col = _ACTIVITY_COLS.get(guess_activity(ref))
            if col and col in j.d:
                j.d[col].setText(ref.upper())
        if mode:
            j.e_mode.setCurrentText(mode)
        j.e_call.setFocus()

    def set_call(self, call):
        """Indicatif reçu (décodeur CW…) : placé dans la saisie sans effacer le reste."""
        if self.jcf is None:
            self._pending = (call, "", None)
            return
        self.jcf.e_call.setText(call.upper())
        self.jcf.call_edited(call.upper())

    def focus_call(self):
        if self.ensure():
            self.raise_()
            self.jcf.e_call.setFocus()

    def import_adif(self):
        self.win.b_log.setChecked(True)
        self.ensure().import_adif()

    def export_adif(self):
        self.ensure().export_all()

    def shutdown(self):
        """À la fermeture de CAT Pilot : mémoriser la disposition et couper le cluster de JCFLog."""
        if not self.jcf:
            return
        try:
            self.jcf.db.set("geometry", bytes(self.jcf.saveState()).hex())
            self.jcf.clu.disconnect_()
        except Exception:
            pass
