"""Panoramique avec une clé SDR (RTL-SDR, NooElec…) : spectre et chute d'eau large.

Deux sources :
- rtl_tcp (réseau) : la clé peut être sur ce PC ou sur un Raspberry Pi ;
- clé USB directe (pyrtlsdr), pilote WinUSB installé avec Zadig.
Le SDR doit avoir sa propre antenne, ou un coupleur protégé : jamais
directement sur la sortie d'un émetteur. En HF, utiliser un convertisseur
(Ham It Up, décalage 125 MHz) ou l'échantillonnage direct (clé V3).
"""
import socket
import struct
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from .waterfall import LUT

try:
    from rtlsdr import RtlSdr
    USB_ERROR = ""
except Exception as e:           # bibliothèque ou pilote absent
    RtlSdr = None
    USB_ERROR = str(e)

FFT = 2048
RATES = [1_024_000, 2_048_000, 2_400_000]


class RtlTcp:
    """Client du protocole rtl_tcp."""

    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        hdr = self._recv(12)
        if hdr[:4] != b"RTL0":
            raise OSError("ce serveur ne parle pas rtl_tcp")
        self.sock.settimeout(2.0)

    def _recv(self, n):
        b = b""
        while len(b) < n:
            c = self.sock.recv(n - len(b))
            if not c:
                raise OSError("liaison rtl_tcp coupée")
            b += c
        return b

    def cmd(self, code, value):
        self.sock.sendall(struct.pack(">BI", code, int(value) & 0xFFFFFFFF))

    def set_freq(self, hz):
        self.cmd(0x01, hz)

    def set_rate(self, sr):
        self.cmd(0x02, sr)

    def set_gain(self, tenth_db):
        if tenth_db is None:
            self.cmd(0x03, 0)
        else:
            self.cmd(0x03, 1)
            self.cmd(0x04, tenth_db)

    def set_ppm(self, ppm):
        self.cmd(0x05, ppm)

    def set_direct(self, mode):
        self.cmd(0x09, mode)

    def read(self, n):
        raw = np.frombuffer(self._recv(2 * n), dtype=np.uint8).astype(np.float32)
        return (raw[0::2] - 127.5) / 127.5 + 1j * (raw[1::2] - 127.5) / 127.5

    def close(self):
        self.sock.close()


class RtlUsb:
    """Clé RTL-SDR branchée sur ce PC (pyrtlsdr)."""

    def __init__(self, index=0):
        if RtlSdr is None:
            raise OSError(f"bibliothèque RTL-SDR indisponible ({USB_ERROR})")
        self.dev = RtlSdr(index)

    def set_freq(self, hz):
        self.dev.center_freq = hz

    def set_rate(self, sr):
        self.dev.sample_rate = sr

    def set_gain(self, tenth_db):
        self.dev.gain = "auto" if tenth_db is None else tenth_db / 10

    def set_ppm(self, ppm):
        if ppm:
            self.dev.freq_correction = ppm

    def set_direct(self, mode):
        self.dev.set_direct_sampling(mode)

    def read(self, n):
        return self.dev.read_samples(n)

    def close(self):
        self.dev.close()


class SdrWorker(QObject):
    spectrum = Signal(object, int, int)      # dB par case, fréquence centrale, largeur affichée
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.dev = None
        self._run = False
        self.center = 0
        self.offset = 0
        self.rate = 2_048_000
        self._pending = {}
        self.lock = threading.Lock()

    def start(self, dev, rate, gain, ppm, direct, offset):
        self.stop()
        self.dev, self.rate, self.offset = dev, rate, offset
        dev.set_rate(rate)
        dev.set_gain(gain)
        dev.set_ppm(ppm)
        if direct:
            dev.set_direct(2)
        self._run = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._run = False
        time.sleep(0.05)
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = None

    def tune(self, hz):
        with self.lock:
            self._pending["freq"] = hz

    def set_gain(self, g):
        with self.lock:
            self._pending["gain"] = g

    def _loop(self):
        win = np.hanning(FFT).astype(np.float32)
        frames = 8
        errors = 0
        while self._run and self.dev:
            try:
                with self.lock:
                    pend, self._pending = self._pending, {}
                if "freq" in pend:
                    self.center = int(pend["freq"])
                    self.dev.set_freq(self.center + self.offset)
                if "gain" in pend:
                    self.dev.set_gain(pend["gain"])
                x = self.dev.read(FFT * frames)
                acc = np.zeros(FFT, np.float32)
                for k in range(frames):
                    seg = x[k * FFT:(k + 1) * FFT]
                    acc += np.abs(np.fft.fftshift(np.fft.fft((seg - seg.mean()) * win))) ** 2
                db = 10 * np.log10(acc / frames + 1e-12)
                keep = int(FFT * 0.8)                     # on retire les bords filtrés
                cut = (FFT - keep) // 2
                self.spectrum.emit(db[cut:cut + keep], self.center, int(self.rate * 0.8))
                errors = 0
            except Exception as e:
                errors += 1
                if errors >= 3:
                    self.status.emit(f"SDR : {e}")
                    break
                time.sleep(0.2)
        self._run = False


class Panadapter(QWidget):
    clicked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cols, self.rows = 800, 160
        self.img = np.full((self.rows, self.cols), 0xFF000000, np.uint32)
        self.line = None
        self.center = self.span = 0
        self.radio = 0
        self.ref, self.range_db = -20.0, 60.0
        self.floor = None
        self.setMouseTracking(True)
        self.setToolTip("Clic : accorder le poste sur ce signal")

    def push(self, db, center, span):
        cols = np.interp(np.linspace(0, len(db) - 1, self.cols), np.arange(len(db)), db)
        floor = float(np.percentile(cols, 25))
        self.floor = floor if self.floor is None else 0.9 * self.floor + 0.1 * floor
        self.line = cols
        self.center, self.span = center, span
        lvl = np.clip((cols - self.floor - 3) / self.range_db * 1.6, 0, 1)
        self.img[1:] = self.img[:-1]
        self.img[0] = LUT[(lvl * 255).astype(np.uint8)]
        self.update()

    def x_of(self, hz, w):
        return (hz - (self.center - self.span / 2)) / self.span * w if self.span else -1

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        hs = int(h * 0.4)
        p.fillRect(0, 0, w, hs, QColor("#000"))
        if self.line is not None and self.floor is not None:
            p.setPen(QPen(QColor("#6fe06a"), 1))
            lo = self.floor - 5
            pts = []
            for i, v in enumerate(self.line):
                y = hs - 4 - (v - lo) / self.range_db * (hs - 8)
                pts.append((i / (self.cols - 1) * w, max(2, min(hs - 2, y))))
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
        img = QImage(self.img.data, self.cols, self.rows, self.cols * 4, QImage.Format_RGB32)
        p.drawImage(QRectF(0, hs, w, h - hs), img)
        if self.span:
            f = QFont()
            f.setPointSize(7)
            p.setFont(f)
            step = 100_000 if self.span > 600_000 else 50_000 if self.span > 250_000 else 10_000
            start = int((self.center - self.span / 2) // step + 1) * step
            p.setPen(QPen(QColor(255, 255, 255, 120), 1))
            for fq in range(start, int(self.center + self.span / 2), step):
                x = self.x_of(fq, w)
                p.drawLine(int(x), hs - 6, int(x), hs)
                p.drawText(QRectF(x - 40, 2, 80, 12), Qt.AlignCenter, f"{fq / 1e6:.3f}".replace(".", ","))
            x = self.x_of(self.radio, w)
            if 0 <= x <= w:
                p.setPen(QPen(QColor("#ff3a2a"), 1.5))
                p.drawLine(int(x), 14, int(x), h)

    def mousePressEvent(self, e):
        if self.span and e.button() == Qt.LeftButton:
            hz = self.center - self.span / 2 + e.position().x() / self.width() * self.span
            self.clicked.emit(int(round(hz / 100) * 100))


class SdrDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Panoramique SDR", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("sdrdock")
        s = win.settings
        self.worker = SdrWorker()
        self.worker.spectrum.connect(self.on_spectrum)
        self.worker.status.connect(lambda m: (self.lb.setText(m), self._uncheck()))
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        self.cb_src = QComboBox()
        self.cb_src.addItem("rtl_tcp (réseau)", "tcp")
        self.cb_src.addItem("Clé RTL-SDR USB", "usb")
        self.cb_src.setCurrentIndex(max(0, self.cb_src.findData(s.value("sdr_src", "tcp"))))
        self.ed_host = QLineEdit(s.value("sdr_host", "127.0.0.1:1234"))
        self.cb_rate = QComboBox()
        for r in RATES:
            self.cb_rate.addItem(f"{r / 1e6:.3f} MHz".replace(".", ","), r)
        self.cb_rate.setCurrentIndex(max(0, self.cb_rate.findData(int(s.value("sdr_rate", 2_048_000)))))
        self.sp_off = QDoubleSpinBox()
        self.sp_off.setRange(-2000, 2000)
        self.sp_off.setDecimals(3)
        self.sp_off.setSuffix(" MHz")
        self.sp_off.setValue(float(s.value("sdr_offset", 0)))
        self.sp_off.setToolTip("Décalage d'un convertisseur : 125 MHz pour un Ham It Up")
        self.ck_direct = QCheckBox("Échantillonnage direct (HF, clé V3)")
        self.ck_direct.setChecked(s.value("sdr_direct", "false") == "true")
        self.sp_ppm = QDoubleSpinBox()
        self.sp_ppm.setRange(-100, 100)
        self.sp_ppm.setDecimals(0)
        self.sp_ppm.setSuffix(" ppm")
        self.sp_ppm.setValue(float(s.value("sdr_ppm", 0)))
        self.sl_gain = QSlider(Qt.Horizontal)
        self.sl_gain.setRange(-1, 496)
        self.sl_gain.setValue(int(s.value("sdr_gain", -1)))
        self.sl_gain.setToolTip("Gain (tout à gauche : automatique)")
        self.sl_gain.valueChanged.connect(lambda g: self.worker.set_gain(None if g < 0 else g))
        self.b_on = QPushButton("Démarrer")
        self.b_on.setCheckable(True)
        self.b_on.toggled.connect(self.toggle)
        g.addWidget(self.cb_src, 0, 0)
        g.addWidget(self.ed_host, 0, 1)
        g.addWidget(self.b_on, 0, 2)
        g.addWidget(QLabel("Largeur"), 1, 0)
        g.addWidget(self.cb_rate, 1, 1)
        g.addWidget(self.sp_ppm, 1, 2)
        g.addWidget(QLabel("Convertisseur"), 2, 0)
        g.addWidget(self.sp_off, 2, 1)
        g.addWidget(self.ck_direct, 2, 2)
        g.addWidget(QLabel("Gain"), 3, 0)
        g.addWidget(self.sl_gain, 3, 1, 1, 2)
        v.addLayout(g)
        self.pan = Panadapter()
        self.pan.clicked.connect(self.on_click)
        v.addWidget(self.pan, 1)
        self.lb = QLabel("Antenne séparée ou coupleur protégé obligatoire : jamais sur la sortie de l'émetteur.")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        self.setWidget(w)
        self.setMinimumWidth(520)
        self.cb_src.currentIndexChanged.connect(lambda: self.ed_host.setVisible(self.cb_src.currentData() == "tcp"))
        self.ed_host.setVisible(self.cb_src.currentData() == "tcp")
        self.ctrl.state_changed.connect(self.on_state)

    def toggle(self, on):
        if not on:
            self.worker.stop()
            self.b_on.setText("Démarrer")
            return
        try:
            if self.cb_src.currentData() == "tcp":
                host, _, port = self.ed_host.text().strip().rpartition(":")
                dev = RtlTcp(host or "127.0.0.1", int(port or 1234))
            else:
                dev = RtlUsb()
            g = self.sl_gain.value()
            self.worker.start(dev, self.cb_rate.currentData(), None if g < 0 else g,
                              int(self.sp_ppm.value()), self.ck_direct.isChecked(),
                              int(self.sp_off.value() * 1e6))
        except Exception as e:
            self.lb.setText(f"SDR injoignable : {e}")
            self._uncheck()
            return
        st = self.ctrl.snapshot()
        self._retune(st.freq or 145_000_000, force=True)
        self.b_on.setText("Arrêter")
        self.lb.setText("SDR en marche. Clic sur un signal : le poste s'y accorde.")

    def _uncheck(self):
        self.b_on.blockSignals(True)
        self.b_on.setChecked(False)
        self.b_on.blockSignals(False)
        self.b_on.setText("Démarrer")

    def _retune(self, radio, force=False):
        span = self.cb_rate.currentData() * 0.8
        c = self.worker.center
        if force or abs(radio - c) > span * 0.4:
            self.worker.tune(int(radio + span / 4))     # le poste hors de la raie centrale du SDR

    def on_state(self, st):
        self.pan.radio = st.freq
        if self.worker.dev and st.freq:
            self._retune(st.freq)

    def on_spectrum(self, db, center, span):
        if self.isVisible():
            self.pan.push(db, center, span)

    def on_click(self, hz):
        if self.ctrl.connected:
            self.ctrl.set_freq(hz)

    def save_settings(self, s):
        s.setValue("sdr_src", self.cb_src.currentData())
        s.setValue("sdr_host", self.ed_host.text())
        s.setValue("sdr_rate", self.cb_rate.currentData())
        s.setValue("sdr_offset", self.sp_off.value())
        s.setValue("sdr_direct", "true" if self.ck_direct.isChecked() else "false")
        s.setValue("sdr_ppm", self.sp_ppm.value())
        s.setValue("sdr_gain", self.sl_gain.value())
        self.worker.stop()
