"""Liaison avec WSJT-X / JTDX par leur protocole UDP (port 2237 par défaut).

CAT Pilot écoute :
- les décodages (message 2) pour lister les stations entendues ;
- les QSO journalisés en ADIF (message 12) pour les inscrire au carnet.
Dans WSJT-X : Paramètres > Rapports > Serveur UDP 127.0.0.1, port 2237,
cocher « Accepter les requêtes UDP ». Si un autre logiciel (JTAlert,
GridTracker) écoute déjà ce port, utilisez l'adresse multicast 224.0.0.1
dans WSJT-X et ici.
"""
import re
import socket
import struct
import threading

from PySide6.QtCore import QObject, Signal

MAGIC = 0xADBCCBDA
GRID = re.compile(r"^[A-R]{2}\d{2}$")
CALL = re.compile(r"^(?=.*\d)[A-Z0-9/]{3,12}$")


class Reader:
    def __init__(self, data):
        self.d, self.i = data, 0

    def u32(self):
        v = struct.unpack_from(">I", self.d, self.i)[0]
        self.i += 4
        return v

    def i32(self):
        v = struct.unpack_from(">i", self.d, self.i)[0]
        self.i += 4
        return v

    def u64(self):
        v = struct.unpack_from(">Q", self.d, self.i)[0]
        self.i += 8
        return v

    def f64(self):
        v = struct.unpack_from(">d", self.d, self.i)[0]
        self.i += 8
        return v

    def b(self):
        v = self.d[self.i] != 0
        self.i += 1
        return v

    def s(self):
        n = self.u32()
        if n == 0xFFFFFFFF:
            return ""
        v = self.d[self.i:self.i + n].decode("utf-8", "replace")
        self.i += n
        return v


def parse_message(data):
    """Renvoie (type, dict) ou None."""
    if len(data) < 12:
        return None
    r = Reader(data)
    if r.u32() != MAGIC:
        return None
    r.u32()                         # schéma
    kind = r.u32()
    msg = {"id": r.s()}
    try:
        if kind == 1:               # Status
            msg["dial"] = r.u64()
            msg["mode"] = r.s()
            msg["dx_call"] = r.s()
            msg["report"] = r.s()
            msg["tx_mode"] = r.s()
            msg["tx_enabled"] = r.b()
            msg["transmitting"] = r.b()
        elif kind == 2:             # Decode
            msg["new"] = r.b()
            msg["time_ms"] = r.u32()
            msg["snr"] = r.i32()
            msg["dt"] = r.f64()
            msg["df"] = r.u32()
            msg["mode"] = r.s()
            msg["text"] = r.s()
        elif kind == 12:            # Logged ADIF
            msg["adif"] = r.s()
    except struct.error:
        return None
    return kind, msg


def caller_of(text):
    """Indicatif et locator d'un message FT8 (« CQ DX F5ABC JN03 », « F4XYZ F5ABC -12 »…)."""
    words = text.upper().replace("<", "").replace(">", "").split()
    if not words:
        return None, None, False
    cq = words[0] == "CQ"
    if cq:
        words = words[1:]
        if words and not CALL.match(words[0]) and len(words) > 1:
            words = words[1:]             # « CQ DX », « CQ POTA »…
        call = words[0] if words else None
    else:
        call = words[1] if len(words) > 1 else None
    grid = next((w for w in words[1:] if GRID.match(w) and w != "RR73"), None)
    if call and not CALL.match(call):
        call = None
    return call, grid, cq


def build_message(kind, ident, payload=b""):
    def s(x):
        b = x.encode("utf-8")
        return struct.pack(">I", len(b)) + b
    return struct.pack(">III", MAGIC, 2, kind) + s(ident) + payload


class WsjtxListener(QObject):
    decode = Signal(object)        # dict : call, grid, cq, snr, df, text, mode
    logged = Signal(str)           # enregistrement ADIF
    status = Signal(object)        # message d'état WSJT-X
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._run = False
        self._sock = None
        self.peer = None

    def start(self, port=2237, group=""):
        self.stop()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if group:
                s.bind(("", port))
                mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton("127.0.0.1"))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            else:
                s.bind(("127.0.0.1", port))
            s.settimeout(1.0)
        except OSError as e:
            self.error.emit(f"Port UDP {port} indisponible : {e}")
            return False
        self._sock = s
        self._run = True
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def stop(self):
        self._run = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def reply_to(self, decode):
        """Demande à WSJT-X de répondre à une station (message 4 « Reply »)."""
        if not (self._sock and self.peer and decode.get("raw")):
            return
        r = decode["raw"]
        enc = lambda x: struct.pack(">I", len(x.encode("utf-8"))) + x.encode("utf-8")
        payload = (struct.pack(">Ii", r["time_ms"], r["snr"]) + struct.pack(">d", r["dt"])
                   + struct.pack(">I", r["df"]) + enc(r["mode"]) + enc(r["text"]) + b"\x00\x00")
        try:
            self._sock.sendto(build_message(4, r["id"], payload), self.peer)
        except OSError:
            pass

    def _loop(self):
        while self._run:
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            m = parse_message(data)
            if not m:
                continue
            kind, msg = m
            self.peer = addr
            if kind == 2:
                call, grid, cq = caller_of(msg["text"])
                if call:
                    self.decode.emit({"call": call, "grid": grid, "cq": cq, "snr": msg["snr"],
                                      "df": msg["df"], "text": msg["text"], "mode": msg["mode"], "raw": msg})
            elif kind == 12 and msg.get("adif"):
                self.logged.emit(msg["adif"])
            elif kind == 1:
                self.status.emit(msg)


# --- panneau ---------------------------------------------------------------------------------
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QCheckBox, QDockWidget, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class WsjtxDock(QDockWidget):
    COLS = ["Indicatif", "SNR", "DF", "Locator", "Distance", "Message"]

    def __init__(self, win, log):
        super().__init__("WSJT-X", win)
        self.win, self.log = win, log
        self.setObjectName("wsjtxdock")
        s = win.settings
        self.listener = WsjtxListener()
        self.listener.decode.connect(self.on_decode)
        self.listener.logged.connect(self.on_logged)
        self.listener.status.connect(self.on_status)
        self.listener.error.connect(lambda m: self.lb.setText(m))
        self.heard = {}
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Port UDP"))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(int(s.value("wsjtx_port", 2237)))
        h.addWidget(self.sp_port)
        self.ed_group = QLineEdit(s.value("wsjtx_group", ""))
        self.ed_group.setPlaceholderText("multicast (facultatif)")
        self.ed_group.setToolTip("Ex. 224.0.0.1 si JTAlert ou GridTracker écoutent aussi WSJT-X")
        h.addWidget(self.ed_group)
        self.b_on = QPushButton("Écouter WSJT-X")
        self.b_on.setCheckable(True)
        self.b_on.toggled.connect(self.toggle)
        h.addWidget(self.b_on)
        v.addLayout(h)
        h = QHBoxLayout()
        self.ck_log = QCheckBox("Inscrire au carnet les QSO journalisés dans WSJT-X")
        self.ck_log.setChecked(s.value("wsjtx_autolog", "true") == "true")
        h.addWidget(self.ck_log)
        self.ck_cq = QCheckBox("Seulement les CQ")
        self.ck_cq.toggled.connect(self.refresh)
        h.addWidget(self.ck_cq)
        h.addStretch()
        b = QPushButton("Vider")
        b.clicked.connect(lambda: (self.heard.clear(), self.refresh()))
        h.addWidget(b)
        v.addLayout(h)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setToolTip("Double-clic : demander à WSJT-X d'appeler cette station.\n"
                            "Vert : CQ d'un indicatif jamais contacté.")
        self.tbl.cellDoubleClicked.connect(self.reply)
        v.addWidget(self.tbl, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        self.setWidget(w)
        if s.value("wsjtx_on", "false") == "true":
            self.b_on.setChecked(True)

    def toggle(self, on):
        if on:
            if not self.listener.start(self.sp_port.value(), self.ed_group.text().strip()):
                self.b_on.blockSignals(True)
                self.b_on.setChecked(False)
                self.b_on.blockSignals(False)
                return
            self.lb.setText("En écoute de WSJT-X…")
        else:
            self.listener.stop()
            self.lb.setText("Arrêté")
        self.sp_port.setEnabled(not on)
        self.ed_group.setEnabled(not on)

    def on_status(self, st):
        dial = st.get("dial", 0)
        self.lb.setText(f"WSJT-X : {st.get('mode', '')} sur {dial / 1e6:.3f} MHz".replace(".", ",")
                        + (" — émission" if st.get("transmitting") else ""))

    def on_decode(self, d):
        self.heard[d["call"]] = d
        if len(self.heard) > 400:
            for k in list(self.heard)[:100]:
                self.heard.pop(k, None)
        if self.isVisible():
            self.refresh()

    def refresh(self):
        from .geo import distance_bearing, from_locator
        pos = getattr(self.win, "station", None)
        rows = [d for d in reversed(list(self.heard.values())) if d["cq"] or not self.ck_cq.isChecked()]
        self.rows = rows
        self.tbl.setRowCount(len(rows))
        for i, d in enumerate(rows):
            dist = ""
            if pos and d.get("grid"):
                try:
                    km, brg = distance_bearing(*pos, *from_locator(d["grid"]))
                    dist = f"{km:.0f} km {brg:.0f}°"
                except ValueError:
                    pass
            new = not self.win.worked_before(d["call"])
            for c, val in enumerate([d["call"], f"{d['snr']:+d}", str(d["df"]), d.get("grid") or "", dist, d["text"]]):
                it = QTableWidgetItem(val)
                if d["cq"] and new:
                    it.setForeground(QColor("#5fdc5a"))
                elif not new:
                    it.setForeground(QColor("#7a7a7a"))
                self.tbl.setItem(i, c, it)

    def reply(self, row, _col):
        if 0 <= row < len(getattr(self, "rows", [])):
            self.listener.reply_to(self.rows[row])
            if self.rows[row].get("grid"):
                self.win.point_rotor_to_grid(self.rows[row]["grid"])
            self.lb.setText(f"Appel de {self.rows[row]['call']} demandé à WSJT-X")

    def on_logged(self, text):
        from . import adif
        from .logbook import band_of_mhz
        if not self.ck_log.isChecked():
            return
        for r in adif.parse(text):
            if not r.get("band"):
                r["band"] = band_of_mhz(r.get("freq"))
            if r.get("call") and not self.log.is_dupe(r):
                self.log.add(r)
                self.win.statusBar().showMessage(f"QSO WSJT-X avec {r['call'].upper()} inscrit au carnet")

    def save_settings(self, s):
        s.setValue("wsjtx_port", self.sp_port.value())
        s.setValue("wsjtx_group", self.ed_group.text())
        s.setValue("wsjtx_autolog", "true" if self.ck_log.isChecked() else "false")
        s.setValue("wsjtx_on", "true" if self.b_on.isChecked() else "false")
        self.listener.stop()
