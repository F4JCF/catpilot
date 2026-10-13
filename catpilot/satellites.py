"""Suivi de satellites amateurs : passages, correction Doppler du poste, rotor.

Données : orbites (TLE) de CelesTrak, transpondeurs de SatNOGS, mises en cache
dans Documents\\CATPilot\\satellites et actualisées une fois par jour.
Le poste reçoit sur le VFO A et émet sur le VFO B (split) : fonctionnement
en semi-duplex, comme le permettent le FT-991A et l'IC-705.
"""
import datetime
import json
import os
import re
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDockWidget, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .orbit import Satellite, doppler, parse_tle, uplink

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"
TX_URL = "https://db.satnogs.org/api/transmitters/?format=json&status=active"
UA = {"User-Agent": f"CATPilot/{__version__}"}

# Transpondeurs de secours (si SatNOGS est injoignable). L'état des satellites change : à vérifier.
BUILTIN = [
    {"norad": 25544, "desc": "ISS — relais FM", "down": 437_800_000, "up": 145_990_000, "mode": "FM", "tone": 67.0},
    {"norad": 25544, "desc": "ISS — phonie FM (Région 1)", "down": 145_800_000, "up": 145_200_000, "mode": "FM"},
    {"norad": 25544, "desc": "ISS — APRS", "down": 145_825_000, "up": 145_825_000, "mode": "PKTFM"},
    {"norad": 27607, "desc": "SO-50 — relais FM", "down": 436_795_000, "up": 145_850_000, "mode": "FM", "tone": 67.0},
    {"norad": 43678, "desc": "PO-101 — relais FM", "down": 145_900_000, "up": 437_500_000, "mode": "FM", "tone": 141.3},
    {"norad": 44909, "desc": "RS-44 — transpondeur linéaire", "down": 435_610_000, "down_hi": 435_670_000,
     "up": 145_935_000, "up_hi": 145_995_000, "mode": "LINEAR", "invert": True},
    {"norad": 7530, "desc": "AO-7 — mode B linéaire", "down": 145_925_000, "down_hi": 145_975_000,
     "up": 432_125_000, "up_hi": 432_175_000, "mode": "LINEAR", "invert": True},
]
CTCSS_RE = re.compile(r"(\d{2,3}(?:[.,]\d)?)\s*Hz", re.I)


def sat_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot", "satellites")
    os.makedirs(d, exist_ok=True)
    return d


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_satnogs(items):
    out = []
    for t in items:
        if t.get("status") != "active" or not t.get("downlink_low") or not t.get("norad_cat_id"):
            continue
        if (t.get("service") or "Amateur") != "Amateur":
            continue
        mode = (t.get("mode") or "").upper()
        two_way = bool(t.get("uplink_low"))
        kind = ("LINEAR" if t.get("downlink_high") and t.get("uplink_high") and two_way
                else "FM" if mode.startswith("FM") else mode or "?")
        tone = None
        m = CTCSS_RE.search(t.get("description") or "")
        if m:
            try:
                tone = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
        out.append({"norad": int(t["norad_cat_id"]), "desc": t.get("description") or mode,
                    "down": int(t["downlink_low"]), "down_hi": t.get("downlink_high"),
                    "up": int(t["uplink_low"]) if two_way else None, "up_hi": t.get("uplink_high"),
                    "mode": kind, "invert": bool(t.get("invert")), "tone": tone})
    return out


class SatData(QObject):
    """Charge orbites et transpondeurs (cache local, actualisé chaque jour)."""
    loaded = Signal(object, object, str)     # {norad: Satellite}, [transpondeurs], message

    def load(self, force=False):
        threading.Thread(target=self._run, args=(force,), daemon=True).start()

    def _cached(self, name, url, max_age, force):
        path = os.path.join(sat_dir(), name)
        fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age
        if force or not fresh:
            try:
                txt = _get(url)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(txt)
                return txt, "actualisé"
            except Exception as e:
                if os.path.exists(path):
                    return open(path, encoding="utf-8").read(), f"hors ligne ({e}), cache utilisé"
                raise
        return open(path, encoding="utf-8").read(), "cache"

    def _run(self, force):
        msgs = []
        try:
            tle, how = self._cached("amateur.tle", TLE_URL, 86400, force)
            msgs.append(f"orbites : {how}")
            sats = {}
            for norad, (name, l1, l2) in parse_tle(tle).items():
                try:
                    sats[norad] = Satellite(name, l1, l2)
                except Exception:
                    pass
        except Exception as e:
            self.loaded.emit({}, BUILTIN, f"Orbites indisponibles : {e}")
            return
        try:
            js, how = self._cached("transmitters.json", TX_URL, 7 * 86400, force)
            txs = parse_satnogs(json.loads(js)) or BUILTIN
            msgs.append(f"transpondeurs : {how}")
        except Exception as e:
            txs = BUILTIN
            msgs.append(f"transpondeurs : liste intégrée ({e})")
        self.loaded.emit(sats, txs, " ; ".join(msgs))


class SatDock(QDockWidget):
    COLS = ["Date", "AOS", "LOS", "Élév. max", "Azimuts", "Durée"]

    def __init__(self, win):
        super().__init__("Satellites", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("satdock")
        s = win.settings
        self.sats, self.txs = {}, []
        self.tracking = False
        self.sat_down = None
        self.last_rx = self.last_tx = None
        self.last_set = 0.0
        self.data = SatData()
        self.data.loaded.connect(self.on_loaded)

        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("Filtrer (ex. ISS, SO-50, RS-44)")
        self.ed_filter.textChanged.connect(self.fill_sats)
        self.ck_twoway = QCheckBox("Seulement avec liaison montante")
        self.ck_twoway.setChecked(True)
        self.ck_twoway.toggled.connect(self.fill_sats)
        self.cb_sat = QComboBox()
        self.cb_sat.currentIndexChanged.connect(self.on_sat)
        self.cb_tx = QComboBox()
        self.cb_tx.currentIndexChanged.connect(self.on_tx)
        g.addWidget(self.ed_filter, 0, 0)
        g.addWidget(self.ck_twoway, 0, 1)
        g.addWidget(QLabel("Satellite"), 1, 0)
        g.addWidget(self.cb_sat, 1, 1)
        g.addWidget(QLabel("Transpondeur"), 2, 0)
        g.addWidget(self.cb_tx, 2, 1)
        v.addLayout(g)

        self.lb_live = QLabel("—")
        self.lb_live.setObjectName("value")
        self.lb_live.setWordWrap(True)
        v.addWidget(self.lb_live)
        self.lb_freqs = QLabel("")
        self.lb_freqs.setObjectName("info")
        self.lb_freqs.setWordWrap(True)
        v.addWidget(self.lb_freqs)

        h = QHBoxLayout()
        self.b_track = QPushButton("Suivre ce satellite")
        self.b_track.setCheckable(True)
        self.b_track.setToolTip("Règle le poste (VFO A réception, VFO B émission en split) et corrige "
                                "le Doppler en continu. Tournez le VFO pour vous déplacer dans un "
                                "transpondeur linéaire : l'émission suit.")
        self.b_track.toggled.connect(self.toggle_track)
        h.addWidget(self.b_track)
        self.ck_rotor = QCheckBox("Piloter le rotor")
        self.ck_rotor.setChecked(s.value("sat_rotor", "true") == "true")
        h.addWidget(self.ck_rotor)
        v.addLayout(h)

        h = QHBoxLayout()
        h.addWidget(QLabel("Passages au-dessus de"))
        self.sp_min = QSpinBox()
        self.sp_min.setRange(0, 60)
        self.sp_min.setValue(int(s.value("sat_min_el", 10)))
        self.sp_min.setSuffix("°")
        self.sp_min.valueChanged.connect(self.update_passes)
        h.addWidget(self.sp_min)
        h.addStretch()
        b = QPushButton("Actualiser les données")
        b.clicked.connect(lambda: self.data.load(force=True))
        h.addWidget(b)
        v.addLayout(h)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.tbl, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        self.setWidget(w)
        self.setMinimumWidth(460)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self._wanted = s.value("sat_last", "")
        self._loaded_once = False
        self.visibilityChanged.connect(self._first_load)

    def _first_load(self, vis):
        if vis and not self._loaded_once:
            self._loaded_once = True
            self.lb.setText("Chargement des orbites…")
            self.data.load()

    # --- données ----------------------------------------------------------------------------
    def on_loaded(self, sats, txs, msg):
        self.sats, self.txs = sats, txs
        self.lb.setText(f"{len(sats)} satellites — {msg}")
        self.fill_sats()

    def _txs_for(self, norad):
        return [t for t in self.txs if t["norad"] == norad and (t.get("up") or not self.ck_twoway.isChecked())]

    def fill_sats(self):
        flt = self.ed_filter.text().strip().upper()
        cur = self.cb_sat.currentData() or (int(self._wanted) if str(self._wanted).isdigit() else None)
        self.cb_sat.blockSignals(True)
        self.cb_sat.clear()
        for norad, sat in sorted(self.sats.items(), key=lambda x: x[1].name):
            if flt and flt not in sat.name.upper():
                continue
            if self.ck_twoway.isChecked() and not self._txs_for(norad):
                continue
            self.cb_sat.addItem(f"{sat.name}  ({norad})", norad)
        i = self.cb_sat.findData(cur)
        self.cb_sat.setCurrentIndex(max(0, i))
        self.cb_sat.blockSignals(False)
        self.on_sat()

    def on_sat(self):
        norad = self.cb_sat.currentData()
        self.cb_tx.blockSignals(True)
        self.cb_tx.clear()
        for t in (self._txs_for(norad) if norad else []):
            self.cb_tx.addItem(t["desc"][:60], t)
        self.cb_tx.blockSignals(False)
        self.on_tx()
        self.update_passes()

    def on_tx(self):
        t = self.cb_tx.currentData()
        self.sat_down = None
        if t:
            self.sat_down = (t["down"] + t["down_hi"]) // 2 if t.get("down_hi") else t["down"]

    def update_passes(self):
        sat = self.sats.get(self.cb_sat.currentData())
        pos = getattr(self.win, "station", None)
        self.tbl.setRowCount(0)
        if not sat or not pos:
            if not pos:
                self.lb.setText("Indiquez la position de la station (menu Poste) pour calculer les passages")
            return
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        try:
            ps = sat.passes(pos[0], pos[1], now, hours=24, min_el=self.sp_min.value())
        except ValueError as e:
            self.lb.setText(f"Orbite inutilisable : {e}")
            return
        off = datetime.datetime.now().astimezone().utcoffset()
        self.tbl.setRowCount(len(ps))
        for i, p in enumerate(ps[:15]):
            aos, los = p["aos"] + off, p["los"] + off
            dur = int((p["los"] - p["aos"]).total_seconds())
            vals = [aos.strftime("%d/%m"), "en cours" if p.get("ongoing") else aos.strftime("%H:%M:%S"),
                    los.strftime("%H:%M:%S"),
                    f"{p['max_el']:.0f}°", f"{p['az_aos']:.0f}° → {p['az_los']:.0f}°", f"{dur // 60} min {dur % 60:02d}"]
            for c, val in enumerate(vals):
                self.tbl.setItem(i, c, QTableWidgetItem(val))
        self.tbl.setRowCount(min(len(ps), 15))

    # --- temps réel ---------------------------------------------------------------------------
    def tick(self):
        sat = self.sats.get(self.cb_sat.currentData())
        pos = getattr(self.win, "station", None)
        if not sat or not pos or not self.isVisible() and not self.tracking:
            return
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        try:
            az, el, rng, rr = sat.look(pos[0], pos[1], now)
        except ValueError:
            return
        self.lb_live.setText(f"Azimut {az:.0f}°   Élévation {el:.1f}°   Distance {rng:.0f} km   "
                             f"Vitesse radiale {rr / 1000:+.2f} km/s" + ("   — VISIBLE" if el > 0 else ""))
        t = self.cb_tx.currentData()
        if not t or self.sat_down is None:
            self.lb_freqs.setText("")
            return
        if self.tracking:
            self._follow_user_tuning(t, rr)
        sat_up = self._sat_up(t)
        rx = doppler(self.sat_down, rr)
        tx = uplink(sat_up, rr) if sat_up else None
        txt = (f"Réception {rx / 1e6:.4f} MHz ({rx - self.sat_down:+.0f} Hz)"
               + (f"   Émission {tx / 1e6:.4f} MHz ({tx - sat_up:+.0f} Hz)" if tx else ""))
        self.lb_freqs.setText(txt.replace(".", ","))
        if self.tracking:
            self._apply(t, rx, tx)
            rot = getattr(self.win, "rotor", None)
            if self.ck_rotor.isChecked() and rot and rot.rotor.connected and el > -2:
                if rot.rotor.target is None or abs(rot.rotor.target[0] - az) > 2 or \
                        (rot.rotor.target[1] is not None and abs(rot.rotor.target[1] - el) > 2):
                    rot.go_az(az, max(0.0, el))

    def _sat_up(self, t):
        if not t.get("up"):
            return None
        if t.get("down_hi") and t.get("up_hi"):          # transpondeur linéaire
            if t.get("invert"):
                return t["up"] + (t["down_hi"] - self.sat_down)
            return t["up"] + (self.sat_down - t["down"])
        return t["up"]

    def _follow_user_tuning(self, t, rr):
        """Transpondeur linéaire : si l'opérateur a tourné le VFO, on suit sa position."""
        if not t.get("down_hi") or self.last_rx is None or time.monotonic() - self.last_set < 2.5:
            return
        st = self.ctrl.snapshot()
        if abs(st.freq - self.last_rx) > 30:
            f = st.freq / (1 - rr / 299_792_458.0)
            self.sat_down = int(max(t["down"], min(t["down_hi"], f)))

    def _apply(self, t, rx, tx):
        step = 10 if t.get("down_hi") else 100
        rx, tx = int(round(rx / step) * step), (int(round(tx / step) * step) if tx else None)
        if rx != self.last_rx:
            self.ctrl.set_freq(rx)
            self.last_rx = rx
            self.last_set = time.monotonic()
        if tx and tx != self.last_tx:
            self.ctrl.set_param("vfob", tx)
            self.last_tx = tx

    def toggle_track(self, on):
        t = self.cb_tx.currentData()
        if on and (not self.ctrl.connected or not t):
            self.lb.setText("Connectez le poste et choisissez un transpondeur")
            self.b_track.blockSignals(True)
            self.b_track.setChecked(False)
            self.b_track.blockSignals(False)
            return
        self.tracking = on
        self.last_rx = self.last_tx = None
        if not on:
            self.ctrl.set_param("split", False)
            self.lb.setText("Suivi arrêté")
            return
        self.on_tx()
        mode = t.get("mode", "FM")
        if mode == "LINEAR":
            down_mode, up_mode = "USB", ("LSB" if t.get("invert") else "USB")
        elif mode in ("CW",):
            down_mode = up_mode = "CW"
        elif mode in ("PKTFM", "AFSK", "APRS"):
            down_mode = up_mode = "PKTFM"
        elif mode in ("USB", "LSB"):
            down_mode = up_mode = mode
        else:
            down_mode = up_mode = "FM"
        self.ctrl.set_mode(down_mode)
        if t.get("up"):
            self.ctrl.set_param("split", True)
            self.ctrl.action("mode_b", up_mode)
        if t.get("tone"):
            from .gui import CTCSS
            idx = min(range(len(CTCSS)), key=lambda i: abs(CTCSS[i] - t["tone"]))
            self.ctrl.set_param("tone", idx)
            self.ctrl.set_param("tone_mode", 2)
        self.lb.setText(f"Suivi de {self.cb_sat.currentText()} : réception VFO A, émission VFO B (split)"
                        + (f", tonalité {t['tone']} Hz" if t.get("tone") else ""))

    def save_settings(self, s):
        s.setValue("sat_last", self.cb_sat.currentData() or "")
        s.setValue("sat_min_el", self.sp_min.value())
        s.setValue("sat_rotor", "true" if self.ck_rotor.isChecked() else "false")
        if self.tracking:
            self.b_track.setChecked(False)
