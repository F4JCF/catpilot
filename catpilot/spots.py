"""Spots POTA, SOTA et DX cluster : un clic accorde le poste."""
import datetime
import json
import re
import socket
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDockWidget, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .geo import distance_bearing, from_locator

POTA_URL = "https://api.pota.app/spot/activator"
SOTA_URL = "https://api2.sota.org.uk/api/spots/60/all"
UA = {"User-Agent": f"CATPilot/{__version__}"}
DX_LINE = re.compile(r"^DX de\s+([A-Z0-9/\-#]+):?\s+(\d+\.\d+)\s+([A-Z0-9/]+)\s+(.*?)\s+(\d{4})Z", re.I)
MODE_GROUPS = {"Tous": None, "CW": {"CW"}, "Phonie": {"SSB", "USB", "LSB", "AM", "FM"},
               "Numérique": {"FT8", "FT4", "DATA", "RTTY", "PSK31", "JS8", "DIGI", "Q65"}}


def rig_mode_for(mode, hz):
    m = (mode or "").upper()
    if m == "CW":
        return "CW"
    if m in ("SSB", "USB", "LSB", "PHONE"):
        return "LSB" if m == "LSB" or (m != "USB" and hz < 10_000_000) else "USB"
    if m == "AM":
        return "AM"
    if m == "FM":
        return "FM"
    if m in ("FT8", "FT4", "DATA", "PSK31", "JS8", "DIGI", "Q65", "RTTY"):
        return "PKTUSB"
    return None


def guess_mode(hz, comment=""):
    """Mode probable d'un spot DX cluster, d'après le commentaire puis la fréquence."""
    c = comment.upper()
    for m in ("FT8", "FT4", "CW", "SSB", "RTTY", "PSK", "JS8", "FM"):
        if m in c:
            return m
    from .bandplan import segment_at
    seg = segment_at(hz)
    if seg:
        return {"CW": "CW", "NUM": "DATA", "BLU": "SSB", "FM": "FM", "RLY": "FM"}.get(seg[2], "")
    return ""


def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_pota(data):
    out = []
    for s in data:
        try:
            hz = int(round(float(s.get("frequency", 0)) * 1000))
        except (TypeError, ValueError):
            continue
        t = (s.get("spotTime") or "")[11:16]
        out.append({"time": t, "call": s.get("activator", ""), "hz": hz, "mode": (s.get("mode") or "").upper(),
                    "ref": s.get("reference", ""), "info": s.get("name") or s.get("parkName") or "",
                    "where": s.get("locationDesc", ""), "grid": s.get("grid6") or s.get("grid4") or "",
                    "spotter": s.get("spotter", ""), "comment": s.get("comments", "")})
    return out


def parse_sota(data):
    out = []
    for s in data:
        try:
            hz = int(round(float(s.get("frequency", 0)) * 1_000_000))
        except (TypeError, ValueError):
            continue
        ts = s.get("timeStamp") or ""
        ref = f"{s.get('associationCode', '')}/{s.get('summitCode', '')}".strip("/")
        out.append({"time": ts[11:16], "call": s.get("activatorCallsign", ""), "hz": hz,
                    "mode": (s.get("mode") or "").upper(), "ref": ref, "info": s.get("summitDetails", ""),
                    "where": s.get("associationCode", ""), "grid": "", "spotter": s.get("callsign", ""),
                    "comment": s.get("comments") or ""})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


def parse_dx_line(line):
    i = line.find("DX de")
    if i < 0:
        i = line.upper().find("DX DE")
    m = DX_LINE.match(line[i:].strip()) if i >= 0 else None
    if not m:
        return None
    spotter, khz, call, comment, hhmm = m.groups()
    hz = int(round(float(khz) * 1000))
    return {"time": f"{hhmm[:2]}:{hhmm[2:]}", "call": call.upper(), "hz": hz, "mode": guess_mode(hz, comment),
            "ref": "", "info": comment.strip(), "where": "", "grid": "", "spotter": spotter.rstrip(":"),
            "comment": comment.strip()}


class Fetcher(QObject):
    """Récupère une liste de spots (HTTP) dans un fil séparé."""
    done = Signal(str, object)

    def fetch(self, kind):
        threading.Thread(target=self._run, args=(kind,), daemon=True).start()

    def _run(self, kind):
        try:
            if kind == "pota":
                self.done.emit(kind, parse_pota(fetch_json(POTA_URL)))
            else:
                self.done.emit(kind, parse_sota(fetch_json(SOTA_URL)))
        except Exception as e:
            self.done.emit(kind, e)


class DxCluster(QObject):
    """Client telnet de DX cluster (DXSpider, AR-Cluster, CC-Cluster)."""
    spot = Signal(object)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self._run = False
        self._sock = None

    def connect_to(self, host, port, call):
        self.disconnect()
        self._run = True
        threading.Thread(target=self._loop, args=(host, int(port), call), daemon=True).start()

    def disconnect(self):
        self._run = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send(self, line):
        if self._sock:
            try:
                self._sock.sendall((line + "\r\n").encode("ascii", "ignore"))
            except OSError:
                pass

    def _loop(self, host, port, call):
        try:
            self.status.emit(f"Connexion à {host}:{port}…")
            s = socket.create_connection((host, port), timeout=15)
            s.settimeout(1.0)
            self._sock = s
        except OSError as e:
            self.status.emit(f"Cluster injoignable : {e}")
            self._run = False
            return
        buf, logged = b"", False
        last_rx = time.monotonic()
        while self._run:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                last_rx = time.monotonic()
                buf += chunk
            except socket.timeout:
                if time.monotonic() - last_rx > 300:      # liaison silencieuse : on relance
                    break
                continue
            except OSError:
                break
            text = buf.decode("latin-1")
            if not logged and re.search(r"(login|call(sign)?)\s*:?\s*$", text.strip(), re.I):
                self.send(call)
                logged = True
                buf = b""
                continue
                self.status.emit(f"Connecté à {host} en tant que {call}")
            *lines, rest = text.replace("\r", "").split("\n")
            buf = rest.encode("latin-1")
            for ln in lines:
                sp = parse_dx_line(ln)
                if sp:
                    self.spot.emit(sp)
        self._sock = None
        if self._run:
            self.status.emit("Cluster déconnecté")
        self._run = False


class SpotsDock(QDockWidget):
    COLS = ["UTC", "Indicatif", "Fréquence", "Mode", "Référence", "Infos", "Distance"]

    def __init__(self, win):
        super().__init__("Spots", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("spotsdock")
        s = win.settings
        self.data = {"pota": [], "sota": [], "dx": []}
        self.fetcher = Fetcher()
        self.fetcher.done.connect(self.on_fetched)
        self.cluster = DxCluster()
        self.cluster.spot.connect(self.on_dx_spot)
        self.cluster.status.connect(lambda m: self.lb_status.setText(m))

        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Bande"))
        self.cb_band = QComboBox()
        self.cb_band.addItem("Toutes")
        for name, *_r in win_bands():
            self.cb_band.addItem(name)
        self.cb_band.currentIndexChanged.connect(self.refresh_tables)
        h.addWidget(self.cb_band)
        h.addWidget(QLabel("Mode"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(list(MODE_GROUPS))
        self.cb_mode.currentIndexChanged.connect(self.refresh_tables)
        h.addWidget(self.cb_mode)
        self.ck_rig = QCheckBox("Bandes de mon poste")
        self.ck_rig.setChecked(True)
        self.ck_rig.toggled.connect(self.refresh_tables)
        h.addWidget(self.ck_rig)
        h.addStretch()
        b = QPushButton("Actualiser")
        b.clicked.connect(self.refresh_now)
        h.addWidget(b)
        v.addLayout(h)

        self.tabs = QTabWidget()
        self.tables = {}
        for key, title in (("pota", "POTA"), ("sota", "SOTA"), ("dx", "DX cluster")):
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 4, 0, 0)
            if key == "dx":
                dh = QHBoxLayout()
                self.ed_host = QLineEdit(s.value("dx_host", "dxc.ve7cc.net:23"))
                self.ed_host.setToolTip("Adresse:port du cluster (DXSpider, AR-Cluster…)")
                self.b_dx = QPushButton("Connecter")
                self.b_dx.setCheckable(True)
                self.b_dx.toggled.connect(self.toggle_cluster)
                dh.addWidget(QLabel("Cluster"))
                dh.addWidget(self.ed_host, 1)
                dh.addWidget(self.b_dx)
                pv.addLayout(dh)
            t = QTableWidget(0, len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            t.horizontalHeader().setStretchLastSection(True)
            t.cellDoubleClicked.connect(lambda r, _c, k=key: self.tune(k, r))
            t.setToolTip("Double-clic : accorder le poste et préparer le QSO dans le carnet")
            pv.addWidget(t)
            self.tables[key] = t
            self.tabs.addTab(page, title)
        v.addWidget(self.tabs, 1)
        h = QHBoxLayout()
        h.addWidget(QLabel("Actualisation"))
        self.sp_every = QSpinBox()
        self.sp_every.setRange(0, 15)
        self.sp_every.setSuffix(" min")
        self.sp_every.setSpecialValueText("manuelle")
        self.sp_every.setValue(int(s.value("spots_every", 1)))
        self.sp_every.valueChanged.connect(self._arm_timer)
        h.addWidget(self.sp_every)
        self.lb_status = QLabel("")
        self.lb_status.setObjectName("hint")
        h.addWidget(self.lb_status, 1)
        v.addLayout(h)
        self.setWidget(w)
        self.setMinimumWidth(560)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_now)
        self._arm_timer()
        self.visibilityChanged.connect(lambda vis: vis and not self.data["pota"] and self.refresh_now())

    def _arm_timer(self):
        n = self.sp_every.value()
        if n:
            self.timer.start(n * 60_000)
        else:
            self.timer.stop()

    def refresh_now(self):
        if not self.isVisible():
            return
        self.lb_status.setText("Actualisation…")
        self.fetcher.fetch("pota")
        self.fetcher.fetch("sota")

    def on_fetched(self, kind, data):
        if isinstance(data, Exception):
            self.lb_status.setText(f"{kind.upper()} indisponible : {data}")
            return
        self.data[kind] = data
        self.lb_status.setText(f"Mis à jour à {datetime.datetime.now(datetime.timezone.utc):%H:%M} UTC")
        self.refresh_tables()

    def on_dx_spot(self, sp):
        lst = self.data["dx"]
        lst[:] = [x for x in lst if not (x["call"] == sp["call"] and abs(x["hz"] - sp["hz"]) < 2000)]
        lst.insert(0, sp)
        del lst[300:]
        self.refresh_tables("dx")

    def toggle_cluster(self, on):
        if on:
            host, _, port = self.ed_host.text().strip().rpartition(":")
            call = (self.win.settings.value("mycall", "") or "").strip().upper()
            if not host or not port.isdigit():
                self.lb_status.setText("Adresse du cluster au format hôte:port")
                self._uncheck()
                return
            if not call:
                self.lb_status.setText("Indiquez votre indicatif (menu Carnet > Réglages)")
                self._uncheck()
                return
            self.cluster.connect_to(host, int(port), call)
            self.b_dx.setText("Déconnecter")
        else:
            self.cluster.disconnect()
            self.b_dx.setText("Connecter")

    def _uncheck(self):
        self.b_dx.blockSignals(True)
        self.b_dx.setChecked(False)
        self.b_dx.blockSignals(False)

    def _visible(self, sp):
        band = self.cb_band.currentText()
        if band != "Toutes":
            b = next((x for x in win_bands() if x[0] == band), None)
            if not b or not b[1] <= sp["hz"] <= b[2]:
                return False
        grp = MODE_GROUPS[self.cb_mode.currentText()]
        if grp and sp["mode"] not in grp:
            return False
        if self.ck_rig.isChecked() and self.ctrl.driver:
            d = self.ctrl.driver
            hi, lo = getattr(d, "max_freq", 470_000_000), getattr(d, "min_freq", 0)
            if not (lo <= sp["hz"] <= hi) or not any(b[1] <= sp["hz"] <= b[2] for b in win_bands()):
                return False
        return True

    def refresh_tables(self, only=None):
        pos = getattr(self.win, "station", None)
        for key, t in self.tables.items():
            if only and isinstance(only, str) and key != only:
                continue
            rows = [sp for sp in self.data[key] if self._visible(sp)]
            t.setProperty("rows", rows)
            t.setRowCount(len(rows))
            for i, sp in enumerate(rows):
                dist = ""
                if pos and sp.get("grid"):
                    try:
                        d, b = distance_bearing(*pos, *from_locator(sp["grid"]))
                        dist = f"{d:.0f} km  {b:.0f}°"
                    except ValueError:
                        pass
                info = " — ".join(x for x in (sp.get("info"), sp.get("where")) if x)
                vals = [sp["time"], sp["call"], f"{sp['hz'] / 1e3:.1f}".replace(".", ","), sp["mode"],
                        sp["ref"], info, dist]
                for c, val in enumerate(vals):
                    it = QTableWidgetItem(val)
                    if c == 2:
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if self.win.worked_before(sp["call"]):
                        it.setForeground(QColor("#7a7a7a"))
                    t.setItem(i, c, it)

    def tune(self, key, row):
        rows = self.tables[key].property("rows") or []
        if not 0 <= row < len(rows) or not self.ctrl.connected:
            return
        sp = rows[row]
        self.ctrl.set_freq(sp["hz"])
        mode = rig_mode_for(sp["mode"], sp["hz"])
        if mode and mode in self.ctrl.driver.modes:
            self.ctrl.set_mode(mode)
        log_mode = {"PKTUSB": "FT4" if sp["mode"] == "FT4" else "FT8", "USB": "SSB", "LSB": "SSB"}.get(mode, mode)
        self.win.prefill_log(sp["call"], sp["ref"], log_mode if sp["mode"] not in ("DATA", "") else None)
        if sp.get("grid") and getattr(self.win, "station", None):
            self.win.point_rotor_to_grid(sp["grid"])
        self.win.statusBar().showMessage(f"Accordé sur {sp['call']} {sp['hz'] / 1e3:.1f} kHz {sp['mode']}")

    def save_settings(self, s):
        s.setValue("dx_host", self.ed_host.text())
        s.setValue("spots_every", self.sp_every.value())
        self.cluster.disconnect()


_BANDS = []


def win_bands():
    return _BANDS


def set_bands(bands):
    _BANDS[:] = bands
