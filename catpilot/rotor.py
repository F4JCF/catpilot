"""Commande de rotor d'antenne : Yaesu GS-232 (port série) ou rotctld (Hamlib, réseau).

Un fil d'exécution interroge la position chaque seconde et envoie les ordres.
L'élévation est prise en charge quand le rotor en dispose (GS-232B, rotctld).
"""
import math
import queue
import re
import socket
import threading
import time

import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .geo import distance_bearing, from_locator


class RotorError(Exception):
    pass


class GS232:
    """Yaesu GS-232A/B et compatibles (ERC, K3NG, ARS en mode GS-232)."""

    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baud, timeout=0.5, write_timeout=0.5)
        self.has_el = True

    def _ask(self, cmd):
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii"))
        return self.ser.read_until(b"\r").decode("ascii", "ignore").strip()

    def position(self):
        r = self._ask("C2")
        nums = [int(x) for x in re.findall(r"[+-]?\d+", r)]
        if not nums:
            r = self._ask("C")
            nums = [int(x) for x in re.findall(r"[+-]?\d+", r)]
        if not nums:
            raise RotorError("le rotor ne répond pas")
        if len(nums) < 2:
            self.has_el = False
            return nums[0] % 360, None
        return nums[0] % 360, nums[1]

    def go(self, az, el=None):
        az = int(round(az)) % 360
        if el is not None and self.has_el:
            self.ser.write(f"W{az:03d} {int(round(max(0, min(180, el)))):03d}\r".encode("ascii"))
        else:
            self.ser.write(f"M{az:03d}\r".encode("ascii"))

    def stop(self):
        self.ser.write(b"S\r")

    def close(self):
        self.ser.close()


class Rotctld:
    """Serveur rotctld de Hamlib (par défaut port 4533)."""

    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=3)
        self.f = self.sock.makefile("rw", encoding="ascii", newline="\n")
        self.has_el = True

    def _ask(self, cmd, lines):
        self.f.write(cmd + "\n")
        self.f.flush()
        return [self.f.readline().strip() for _ in range(lines)]

    def position(self):
        az, el = self._ask("p", 2)
        try:
            return float(az) % 360, float(el)
        except ValueError:
            raise RotorError(f"réponse inattendue : {az} {el}")

    def go(self, az, el=None):
        cur_el = 0.0 if el is None else el
        self._ask(f"P {az:.1f} {cur_el:.1f}", 1)

    def stop(self):
        self._ask("S", 1)

    def close(self):
        self.sock.close()


class SimRotor:
    """Rotor simulé : 6°/s en azimut, 3°/s en élévation."""

    def __init__(self):
        self.az, self.el, self.taz, self.tel = 0.0, 0.0, None, None
        self.t = time.monotonic()
        self.has_el = True

    def _move(self):
        now = time.monotonic()
        dt, self.t = now - self.t, now
        if self.taz is not None:
            d = self.taz - self.az
            self.az += max(-6 * dt, min(6 * dt, d))
        if self.tel is not None:
            d = self.tel - self.el
            self.el += max(-3 * dt, min(3 * dt, d))

    def position(self):
        self._move()
        return self.az, self.el

    def go(self, az, el=None):
        self._move()
        self.taz = az % 360
        if el is not None:
            self.tel = max(0, min(90, el))

    def stop(self):
        self._move()
        self.taz = self.tel = None

    def close(self):
        pass


class Rotor(QObject):
    position = Signal(float, object)      # azimut, élévation (ou None)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.dev = None
        self.q = queue.Queue()
        self._run = False
        self.az, self.el = None, None
        self.target = None

    @property
    def connected(self):
        return self.dev is not None

    def connect_rotor(self, kind, a, b):
        self.disconnect()
        if kind == "gs232":
            self.dev = GS232(a, int(b))
        elif kind == "rotctld":
            self.dev = Rotctld(a, int(b))
        else:
            self.dev = SimRotor()
        self._run = True
        threading.Thread(target=self._loop, daemon=True).start()

    def disconnect(self):
        self._run = False
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = None

    def go(self, az, el=None):
        self.target = (az % 360, el)
        self.q.put(("go", az % 360, el))

    def stop(self):
        self.target = None
        self.q.put(("stop",))

    def _loop(self):
        errors = 0
        while self._run and self.dev:
            try:
                while True:
                    try:
                        cmd = self.q.get_nowait()
                    except queue.Empty:
                        break
                    if cmd[0] == "go":
                        self.dev.go(cmd[1], cmd[2])
                    else:
                        self.dev.stop()
                az, el = self.dev.position()
                self.az, self.el = az, el
                self.position.emit(az, el)
                errors = 0
            except Exception as e:
                errors += 1
                if errors >= 5:
                    self.status.emit(f"Rotor : liaison perdue ({e})")
                    self.dev = None
                    break
            time.sleep(1.0)


class Compass(QWidget):
    """Rose des vents : aiguille verte = position, trait orangé = cible. Clic = aller."""
    clicked = Signal(float)

    def __init__(self):
        super().__init__()
        self.az, self.target = None, None
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setToolTip("Clic : orienter l'antenne dans cette direction")

    def heightForWidth(self, w):
        return w

    def _geom(self):
        s = min(self.width(), self.height()) - 30
        return QPointF(self.width() / 2, self.height() / 2), s / 2

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, r = self._geom()
        p.setPen(QPen(QColor("#5a5a5a"), 1.5))
        p.drawEllipse(c, r, r)
        p.drawEllipse(c, r * 0.5, r * 0.5)
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        for deg in range(0, 360, 10):
            a = math.radians(deg)
            inner = r * (0.88 if deg % 30 else 0.8)
            p.setPen(QPen(QColor("#9a9a9a"), 1))
            p.drawLine(QPointF(c.x() + inner * math.sin(a), c.y() - inner * math.cos(a)),
                       QPointF(c.x() + r * math.sin(a), c.y() - r * math.cos(a)))
        for deg, label in ((0, "N"), (90, "E"), (180, "S"), (270, "O")):
            a = math.radians(deg)
            p.setPen(QColor("#f2b705"))
            q = QPointF(c.x() + (r + 11) * math.sin(a), c.y() - (r + 11) * math.cos(a))
            p.drawText(QRectF(q.x() - 10, q.y() - 8, 20, 16), Qt.AlignCenter, label)
        if self.target is not None:
            a = math.radians(self.target)
            p.setPen(QPen(QColor("#f2a03a"), 2, Qt.DashLine))
            p.drawLine(c, QPointF(c.x() + r * math.sin(a), c.y() - r * math.cos(a)))
        if self.az is not None:
            a = math.radians(self.az)
            p.setPen(QPen(QColor("#5fdc5a"), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(c, QPointF(c.x() + r * 0.92 * math.sin(a), c.y() - r * 0.92 * math.cos(a)))
            p.setPen(QColor("#5fdc5a"))
            f.setPointSize(13)
            p.setFont(f)
            p.drawText(QRectF(c.x() - 40, c.y() + r * 0.15, 80, 24), Qt.AlignCenter, f"{self.az:.0f}°")

    def mousePressEvent(self, e):
        c, _r = self._geom()
        dx, dy = e.position().x() - c.x(), e.position().y() - c.y()
        self.clicked.emit((math.degrees(math.atan2(dx, -dy)) + 360) % 360)


class RotorDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Rotor d'antenne", win)
        self.win = win
        self.setObjectName("rotordock")
        s = win.settings
        self.rotor = Rotor()
        self.rotor.position.connect(self.on_position)
        self.rotor.status.connect(lambda m: self.lb.setText(m))
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        self.cb_kind = QComboBox()
        for label, key in (("Yaesu GS-232 (port série)", "gs232"), ("rotctld (Hamlib, réseau)", "rotctld"),
                           ("Rotor simulé", "sim")):
            self.cb_kind.addItem(label, key)
        self.cb_kind.setCurrentIndex(max(0, self.cb_kind.findData(s.value("rot_kind", "gs232"))))
        self.cb_kind.currentIndexChanged.connect(self._kind_changed)
        self.cb_port = QComboBox()
        self.cb_port.setEditable(True)
        for p in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device):
            self.cb_port.addItem(p.device)
        self.ed_host = QLineEdit(s.value("rot_host", "127.0.0.1:4533"))
        self.cb_baud = QComboBox()
        self.cb_baud.addItems(["1200", "4800", "9600", "19200"])
        self.cb_baud.setCurrentText(s.value("rot_baud", "9600"))
        if s.value("rot_port", ""):
            self.cb_port.setCurrentText(s.value("rot_port", ""))
        self.b_conn = QPushButton("Connecter")
        self.b_conn.setCheckable(True)
        self.b_conn.toggled.connect(self.toggle)
        g.addWidget(QLabel("Rotor"), 0, 0)
        g.addWidget(self.cb_kind, 0, 1, 1, 2)
        g.addWidget(self.cb_port, 1, 0, 1, 2)
        g.addWidget(self.cb_baud, 1, 2)
        g.addWidget(self.ed_host, 2, 0, 1, 3)
        g.addWidget(self.b_conn, 3, 0, 1, 3)
        v.addLayout(g)
        self.compass = Compass()
        self.compass.clicked.connect(self.go_az)
        v.addWidget(self.compass, 1)
        self.lb_el = QLabel("")
        self.lb_el.setObjectName("value")
        self.lb_el.setAlignment(Qt.AlignCenter)
        v.addWidget(self.lb_el)
        h = QHBoxLayout()
        self.sp_az = QSpinBox()
        self.sp_az.setRange(0, 359)
        self.sp_az.setSuffix("°")
        b = QPushButton("Aller")
        b.clicked.connect(lambda: self.go_az(self.sp_az.value()))
        h.addWidget(QLabel("Cap"))
        h.addWidget(self.sp_az)
        h.addWidget(b)
        b = QPushButton("Stop")
        b.clicked.connect(self.rotor.stop)
        h.addWidget(b)
        v.addLayout(h)
        h = QHBoxLayout()
        self.ed_loc = QLineEdit()
        self.ed_loc.setPlaceholderText("Viser un locator (ex. JO40)")
        self.ed_loc.returnPressed.connect(lambda: self.point_to_grid(self.ed_loc.text()))
        h.addWidget(self.ed_loc, 1)
        self.ck_long = QCheckBox("Long path")
        h.addWidget(self.ck_long)
        v.addLayout(h)
        self.ck_spots = QCheckBox("Orienter vers les spots, le carnet et WSJT-X (double-clic)")
        self.ck_spots.setChecked(s.value("rot_follow", "true") == "true")
        v.addWidget(self.ck_spots)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        self.setWidget(w)
        self._kind_changed()

    def _kind_changed(self):
        k = self.cb_kind.currentData()
        self.cb_port.setVisible(k == "gs232")
        self.cb_baud.setVisible(k == "gs232")
        self.ed_host.setVisible(k == "rotctld")

    def toggle(self, on):
        if not on:
            self.rotor.disconnect()
            self.b_conn.setText("Connecter")
            self.lb.setText("Déconnecté")
            return
        k = self.cb_kind.currentData()
        try:
            if k == "gs232":
                self.rotor.connect_rotor(k, self.cb_port.currentText(), self.cb_baud.currentText())
            elif k == "rotctld":
                host, _, port = self.ed_host.text().strip().rpartition(":")
                self.rotor.connect_rotor(k, host or "127.0.0.1", int(port or 4533))
            else:
                self.rotor.connect_rotor(k, None, None)
        except Exception as e:
            self.lb.setText(f"Rotor injoignable : {e}")
            self.b_conn.blockSignals(True)
            self.b_conn.setChecked(False)
            self.b_conn.blockSignals(False)
            return
        self.b_conn.setText("Déconnecter")
        self.lb.setText("Rotor connecté")

    def follow_spots(self):
        return self.ck_spots.isChecked() and self.rotor.connected

    def go_az(self, az, el=None):
        if not self.rotor.connected:
            self.lb.setText("Connectez d'abord le rotor")
            return
        self.compass.target = az
        self.compass.update()
        self.rotor.go(az, el)
        self.lb.setText(f"Rotation vers {az:.0f}°" + (f", élévation {el:.0f}°" if el is not None else ""))

    def point_to_grid(self, grid):
        pos = getattr(self.win, "station", None)
        if not pos:
            self.lb.setText("Indiquez d'abord la position de la station (menu Poste)")
            return
        try:
            d, b = distance_bearing(*pos, *from_locator(grid.strip()))
        except ValueError as e:
            self.lb.setText(str(e))
            return
        if self.ck_long.isChecked():
            b, d = (b + 180) % 360, 40030 - d
        self.go_az(b)
        self.lb.setText(f"{grid.upper()} : {d:.0f} km, cap {b:.0f}°" + (" (long path)" if self.ck_long.isChecked() else ""))

    def on_position(self, az, el):
        self.compass.az = az
        self.compass.update()
        self.lb_el.setText(f"Azimut {az:.0f}°" + (f"   Élévation {el:.0f}°" if el is not None else ""))

    def save_settings(self, s):
        s.setValue("rot_kind", self.cb_kind.currentData())
        s.setValue("rot_port", self.cb_port.currentText())
        s.setValue("rot_baud", self.cb_baud.currentText())
        s.setValue("rot_host", self.ed_host.text())
        s.setValue("rot_follow", "true" if self.ck_spots.isChecked() else "false")
        self.rotor.disconnect()
