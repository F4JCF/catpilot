"""Spots POTA, SOTA et DX cluster : un clic accorde le poste."""
import datetime
import json
import re
import socket
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDockWidget, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from . import cty
from .geo import distance_bearing, from_locator

CLUSTERS = [
    ("dxc.ve7cc.net:23", "VE7CC (Canada), CC Cluster, très fréquenté"),
    ("dxfun.com:8000", "DXFun (Pays-Bas), DXSpider"),
    ("w3lpl.net:7373", "W3LPL (États-Unis), filtré, rapide"),
    ("dxc.nc7j.com:23", "NC7J (États-Unis), AR-Cluster"),
    ("gb7mbc.spoo.org:8000", "GB7MBC (Angleterre), DXSpider"),
    ("dx.k3lr.com:23", "K3LR (États-Unis), concours"),
    ("telnet.reversebeacon.net:7000", "RBN : spots CW/RTTY des skimmers"),
]
RBN_HOST = "telnet.reversebeacon.net"
RBN_PORTS = (7000, 7001)          # 7000 : CW et RTTY, 7001 : FT8 / FT4
RBN_INFO = re.compile(r"(-?\d+)\s*dB(?:\s+(\d+)\s*(WPM|BPS))?", re.I)

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
                self.status.emit(f"Connecté à {host} en tant que {call}")
                continue
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


def parse_rbn(sp):
    """Complète un spot du RBN : rapport (dB), vitesse, type (CQ, BEACON…)."""
    c = sp.get("comment", "")
    m = RBN_INFO.search(c)
    sp["snr"] = int(m.group(1)) if m else None
    sp["wpm"] = int(m.group(2)) if m and m.group(2) else None
    words = c.upper().split()
    sp["mode"] = words[0] if words else sp.get("mode", "")
    sp["type"] = next((w for w in words if w in ("CQ", "BEACON", "NCDXF", "DX")), "")
    return sp


def wildcard_match(call, patterns):
    for p in patterns:
        rx = "^" + re.escape(p).replace("\\*", ".*") + "$"
        if re.match(rx, call):
            return True
    return False


class PskReporter(QObject):
    """Rapports de réception de pskreporter.info (qui a décodé mon indicatif ces 30 dernières minutes)."""
    done = Signal(object)
    URL = "https://retrieve.pskreporter.info/query"

    def fetch(self, call):
        threading.Thread(target=self._run, args=(call,), daemon=True).start()

    def _run(self, call):
        import urllib.parse
        import xml.etree.ElementTree as ET
        try:
            q = urllib.parse.urlencode({"senderCallsign": call, "flowStartSeconds": "-1800", "rronly": "1",
                                        "noactive": "1", "appcontact": "catpilot"})
            req = urllib.request.Request(f"{self.URL}?{q}", headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                root = ET.fromstring(r.read())
            out = {}
            for el in root.iter():
                if el.tag.split("}")[-1] != "receptionReport":
                    continue
                a = el.attrib
                rx = (a.get("receiverCallsign") or "").upper()
                if not rx:
                    continue
                t = int(a.get("flowStartSeconds") or 0) or int(time.time())
                try:
                    snr = int(a.get("sNR")) if a.get("sNR") not in (None, "") else None
                except ValueError:
                    snr = None
                sp = {"spotter": rx, "grid": (a.get("receiverLocator") or "")[:6], "hz": int(a.get("frequency") or 0),
                      "mode": a.get("mode") or "", "snr": snr, "t": t, "src": "PSK Reporter",
                      "time": datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%H:%M")}
                if rx not in out or out[rx]["t"] < t:
                    out[rx] = sp
            self.done.emit(list(out.values()))
        except Exception as e:
            self.done.emit(e)


class SpotsDock(QDockWidget):
    COLS = ["UTC", "Indicatif", "Pays", "Fréquence", "Mode", "Référence", "Infos", "Distance"]
    ME_COLS = ["UTC", "Entendu par", "Pays", "Distance", "Fréquence", "Mode", "dB", "Vitesse", "Source"]
    BEACON_COLS = ["Bande", "Fréquence", "Balise en ce moment", "Lieu", "Distance", "Reste", "Suivante"]

    def __init__(self, win):
        super().__init__("Spots", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("spotsdock")
        s = win.settings
        self.data = {"pota": [], "sota": [], "dx": [], "me": []}
        self.alerts = 0
        self.rbn = []
        for _port in RBN_PORTS:
            c = DxCluster()
            c.spot.connect(self.on_rbn_spot)
            c.status.connect(self.on_rbn_status)
            self.rbn.append(c)
        self.grids = {}                     # indicatif -> locator (stations RBN)
        self.psk = PskReporter()
        self.psk.done.connect(self.on_psk)
        self.psk_timer = QTimer(self)
        self.psk_timer.timeout.connect(self._psk_fetch)
        self._dirty = set()
        self._alerted, self._last_ring = {}, 0.0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)
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
        for key, title in (("pota", "POTA"), ("sota", "SOTA"), ("dx", "DX cluster"), ("me", "Qui m'entend ?")):
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 4, 0, 0)
            if key == "dx":
                dh = QHBoxLayout()
                self.cb_host = QComboBox()
                self.cb_host.setEditable(True)
                for host, desc in CLUSTERS:
                    self.cb_host.addItem(f"{host}   — {desc}", host)
                self.cb_host.setCurrentText(s.value("dx_host", CLUSTERS[0][0]))
                self.cb_host.setToolTip("Choisissez un cluster dans la liste ou tapez une adresse hôte:port.\n"
                                        "Si l'un ne répond pas, essayez le suivant.")
                self.cb_host.activated.connect(lambda i: self.cb_host.setEditText(self.cb_host.itemData(i) or
                                                                                   self.cb_host.currentText()))
                self.ed_host = self.cb_host.lineEdit()
                self.b_dx = QPushButton("Connecter")
                self.b_dx.setCheckable(True)
                self.b_dx.toggled.connect(self.toggle_cluster)
                dh.addWidget(QLabel("Cluster"))
                dh.addWidget(self.cb_host, 1)
                dh.addWidget(self.b_dx)
                pv.addLayout(dh)
                ah = QHBoxLayout()
                ah.addWidget(QLabel("Alertes :"))
                self.ck_new = QCheckBox("nouveau pays")
                self.ck_new.setToolTip("Signale un pays DXCC jamais contacté")
                self.ck_new.setChecked(s.value("alert_new", "true") in (True, "true"))
                self.ck_newband = QCheckBox("nouveau sur la bande")
                self.ck_newband.setToolTip("Signale un pays jamais contacté sur cette bande")
                self.ck_newband.setChecked(s.value("alert_newband", "false") in (True, "true"))
                self.ed_watch = QLineEdit(s.value("alert_watch", ""))
                self.ed_watch.setPlaceholderText("indicatifs surveillés : TX5S, 3Y0*, VP8*…")
                self.ed_watch.setToolTip("Séparés par des virgules ; * remplace n'importe quels caractères")
                self.ck_beep = QCheckBox("son")
                self.ck_beep.setChecked(s.value("alert_beep", "true") in (True, "true"))
                for wd in (self.ck_new, self.ck_newband):
                    ah.addWidget(wd)
                ah.addWidget(self.ed_watch, 1)
                ah.addWidget(self.ck_beep)
                pv.addLayout(ah)
            if key == "me":
                mh = QHBoxLayout()
                self.b_rbn = QPushButton("Écouter le RBN")
                self.b_rbn.setCheckable(True)
                self.b_rbn.setToolTip("Reverse Beacon Network : des récepteurs automatiques du monde entier "
                                      "signalent qui ils entendent (CW, RTTY, FT8, FT4).\n"
                                      "Lancez un CQ avec votre indicatif : les stations qui vous "
                                      "entendent s'affichent ici et sur la carte.")
                self.b_rbn.toggled.connect(self.toggle_rbn)
                mh.addWidget(self.b_rbn)
                self.b_psk = QPushButton("PSK Reporter")
                self.b_psk.setCheckable(True)
                self.b_psk.setToolTip("pskreporter.info : stations qui ont décodé vos émissions FT8, FT4, PSK, JS8…\n"
                                      "(avec WSJT-X ou le panneau Numérique). Interrogé toutes les 5 minutes.")
                self.b_psk.toggled.connect(self.toggle_psk)
                mh.addWidget(self.b_psk)
                self.lb_me = QLabel("")
                self.lb_me.setObjectName("value")
                mh.addWidget(self.lb_me, 1)
                b = QPushButton("Effacer")
                b.clicked.connect(self.clear_me)
                mh.addWidget(b)
                pv.addLayout(mh)
            cols = self.ME_COLS if key == "me" else self.COLS
            t = QTableWidget(0, len(cols))
            t.setHorizontalHeaderLabels(cols)
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            t.horizontalHeader().setStretchLastSection(True)
            if key != "me":
                t.cellDoubleClicked.connect(lambda r, _c, k=key: self.tune(k, r))
                t.setToolTip("Double-clic : accorder le poste et préparer le QSO dans le carnet")
            pv.addWidget(t)
            if key != "me":
                lg = QLabel("<span style='color:#ff5252'>■</span> nouveau pays &nbsp; "
                            "<span style='color:#ffab40'>■</span> pays nouveau sur la bande &nbsp; "
                            "<span style='color:#ffd740'>■</span> pays contacté, pas encore confirmé &nbsp; "
                            "<span style='color:#7a7a7a'>■</span> indicatif déjà contacté")
                lg.setObjectName("hint")
                pv.addWidget(lg)
            self.tables[key] = t
            self.tabs.addTab(page, title)
        self._build_beacons()
        v.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._tab_changed)
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
        self.visibilityChanged.connect(lambda vis: vis and self.refresh_tables())
        self.tabs.currentChanged.connect(lambda _i: self.refresh_tables())

    # --- balises NCDXF ----------------------------------------------------------------------
    def _build_beacons(self):
        from .beacons import BEACONS
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 4, 0, 0)
        t = QLabel("Balises NCDXF/IARU : 18 balises à travers le monde se relaient toutes les 10 s sur 5 bandes "
                   "(indicatif en CW puis 4 traits à 100, 10, 1 et 0,1 W). Double-clic : écouter la balise "
                   "(le poste passe en CW sur la fréquence). L'horloge du PC doit être à l'heure.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        pv.addWidget(t)
        tb = QTableWidget(0, len(self.BEACON_COLS))
        tb.setHorizontalHeaderLabels(self.BEACON_COLS)
        tb.verticalHeader().setVisible(False)
        tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        tb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        tb.horizontalHeader().setStretchLastSection(True)
        tb.cellDoubleClicked.connect(self._beacon_tune)
        from PySide6.QtCore import QSize
        tb.setIconSize(QSize(24, 18))
        pv.addWidget(tb, 1)
        h = QHBoxLayout()
        self.ck_follow = QCheckBox("Suivre la balise")
        self.ck_follow.setToolTip("Le poste change de bande toutes les 10 s pour rester sur cette balise")
        h.addWidget(self.ck_follow)
        self.cb_beacon = QComboBox()
        for c, where, _g in BEACONS:
            self.cb_beacon.addItem(f"{c} — {where}")
        h.addWidget(self.cb_beacon)
        h.addStretch()
        pv.addLayout(h)
        self.tb_beacons = tb
        self.tabs.addTab(page, "Balises")
        self._follow_last = None
        self.beacon_timer = QTimer(self)
        self.beacon_timer.timeout.connect(self._beacon_tick)
        self.beacon_timer.start(1000)

    def _beacon_tick(self):
        from .beacons import BEACONS, FREQS, on_air, where_is
        if self.ck_follow.isChecked() and self.ctrl.connected:
            w = where_is(self.cb_beacon.currentIndex())
            if w and w[1] != self._follow_last:
                self._follow_last = w[1]
                self.ctrl.set_freq(w[1])
                if "CW" in self.ctrl.driver.modes:
                    self.ctrl.set_mode("CW")
        if not self.isVisible() or self.tabs.currentIndex() != self.tabs.count() - 1:
            return
        from .qsl import country_of, flag_icon
        from .geo import distance_bearing as db
        rows = on_air()
        t = self.tb_beacons
        t.setRowCount(len(rows))
        pos = getattr(self.win, "station", None)
        for i, (band, hz, idx, left) in enumerate(rows):
            call, where, grid = BEACONS[idx]
            nxt = BEACONS[(idx - 1) % len(BEACONS)][0]
            dist = ""
            if pos:
                try:
                    d, b = db(*pos, *from_locator(grid))
                    dist = f"{d:.0f} km  {b:.0f}°"
                except ValueError:
                    pass
            vals = [band, f"{hz / 1e3:.0f}".replace(".", ","), call, where, dist, f"{left:.0f} s", nxt]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 2:
                    f = QFont(it.font())
                    f.setBold(True)
                    it.setFont(f)
                    ic = flag_icon(country_of(call)[0])
                    if ic:
                        it.setIcon(ic)
                if self._last_hz_band(hz):
                    it.setForeground(QColor("#4fc3f7"))
                t.setItem(i, c, it)

    def _last_hz_band(self, hz):
        st = getattr(self.win, "_last", None)
        return bool(st and self.ctrl.connected and abs(st.freq - hz) < 1500)

    def _beacon_tune(self, row, _col=0):
        from .beacons import FREQS
        if not self.ctrl.connected or not 0 <= row < len(FREQS):
            return
        self.ck_follow.setChecked(False)
        self.ctrl.set_freq(FREQS[row][1])
        if "CW" in self.ctrl.driver.modes:
            self.ctrl.set_mode("CW")
        self.win.statusBar().showMessage(f"Écoute des balises NCDXF sur {FREQS[row][1] / 1e3:.0f} kHz")

    def current_beacons(self):
        """Pour la carte : [(indicatif, locator, bande, fréquence)] des balises qui émettent."""
        from .beacons import BEACONS, on_air
        return [(BEACONS[i][0], BEACONS[i][2], band, hz) for band, hz, i, _l in on_air()]

    # --- PSK Reporter --------------------------------------------------------------------------
    def toggle_psk(self, on):
        call = (self.win.settings.value("mycall", "") or "").strip().upper()
        if on and not call:
            self.lb_me.setText("Indiquez votre indicatif (menu Carnet > Réglages)")
            self.b_psk.blockSignals(True)
            self.b_psk.setChecked(False)
            self.b_psk.blockSignals(False)
            return
        if on:
            self._psk_fetch()
            self.psk_timer.start(5 * 60_000)        # pskreporter.info demande au plus une requête / 5 min
        else:
            self.psk_timer.stop()

    def _psk_fetch(self):
        call = (self.win.settings.value("mycall", "") or "").strip().upper()
        if call:
            self.lb_me.setText("PSK Reporter : interrogation…")
            self.psk.fetch(call)

    def on_psk(self, data):
        if isinstance(data, Exception):
            self.lb_me.setText(f"PSK Reporter indisponible : {data}")
            return
        lst = self.data["me"]
        now = time.time()
        for sp in data:
            info = cty.lookup(sp["spotter"])
            from .logbook import french_name
            sp["country"] = french_name(info) if info else ""
            self._fill_spotter_pos(sp)
            lst[:] = [x for x in lst if not (x["spotter"] == sp["spotter"] and x.get("src") == "PSK Reporter")]
            lst.append(sp)
        lst[:] = [x for x in lst if now - x["t"] < 3600]
        lst.sort(key=lambda x: -x["t"])
        if not data:
            self.lb_me.setText("PSK Reporter : personne ne vous a signalé dans les 30 dernières minutes")
        self.refresh_me()

    def _tab_changed(self, i):
        if i == 2 and self.alerts:
            self.alerts = 0
            self.tabs.setTabText(2, "DX cluster")

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
        for sp in data:
            self._fill_pos(sp)
            why = self.alert_reason(sp) if self.ed_watch.text().strip() else ""
            if why == "indicatif surveillé":
                sp["alert"] = why
        self.data[kind] = data
        mp = getattr(self.win, "mapdock", None)
        if mp:
            mp.update_layers()
        self.lb_status.setText(f"Mis à jour à {datetime.datetime.now(datetime.timezone.utc):%H:%M} UTC")
        self.refresh_tables()

    def on_dx_spot(self, sp):
        self._fill_pos(sp)
        why = self.alert_reason(sp)
        if why:
            sp["alert"] = why
            now = time.time()
            seen = self._alerted.get(sp["call"])
            if not seen or now - seen > 3600:          # une seule alerte par indicatif et par heure
                self._alerted[sp["call"]] = now
                self.alerts += 1
                self.tabs.setTabText(2, f"DX cluster ({self.alerts} alerte{'s' if self.alerts > 1 else ''})")
                self.win.statusBar().showMessage(
                    f"Alerte : {sp['call']} sur {sp['hz'] / 1e3:.1f} kHz {sp['mode']} — {why}", 20000)
                if now - self._last_ring > 15:          # son et voix : au plus toutes les 15 s
                    self._last_ring = now
                    if self.ck_beep.isChecked():
                        QApplication.beep()
                    if hasattr(self.win, "say_alert"):
                        self.win.say_alert(sp, why)
        lst = self.data["dx"]
        lst[:] = [x for x in lst if not (x["call"] == sp["call"] and abs(x["hz"] - sp["hz"]) < 2000)]
        sp.setdefault("t", time.time())
        lst.insert(0, sp)
        self._check_6m(lst)
        del lst[300:]
        self.refresh_tables("dx")
        mp = getattr(self.win, "mapdock", None)
        if mp:
            mp.update_layers()

    def _check_6m(self, lst):
        """Ouverture du 6 m : au moins 4 spots européens sur 50 MHz en 15 minutes."""
        if self.win.settings.value("alert_es", "true") not in (True, "true"):
            return
        now = time.time()
        if not 50_000_000 <= lst[0]["hz"] <= 54_000_000:
            return
        recent = {x["call"] for x in lst if 50_000_000 <= x["hz"] <= 54_000_000 and now - x.get("t", 0) < 900
                  and (cty.lookup(x["call"]) or {}).get("cont") == "EU"}
        if len(recent) >= 4 and now - getattr(self, "_six_alert", 0) > 3 * 3600:
            self._six_alert = now
            self.win.propagation_alert(f"le 6 m est ouvert : {len(recent)} stations européennes signalées "
                                       f"en 15 min ({', '.join(sorted(recent)[:5])})")

    # --- alertes ----------------------------------------------------------------------------
    def alert_reason(self, sp):
        call = sp["call"]
        watch = [w.strip().upper() for w in self.ed_watch.text().split(",") if w.strip()]
        if watch and wildcard_match(call, watch):
            return "indicatif surveillé"
        if not (self.ck_new.isChecked() or self.ck_newband.isChecked()):
            return ""
        if not self.win.worked_entities():          # carnet vide : tout serait « nouveau »
            return ""
        ent = cty.dxcc(call)
        if not ent:
            return ""
        worked = self.win.worked_entities()
        from .logbook import band_of_mhz, french_name
        name = french_name(ent)
        if self.ck_new.isChecked() and ent["prefix"] not in worked:
            return f"nouveau pays : {name}"
        band = band_of_mhz(sp["hz"] / 1e6)
        if self.ck_newband.isChecked() and band and band not in worked.get(ent["prefix"], set()):
            return f"{name} jamais contacté sur {band}"
        return ""

    def _fill_pos(self, sp):
        if sp.get("grid"):
            try:
                sp["lat"], sp["lon"] = from_locator(sp["grid"])
                return
            except ValueError:
                pass
        info = cty.lookup(sp["call"])
        if info:
            sp["lat"], sp["lon"] = info["lat"], info["lon"]

    # --- Reverse Beacon Network ---------------------------------------------------------
    def toggle_rbn(self, on):
        call = cty.base_call((self.win.settings.value("mycall", "") or "").strip().upper())
        if on and not call:
            self.lb_me.setText("Indiquez votre indicatif (menu Carnet > Réglages)")
            self.b_rbn.blockSignals(True)
            self.b_rbn.setChecked(False)
            self.b_rbn.blockSignals(False)
            return
        for c, port in zip(self.rbn, RBN_PORTS):
            if on:
                c.connect_to(RBN_HOST, port, call)
            else:
                c.disconnect()
        self.b_rbn.setText("Arrêter le RBN" if on else "Écouter le RBN")
        if not on:
            self.lb_me.setText("")

    def on_rbn_status(self, msg):
        if self.b_rbn.isChecked() and not self.data["me"]:
            self.lb_me.setText(msg.replace(RBN_HOST, "RBN"))

    def on_rbn_spot(self, sp):
        mine = cty.base_call(self.win.settings.value("mycall", "") or "")
        if not mine or cty.base_call(sp["call"]) != mine:
            return
        parse_rbn(sp)
        sp["spotter"] = re.sub(r"-[0-9#]+$", "", sp["spotter"].upper())
        sp["t"] = time.time()
        sp["src"] = "RBN"
        g = self.grids.get(sp["spotter"])
        if g:
            sp["grid"] = g
        else:
            self._ask_grid(sp["spotter"])
        info = cty.lookup(sp["spotter"])
        sp["country"] = ""
        if info:
            from .logbook import french_name
            sp["country"] = french_name(info)
        self._fill_spotter_pos(sp)
        lst = self.data["me"]
        lst[:] = [x for x in lst if not (x["spotter"] == sp["spotter"] and x.get("src", "RBN") == "RBN")
                  and time.time() - x["t"] < 3600]
        lst.insert(0, sp)
        self.refresh_me()

    def _fill_spotter_pos(self, sp):
        grid = sp.get("grid") or self.grids.get(sp["spotter"])
        pos = None
        if grid:
            try:
                pos = from_locator(grid)
            except ValueError:
                pos = None
        if not pos:
            info = cty.lookup(sp["spotter"])
            pos = (info["lat"], info["lon"]) if info else None
        if pos:
            sp["lat"], sp["lon"] = pos
            st = getattr(self.win, "station", None)
            if st:
                sp["km"], sp["az"] = distance_bearing(*st, *pos)

    def _ask_grid(self, call):
        """Locator précis d'une station du RBN (QRZ.com / HamQTH, si un compte est réglé)."""
        if call in self.grids or not hasattr(self.win, "logdock"):
            return
        self.grids[call] = ""
        look = self.win.logdock.hamqth
        if not getattr(self, "_grid_hooked", False):
            look.result.connect(self._on_grid)
            self._grid_hooked = True
        look.lookup(call)

    def _on_grid(self, call, info):
        if call in self.grids and isinstance(info, dict) and info.get("grid"):
            self.grids[call] = info["grid"][:6]
            for sp in self.data["me"]:
                if sp["spotter"] == call:
                    sp["grid"] = self.grids[call]
                    self._fill_spotter_pos(sp)
            self.refresh_me()

    def clear_me(self):
        self.data["me"] = []
        self.refresh_me()

    def refresh_me(self):
        rows = self.data["me"]
        t = self.tables["me"]
        t.setRowCount(len(rows))
        for i, sp in enumerate(rows):
            vals = [sp["time"], sp["spotter"], sp.get("country", ""),
                    f"{sp['km']:.0f} km" if sp.get("km") is not None else "",
                    f"{sp['hz'] / 1e3:.1f}".replace(".", ","), sp.get("mode", ""),
                    f"{sp['snr']} dB" if sp.get("snr") is not None else "",
                    f"{sp['wpm']} mots/min" if sp.get("wpm") and sp.get("mode") == "CW" else "",
                    sp.get("src", "RBN")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c in (3, 4, 6):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(i, c, it)
        if rows:
            far = max(rows, key=lambda x: x.get("km") or 0)
            best = max(rows, key=lambda x: x.get("snr") if x.get("snr") is not None else -99)
            txt = f"{len(rows)} station{'s' if len(rows) > 1 else ''} vous entend{'ent' if len(rows) > 1 else ''}"
            if far.get("km"):
                txt += f" · la plus loin : {far['spotter']} ({far['km']:.0f} km)"
            if best.get("snr") is not None:
                txt += f" · meilleur : {best['snr']} dB ({best['spotter']})"
            self.lb_me.setText(txt)
            self.tabs.setTabText(3, f"Qui m'entend ? ({len(rows)})")
        else:
            self.tabs.setTabText(3, "Qui m'entend ?")
        mp = getattr(self.win, "mapdock", None)
        if mp:
            mp.update_layers()

    def toggle_cluster(self, on):
        if on:
            host, _, port = (self.ed_host.text().strip().split() or [""])[0].rpartition(":")
            call = cty.base_call((self.win.settings.value("mycall", "") or "").strip().upper())
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

    def spot_status(self, sp):
        """« new », « newband », « unconf », « worked » ou "" (pour la couleur de la ligne)."""
        ent = cty.dxcc(sp["call"])
        if not ent:
            return "worked" if self.win.worked_before(sp["call"]) else ""
        worked = self.win.worked_entities()
        if ent["prefix"] not in worked:
            return "new"
        from .logbook import band_of_mhz
        band = band_of_mhz(sp["hz"] / 1e6)
        if band and band not in worked.get(ent["prefix"], set()):
            return "newband"
        conf = getattr(self.win, "confirmed_entities", lambda: set())()
        if ent["prefix"] not in conf:
            return "unconf"
        return "worked" if self.win.worked_before(sp["call"]) else ""

    STATUS_STYLE = {"new": ("#ff5252", 60), "newband": ("#ffab40", 45), "unconf": ("#ffd740", 30)}

    MAX_ROWS = 200

    def refresh_tables(self, only=None):
        """Remplit les tableaux. Appelé souvent (chaque spot) : regroupé, et seulement si le panneau est visible."""
        if only and isinstance(only, str):
            self._dirty.add(only)
        else:
            self._dirty.update(k for k in self.tables if k != "me")
        if not self.isVisible():
            return
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(700)

    def _do_refresh(self):
        if not self.isVisible():
            return
        from .qsl import country_of, flag_icon
        pos = getattr(self.win, "station", None)
        gen = getattr(self.win, "log_gen", 0)
        cur_tab = ["pota", "sota", "dx", "me", "beacons"][self.tabs.currentIndex()] \
            if self.tabs.currentIndex() < 5 else ""
        keys = [k for k in self._dirty if k == cur_tab] or []      # l'onglet affiché d'abord
        for key in keys:
            self._dirty.discard(key)
            t = self.tables[key]
            rows = [sp for sp in self.data[key] if self._visible(sp)][:self.MAX_ROWS]
            t.setProperty("rows", rows)
            t.setUpdatesEnabled(False)
            t.setRowCount(len(rows))
            for i, sp in enumerate(rows):
                if "_iso" not in sp:
                    sp["_iso"], sp["_country"] = country_of(sp["call"])
                if sp.get("_gen") != gen:
                    sp["_gen"], sp["_stat"] = gen, self.spot_status(sp)
                    sp["_worked"] = self.win.worked_before(sp["call"])
                stat = sp["_stat"]
                dist = sp.get("_dist")
                if dist is None:
                    dist = ""
                    if pos and sp.get("grid"):
                        try:
                            d, b = distance_bearing(*pos, *from_locator(sp["grid"]))
                            dist = f"{d:.0f} km  {b:.0f}°"
                        except ValueError:
                            pass
                    sp["_dist"] = dist
                info = " — ".join(x for x in (sp.get("info"), sp.get("where")) if x)
                vals = [sp["time"], sp["call"], sp["_country"], f"{sp['hz'] / 1e3:.1f}".replace(".", ","),
                        sp["mode"], sp["ref"], info, dist]
                bg = fg = None
                tip = ""
                if stat in self.STATUS_STYLE:
                    col, alpha = self.STATUS_STYLE[stat]
                    bg = QColor(col)
                    bg.setAlpha(alpha)
                    tip = {"new": "Nouveau pays DXCC", "newband": "Pays jamais contacté sur cette bande",
                           "unconf": "Pays contacté mais pas encore confirmé (QSL, eQSL, LoTW)"}[stat]
                if sp.get("alert"):
                    fg, tip = QColor("#ff9a2e"), "Alerte : " + sp["alert"]
                elif stat == "worked" or sp.get("_worked"):
                    fg = QColor("#7a7a7a")
                for c, val in enumerate(vals):
                    it = QTableWidgetItem(val)
                    if c == 2:
                        ic = flag_icon(sp["_iso"])
                        if ic:
                            it.setIcon(ic)
                    elif c == 3:
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if bg is not None:
                        it.setBackground(bg)
                    if fg is not None:
                        it.setForeground(fg)
                        if sp.get("alert"):
                            f = QFont(it.font())
                            f.setBold(True)
                            it.setFont(f)
                    if tip:
                        it.setToolTip(tip)
                    t.setItem(i, c, it)
            if len(rows) != t.property("sized"):
                t.setProperty("sized", len(rows))
                t.resizeColumnsToContents()
            t.setUpdatesEnabled(True)

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
        s.setValue("alert_new", self.ck_new.isChecked())
        s.setValue("alert_newband", self.ck_newband.isChecked())
        s.setValue("alert_watch", self.ed_watch.text())
        s.setValue("alert_beep", self.ck_beep.isChecked())
        for c in self.rbn:
            c.disconnect()
        s.setValue("dx_host", (self.ed_host.text().strip().split() or [""])[0])
        s.setValue("spots_every", self.sp_every.value())
        self.cluster.disconnect()


_BANDS = []


def win_bands():
    return _BANDS


def set_bands(bands):
    _BANDS[:] = bands
