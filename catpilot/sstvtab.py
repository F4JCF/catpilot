"""Onglet SSTV : réception d'images (mode reconnu tout seul par l'en-tête VIS) et émission.

Bibliothèque « sstv » (MIT, moteur en Rust). Les images reçues sont enregistrées dans
Documents/CATPilot/sstv.
"""
import datetime
import os

import numpy as np
import sstv
from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from .logbook import data_dir

RATE = 12000
TX_MODES = {"Robot 36": "ROBOT_36", "Robot 72": "ROBOT_72", "Martin 1": "MARTIN_1", "Martin 2": "MARTIN_2",
            "Scottie 1": "SCOTTIE_1", "Scottie 2": "SCOTTIE_2", "Scottie DX": "SCOTTIE_DX", "PD 90": "PD_90",
            "PD 120": "PD_120", "PD 180": "PD_180"}
FREQS = {"80m": 3733, "40m": 7165, "20m": 14230, "17m": 18160, "15m": 21340, "12m": 24975, "10m": 28680,
         "2m (FM)": 144500, "70cm (FM)": 433400}
BUF_SECONDS = 330
RX_TRY = ["ROBOT_36", "MARTIN_1", "SCOTTIE_1", "PD_120", "MARTIN_2", "SCOTTIE_2", "ROBOT_72", "PD_90", "SCOTTIE_DX"]


def clean(x):
    """Filtre 1 000 - 2 450 Hz (enlève porteuses et bruit hors bande) et niveau normalisé."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    w = np.clip((f - 900) / 100, 0, 1) * np.clip((2550 - f) / 100, 0, 1)
    y = np.fft.irfft(X * w, len(x))
    return (y / (np.percentile(np.abs(y), 99.5) + 1e-9) * 0.7).astype(np.float32)


def sstv_dir():
    d = os.path.join(data_dir(), "sstv")
    os.makedirs(d, exist_ok=True)
    return d


def mode_label(m):
    s = str(m).split(".")[-1]
    for k, v in TX_MODES.items():
        if v == s:
            return k
    return s.replace("_", " ").title()


def to_qimage(img):
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    q = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return q.copy()


class Down12k:
    """Passage à 12 000 Hz par blocs (moyenne puis interpolation), suffisant pour la SSTV (< 2,4 kHz)."""

    def __init__(self):
        self.sr = 0

    def run(self, x, sr):
        if sr != self.sr:
            self.sr, self.pos, self.last = sr, 0.0, 0.0
        if sr == RATE:
            return x
        if sr % RATE == 0:
            k = sr // RATE
            x = np.concatenate([getattr(self, "rest", np.zeros(0, np.float32)), x])
            n = len(x) // k
            self.rest = x[n * k:]
            return x[:n * k].reshape(n, k).mean(axis=1).astype(np.float32)
        step = sr / RATE
        xx = np.concatenate([[self.last], x])
        idx = np.arange(self.pos, len(xx) - 1, step)
        self.pos = idx[-1] + step - (len(xx) - 1) if len(idx) else self.pos - (len(xx) - 1)
        self.last = xx[-1]
        i = idx.astype(int)
        f = idx - i
        return (xx[i] * (1 - f) + xx[i + 1] * f).astype(np.float32)


class Preview(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #111; color: #888;")
        self._img = None

    def set_image(self, q):
        self._img = q
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        if self._img is not None:
            self.setPixmap(QPixmap.fromImage(self._img).scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class SstvTab(QWidget):
    def __init__(self, dock):
        super().__init__()
        self.dock, self.win = dock, dock.win
        s = self.win.settings
        self.down = Down12k()
        self.buf = np.zeros(RATE * BUF_SECONDS, np.float32)
        self.n = 0                        # échantillons valides dans buf
        self.dirty = False
        self.saved_sig = None
        self.tx_image = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        h = QHBoxLayout()
        self.cb_band = QComboBox()
        for b, khz in FREQS.items():
            self.cb_band.addItem(f"{b}  {khz:g} kHz", khz)
        h.addWidget(self.cb_band)
        b = QPushButton("Aller")
        b.setToolTip("Règle le poste sur la fréquence SSTV habituelle de la bande")
        b.clicked.connect(self.goto_band)
        h.addWidget(b)
        self.lb_rx = QLabel("En attente d'une image…")
        self.lb_rx.setObjectName("value")
        h.addWidget(self.lb_rx, 1)
        self.cb_rxmode = QComboBox()
        self.cb_rxmode.addItem("Mode auto", "")
        for k, val in TX_MODES.items():
            self.cb_rxmode.addItem(k, val)
        self.cb_rxmode.setToolTip("Auto : mode reconnu par l'en-tête de l'image. Choisir le mode aide si le signal est faible.")
        h.addWidget(self.cb_rxmode)
        b = QPushButton("Dossier des images")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(sstv_dir())))
        h.addWidget(b)
        v.addLayout(h)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Réception")
        t.setObjectName("hint")
        lv.addWidget(t)
        self.rx_view = Preview()
        self.rx_view.setText("L'image reçue s'affiche ici\n(mode reconnu tout seul)")
        lv.addWidget(self.rx_view, 1)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(96, 72))
        self.gallery.setMaximumHeight(110)
        self.gallery.setFlow(QListWidget.LeftToRight)
        self.gallery.setWrapping(False)
        self.gallery.itemDoubleClicked.connect(lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.UserRole))))
        self.gallery.itemClicked.connect(lambda it: self.rx_view.set_image(QImage(it.data(Qt.UserRole))))
        lv.addWidget(self.gallery)
        split.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Émission")
        t.setObjectName("hint")
        rv.addWidget(t)
        self.tx_view = Preview()
        self.tx_view.setText("Choisissez une image")
        rv.addWidget(self.tx_view, 1)
        h = QHBoxLayout()
        b = QPushButton("Image…")
        b.clicked.connect(self.pick_image)
        h.addWidget(b)
        b = QPushButton("Dernière reçue")
        b.setToolTip("Renvoyer la dernière image reçue (avec votre texte)")
        b.clicked.connect(self.use_last_rx)
        h.addWidget(b)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(list(TX_MODES))
        self.cb_mode.setCurrentText(s.value("sstv_mode", "Robot 36"))
        self.cb_mode.currentTextChanged.connect(self.render_tx)
        h.addWidget(self.cb_mode)
        rv.addLayout(h)
        h = QHBoxLayout()
        self.ed_txt = QLineEdit(s.value("sstv_text", "{CALL} de {MYCALL}"))
        self.ed_txt.setToolTip("Texte écrit sur l'image ({MYCALL}, {CALL}, {LOC}, {RST})")
        self.ed_txt.textChanged.connect(self.render_tx)
        h.addWidget(self.ed_txt, 1)
        self.ed_call = QLineEdit()
        self.ed_call.setPlaceholderText("{CALL}")
        self.ed_call.setMaximumWidth(100)
        self.ed_call.textChanged.connect(self.render_tx)
        h.addWidget(self.ed_call)
        rv.addLayout(h)
        h = QHBoxLayout()
        self.b_send = QPushButton("Émettre l'image")
        self.b_send.clicked.connect(self.send)
        h.addWidget(self.b_send)
        b = QPushButton("Stop")
        b.clicked.connect(self.dock.tx.stop)
        h.addWidget(b)
        rv.addLayout(h)
        split.addWidget(right)
        split.setSizes([400, 300])
        v.addWidget(split, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        v.addWidget(self.lb)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._decode)
        self.timer.start(2000)
        self._load_gallery()
        self.src = None
        path = s.value("sstv_image", "")
        if path and os.path.exists(path):
            self.load_image(path)
        else:
            self._default_image()

    # --- réception -----------------------------------------------------------------------
    def feed(self, x, sr):
        if self.dock.tx.busy:
            return
        y = self.down.run(np.asarray(x, np.float32), sr)
        n = len(y)
        if not n:
            return
        if self.n + n > len(self.buf):
            keep = len(self.buf) - n
            self.buf[:keep] = self.buf[self.n - keep:self.n]
            self.n = keep
        self.buf[self.n:self.n + n] = y
        self.n += n
        self.dirty = True

    def _decode(self):
        if not self.dirty or not self.isVisible() or self.n < RATE * 3:
            return
        self.dirty = False
        try:
            x = clean(self.buf[:self.n])
            fixed = self.cb_rxmode.currentData()
            imgs = [] if fixed else sstv.decode(x, RATE)
            if not imgs:
                # détection plus sensible quand on indique le mode : on essaie les plus courants
                for name in ([fixed] if fixed else RX_TRY):
                    imgs = sstv.decode(x, RATE, mode=getattr(sstv.Mode, name))
                    if imgs:
                        break
        except Exception as e:
            self.lb.setText(f"SSTV : {e}")
            return
        if not imgs:
            if self.n > RATE * 40:              # rien : on ne garde que les dernières secondes
                keep = RATE * 15
                self.buf[:keep] = self.buf[self.n - keep:self.n]
                self.n = keep
            self.lb_rx.setText(getattr(self, "done_at", "") or "En attente d'une image…")
            return
        img = imgs[-1]
        mode = mode_label(img.info.get("sstv_mode"))
        self.rx_view.set_image(to_qimage(img))
        if img.info.get("sstv_complete"):
            self._save(img, mode)
            self.n = 0                              # l'image est enregistrée : on repart à vide
            self.done_at = self.lb_rx.text()
        else:
            self.lb_rx.setText(f"Réception en cours : {mode}…")
            self.done_at = ""

    def _save(self, img, mode):
        now = datetime.datetime.now()
        path = os.path.join(sstv_dir(), f"SSTV_{now:%Y%m%d_%H%M%S}_{mode.replace(' ', '')}.png")
        img.convert("RGB").save(path)
        self.lb_rx.setText(f"Image reçue ({mode}) à {now:%H:%M:%S}, enregistrée")
        self.win.statusBar().showMessage(f"Image SSTV {mode} reçue : {path}", 10000)
        self._add_thumb(path, front=True)

    def _add_thumb(self, path, front=False):
        it = QListWidgetItem(QIcon(path), os.path.basename(path)[5:18].replace("_", " "))
        it.setData(Qt.UserRole, path)
        it.setToolTip(path)
        if front:
            self.gallery.insertItem(0, it)
        else:
            self.gallery.addItem(it)

    def _load_gallery(self):
        files = sorted((f for f in os.listdir(sstv_dir()) if f.lower().endswith(".png")), reverse=True)[:30]
        for f in files:
            self._add_thumb(os.path.join(sstv_dir(), f))

    # --- émission ------------------------------------------------------------------------
    def goto_band(self):
        ctrl = self.win.ctrl
        if not ctrl.connected:
            self.lb.setText("Pas de poste connecté")
            return
        khz = self.cb_band.currentData()
        ctrl.set_freq(int(khz * 1000))
        ctrl.set_mode("PKTFM" if khz > 100000 else "PKTUSB")

    def _default_image(self):
        img = QImage(320, 256, QImage.Format_RGB888)
        img.fill(QColor("#1b3a5c"))
        p = QPainter(img)
        for i in range(8):
            p.fillRect(i * 40, 170, 40, 86, QColor.fromHsv(i * 45, 200, 230))
        p.end()
        self.src = img
        self.render_tx()

    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Image à émettre", os.path.expanduser("~"),
                                              "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            self.load_image(path)

    def load_image(self, path):
        q = QImage(path)
        if q.isNull():
            self.lb.setText("Image illisible")
            return
        self.src = q.convertToFormat(QImage.Format_RGB888)
        self.src_path = path
        self.render_tx()

    def use_last_rx(self):
        it = self.gallery.item(0)
        if it:
            self.load_image(it.data(Qt.UserRole))

    def _size(self):
        m = getattr(sstv.Mode, TX_MODES[self.cb_mode.currentText()])
        return m, m.image_width, m.image_height

    def render_tx(self, *_):
        if self.src is None:
            return
        _m, w, h = self._size()
        src = self.src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        img = QImage(w, h, QImage.Format_RGB888)
        p = QPainter(img)
        p.drawImage((w - src.width()) // 2, (h - src.height()) // 2, src)
        st = getattr(self.win, "station", None)
        text = (self.ed_txt.text().replace("{MYCALL}", (self.win.settings.value("mycall", "") or "").upper())
                .replace("{CALL}", self.ed_call.text().strip().upper())
                .replace("{LOC}", self.win.b_loc.text().split()[0] if st else "").replace("{RST}", "595")).strip()
        if text:
            f = QFont()
            f.setBold(True)
            f.setPixelSize(max(14, h // 9))
            p.setFont(f)
            r = img.rect().adjusted(6, 4, -6, -4)
            p.setPen(QColor(0, 0, 0))
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
                p.drawText(r.translated(dx, dy), Qt.AlignTop | Qt.AlignHCenter | Qt.TextWordWrap, text)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r, Qt.AlignTop | Qt.AlignHCenter | Qt.TextWordWrap, text)
        p.end()
        self.tx_image = img
        self.tx_view.set_image(img)

    def send(self):
        if self.tx_image is None:
            return
        mode, w, h = self._size()
        q = self.tx_image.convertToFormat(QImage.Format_RGB888)
        ptr = q.constBits()
        arr = np.frombuffer(ptr, np.uint8, q.sizeInBytes()).reshape(h, q.bytesPerLine())[:, :w * 3]
        arr = arr.reshape(h, w, 3).copy()
        sr = self.dock.tx.rate()
        try:
            sig = sstv.encode(Image.fromarray(arr, "RGB"), mode, sample_rate=sr).astype(np.float32) / 32768.0
        except Exception as e:
            self.lb.setText(f"Codage impossible : {e}")
            return
        if self.dock.tx.play(sig * 0.9, sr, label="SSTV"):
            self.dock.owner = self
            self.lb.setText(f"Émission {self.cb_mode.currentText()} : {len(sig) / sr:.0f} s…")

    def tx_finished(self, msg):
        self.lb.setText(msg or "Image émise")
        self.n = 0                                  # on n'essaie pas de décoder sa propre image

    def update_markers(self):
        pass

    def save_settings(self, s):
        s.setValue("sstv_mode", self.cb_mode.currentText())
        s.setValue("sstv_text", self.ed_txt.text())
        if getattr(self, "src_path", ""):
            s.setValue("sstv_image", self.src_path)
