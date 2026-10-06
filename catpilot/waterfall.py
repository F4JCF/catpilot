"""Chute d'eau (waterfall) à partir de la carte son USB du FT-991A.

Le CAT du FT-991A ne transmet pas les données du scope. On analyse donc
l'audio de réception fourni par le codec USB du poste (« USB Audio CODEC »),
comme le fait WSJT-X : on voit environ 3 kHz autour de la fréquence affichée.
"""
import collections
import math

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

try:
    import sounddevice as sd
    SD_ERROR = ""
except Exception as e:          # module absent ou bibliothèque PortAudio introuvable
    sd = None
    SD_ERROR = str(e)

TEST_DEVICE = "test"
FFT_SIZE = 4096


def _make_lut():
    stops = [(0.0, (0, 0, 0)), (0.25, (0, 0, 150)), (0.5, (0, 170, 230)),
             (0.7, (240, 230, 0)), (0.88, (255, 70, 0)), (1.0, (255, 255, 255))]
    lut = np.zeros(256, np.uint32)
    for i in range(256):
        f = i / 255
        for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
            if f <= f1:
                t = (f - f0) / (f1 - f0)
                r, g, b = (int(a + (b_ - a) * t) for a, b_ in zip(c0, c1))
                lut[i] = 0xFF000000 | (r << 16) | (g << 8) | b
                break
    return lut


LUT = _make_lut()


def list_inputs():
    """Entrées audio disponibles : [(identifiant, libellé)]."""
    out = [(TEST_DEVICE, "Signal de test (sans poste)")]
    if not sd:
        return out
    try:
        apis = sd.query_hostapis()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                out.append((i, f'{d["name"]} ({apis[d["hostapi"]]["name"]})'))
    except Exception:
        pass
    return out


def guess_radio_input(inputs):
    """Repère le codec USB du poste, de préférence via MME (le plus tolérant sous Windows)."""
    best = None
    for dev, label in inputs:
        low = label.lower()
        if "usb audio codec" in low or "codec" in low:
            if "mme" in low:
                return dev
            best = best if best is not None else dev
    return best


class Waterfall(QWidget):
    COLS, ROWS = 640, 150
    FMAX = 3200                      # Hz affichés
    hover = Signal(object)           # fréquence audio sous la souris (ou None)
    clicked = Signal(int)            # fréquence audio cliquée

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(100)
        self.setMouseTracking(True)
        self.img = np.full((self.ROWS, self.COLS), 0xFF000000, np.uint32)
        self.chunks = collections.deque(maxlen=200)
        self.hist = np.zeros(0, np.float32)
        self.win = np.hanning(FFT_SIZE).astype(np.float32)
        self.sr = 48000
        self.stream = None
        self.test = False
        self._phase = 0.0
        self._t = 0.0
        self.contrast = 45.0          # dB couverts par la palette
        self.offset = 5.0             # dB au-dessus du bruit de fond
        self.floor = None
        self.message = "Chute d'eau arrêtée"
        self.marker = None            # fréquence audio où un clic amène le signal
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60)

    # --- démarrage / arrêt --------------------------------------------------
    def start(self, device):
        self.stop()
        self.floor = None
        self.hist = np.zeros(0, np.float32)
        if device == TEST_DEVICE:
            self.test, self.sr = True, 12000
        else:
            if not sd:
                raise RuntimeError("Le module audio n'est pas disponible : " + (SD_ERROR or "?"))
            info = sd.query_devices(device)
            self.sr = int(info["default_samplerate"]) or 48000
            self.stream = sd.InputStream(device=device, channels=1, samplerate=self.sr,
                                         blocksize=1024, dtype="float32", callback=self._cb)
            self.stream.start()
        self.message = ""

    def stop(self):
        self.test = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.message = "Chute d'eau arrêtée"
        self.update()

    @property
    def running(self):
        return self.test or self.stream is not None

    def _cb(self, indata, frames, t, status):       # fil audio
        self.chunks.append(indata[:, 0].copy())

    # --- signal de test : quelques porteuses façon FT8 sur du bruit ----------
    def _test_samples(self, dt):
        n = int(self.sr * dt)
        t = self._t + np.arange(n) / self.sr
        x = np.random.normal(0, 0.02, n).astype(np.float32)
        for f, a, period in ((620, 0.05, 15), (1180, 0.02, 15), (1525, 0.08, 15),
                             (2230, 0.03, 7.5), (2760, 0.015, 15)):
            if (self._t // period) % 2 == (0 if f != 1180 else 1):
                fm = f + 6.25 * ((t * 6.25).astype(int) % 8)        # 8 tonalités
                x += a * np.sin(2 * math.pi * fm * t).astype(np.float32)
        self._t += n / self.sr
        return x

    # --- traitement -------------------------------------------------------------
    def _tick(self):
        new = []
        if self.test:
            new.append(self._test_samples(0.06))
        while self.chunks:
            new.append(self.chunks.popleft())
        if not new:
            return
        self.hist = np.concatenate([self.hist] + new)[-FFT_SIZE:]
        if len(self.hist) < FFT_SIZE:
            return
        spec = 20 * np.log10(np.abs(np.fft.rfft(self.hist * self.win)) + 1e-9)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1 / self.sr)
        cols = np.interp(np.linspace(0, self.FMAX, self.COLS), freqs, spec)
        floor = float(np.percentile(cols, 30))
        self.floor = floor if self.floor is None else 0.92 * self.floor + 0.08 * floor
        lvl = np.clip((cols - self.floor - self.offset) / self.contrast, 0, 1)
        self.img[1:] = self.img[:-1]
        self.img[0] = LUT[(lvl * 255).astype(np.uint8)]
        self.update()

    # --- dessin -----------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        qimg = QImage(self.img.data, self.COLS, self.ROWS, self.COLS * 4, QImage.Format_RGB32)
        p.drawImage(r, qimg)
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)
        for f in range(500, self.FMAX, 500):
            x = r.width() * f / self.FMAX
            p.setPen(QPen(QColor(255, 255, 255, 160), 1))
            p.drawLine(int(x), 0, int(x), 5)
            p.drawText(QRectF(x - 20, 5, 40, 12), Qt.AlignCenter, f"{f}")
        if self.marker:
            x = r.width() * self.marker / self.FMAX
            p.setPen(QPen(QColor(255, 255, 255, 110), 1, Qt.DashLine))
            p.drawLine(int(x), 18, int(x), int(r.height()))
        if self.message:
            p.setPen(QColor("#9a9a9a"))
            p.drawText(r, Qt.AlignCenter, self.message)

    def mouseMoveEvent(self, e):
        self.hover.emit(round(e.position().x() / max(1, self.width()) * self.FMAX))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(round(e.position().x() / max(1, self.width()) * self.FMAX))

    def leaveEvent(self, _e):
        self.hover.emit(None)
