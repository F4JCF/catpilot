"""Interface graphique de CAT Pilot pour Yaesu FT-991A."""
import csv
import json
import math
import sys

import serial.tools.list_ports
from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDockWidget,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .controller import RigController
from .drivers import DRIVERS
from .drivers.sim import SimDriver
from .rigctl_server import RigctlServer

# --- données ----------------------------------------------------------------
MODE_BUTTONS = [("USB", "USB"), ("LSB", "LSB"), ("CW", "CW"), ("CWR", "CW-R"),
                ("AM", "AM"), ("FM", "FM"), ("RTTY", "RTTY-L"), ("RTTYR", "RTTY-U"),
                ("PKTLSB", "DATA-L"), ("PKTUSB", "DATA-U"), ("PKTFM", "DATA-FM"),
                ("C4FM", "C4FM")]
MODE_LABELS = dict(MODE_BUTTONS)

BANDS = [  # nom, début, fin, fréquence par défaut (Région 1)
    ("160m", 1810000, 2000000, 1840000), ("80m", 3500000, 3800000, 3573000),
    ("60m", 5351500, 5366500, 5357000), ("40m", 7000000, 7200000, 7074000),
    ("30m", 10100000, 10150000, 10136000), ("20m", 14000000, 14350000, 14074000),
    ("17m", 18068000, 18168000, 18100000), ("15m", 21000000, 21450000, 21074000),
    ("12m", 24890000, 24990000, 24915000), ("10m", 28000000, 29700000, 28074000),
    ("6m", 50000000, 52000000, 50313000), ("2m", 144000000, 146000000, 144174000),
    ("70cm", 430000000, 440000000, 432174000),
]
STEPS = [("10 Hz", 10), ("100 Hz", 100), ("1 kHz", 1000), ("12,5 kHz", 12500), ("100 kHz", 100000)]

# Largeurs de filtre (index SH) — valeurs indicatives
WIDTH_SSB = {1: 200, 2: 400, 3: 600, 4: 850, 5: 1100, 6: 1350, 7: 1500, 8: 1650, 9: 1800,
             10: 1950, 11: 2100, 12: 2250, 13: 2400, 14: 2500, 15: 2600, 16: 2700,
             17: 2800, 18: 2900, 19: 3000, 20: 3200, 21: 3400}
WIDTH_CW = {1: 50, 2: 100, 3: 150, 4: 200, 5: 250, 6: 300, 7: 350, 8: 400, 9: 450,
            10: 500, 11: 800, 12: 1200, 13: 1400, 14: 1700, 15: 2000, 16: 2400, 17: 3000}
CW_LIKE = ("CW", "CWR", "RTTY", "RTTYR", "PKTUSB", "PKTLSB")

CTCSS = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0,
         103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
         151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5,
         186.2, 189.9, 192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1,
         233.6, 241.8, 250.3, 254.1]
SHIFT_LABELS = ["Simplex", "Décalage +", "Décalage −"]
TONE_MODES = ["Sans tonalité", "TSQ (enc./déc.)", "Tonalité à l'émission", "DCS"]
AGC_LABELS = ["AGC OFF", "AGC FAST", "AGC MID", "AGC SLOW", "AGC AUTO"]
PRE_LABELS = ["IPO", "AMP 1", "AMP 2"]

AMBER, GREEN, RED, TEXT = "#f2b705", "#8cff3a", "#e5463b", "#e6e6e6"

STYLE = f"""
QMainWindow, QWidget {{ background: #050505; color: {TEXT};
    font-family: "Segoe UI", sans-serif; font-size: 9pt; }}
QFrame#panel {{ background: #000; border: 1px solid #5a5a5a; border-radius: 3px; }}
QLabel#ptitle {{ color: {AMBER}; font-weight: bold; font-size: 9.5pt; }}
QLabel#freq {{ color: {GREEN}; background: #000; border: 2px solid #d0d0d0; border-radius: 3px;
    font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 38pt; padding: 0 14px; }}
QLabel#vfob {{ color: {GREEN}; background: #000; border: 2px solid #d0d0d0; border-radius: 3px;
    font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 15pt; padding: 1px 10px; }}
QLabel#info {{ color: {AMBER}; font-weight: bold; }}
QLabel#value {{ color: {AMBER}; }}
QLabel#hint {{ color: #8a8a8a; }}
QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4a4a4a, stop:1 #262626);
    border: 1px solid #1a1a1a; border-radius: 3px; padding: 4px 8px; min-height: 18px; color: {TEXT}; }}
QPushButton:hover {{ background: #555; }}
QPushButton:checked {{ border: 2px solid #f0f0f0; color: {GREEN}; background: #2a2a2a; }}
QPushButton:disabled {{ color: #555; background: #181818; }}
QPushButton#ptt {{ font-size: 13pt; font-weight: bold; min-height: 34px; }}
QPushButton#ptt:checked {{ background: #a01d15; border-color: #ff6a5e; color: #fff; }}
QSlider::groove:horizontal {{ height: 3px; background: #888; }}
QSlider::groove:vertical {{ width: 3px; background: #888; }}
QSlider::handle:horizontal {{ background: #1f8f2a; border: 1px solid #0b4d12; width: 11px; margin: -8px 0; border-radius: 3px; }}
QSlider::handle:vertical {{ background: #1f8f2a; border: 1px solid #0b4d12; height: 11px; margin: 0 -8px; border-radius: 3px; }}
QSlider::handle:disabled {{ background: #444; border-color: #333; }}
QComboBox, QLineEdit, QSpinBox {{ background: #111; border: 1px solid #5a5a5a; border-radius: 3px; padding: 2px 6px; }}
QComboBox QAbstractItemView {{ background: #111; selection-background-color: #333; }}
QProgressBar {{ background: #111; border: 1px solid #444; border-radius: 2px; }}
QProgressBar::chunk {{ background: {AMBER}; }}
QTableWidget {{ background: #000; gridline-color: #333; color: {AMBER}; selection-background-color: #333; }}
QHeaderView::section {{ background: #e8e8e8; color: #000; border: 1px solid #aaa; padding: 2px; }}
QDockWidget {{ color: {AMBER}; font-weight: bold; }}
QStatusBar {{ color: #bdbdbd; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid #aaa; background: #111; }}
QCheckBox::indicator:checked {{ background: {GREEN}; }}
"""


# --- widgets ------------------------------------------------------------------
class Panel(QFrame):
    """Cadre noir avec titre en bas, à la manière d'une face avant."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 4)
        outer.setSpacing(4)
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        outer.addWidget(self.body, 1)
        t = QLabel(title)
        t.setObjectName("ptitle")
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("background: transparent;")
        outer.addWidget(t)


class FreqDisplay(QLabel):
    """Afficheur de fréquence : la molette sur un chiffre règle ce chiffre."""
    tune = Signal(int)
    PLACES = {0: 8, 1: 7, 2: 6, 4: 5, 5: 4, 6: 3, 8: 2, 9: 1, 10: 0}

    def __init__(self, name="freq"):
        super().__init__("  -.---.---")
        self.setObjectName(name)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setToolTip("Molette sur un chiffre pour le régler")
        self.default_step = 100

    def set_freq(self, hz):
        mhz, rest = divmod(int(hz), 1_000_000)
        khz, h = divmod(rest, 1000)
        self.setText(f"{mhz:>3}.{khz:03}.{h:03}")

    def _step_at(self, x):
        txt = self.text()
        w = QFontMetrics(self.font()).horizontalAdvance(txt)
        idx = int((x - (self.width() - w) / 2) // (w / len(txt)))
        p = self.PLACES.get(idx)
        return None if p is None else 10 ** p

    def wheelEvent(self, e):
        n = e.angleDelta().y() // 120
        if n:
            self.tune.emit(n * (self._step_at(e.position().x()) or self.default_step))


class AnalogMeter(QWidget):
    """Galvanomètre à aiguille dessiné en vectoriel."""

    def __init__(self, title, scale, red_from):
        super().__init__()
        self.set_scale(title, scale, red_from)
        self.value = self.target = 0.0
        self.setMinimumSize(QSize(250, 118))
        t = QTimer(self)
        t.timeout.connect(self._animate)
        t.start(30)

    def set_scale(self, title, scale, red_from):
        self.title, self.scale, self.red_from = title, scale, red_from
        self.update()

    def set_value(self, frac):
        self.target = max(0.0, min(1.0, frac))

    def _animate(self):
        d = self.target - self.value
        if abs(d) > 0.002:
            self.value += d * 0.35
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#000"))
        cx, cy, r = w / 2, h * 1.45, h * 1.18
        a0, a1 = 132, 48

        def ang(f):
            return math.radians(a0 - (a0 - a1) * f)

        def pt(f, rr):
            return QPointF(cx + rr * math.cos(ang(f)), cy - rr * math.sin(ang(f)))

        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        ar = a0 - (a0 - a1) * self.red_from
        p.setPen(QPen(QColor("#2fbf3a"), 4, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(rect, int(ar * 16), int((a0 - ar) * 16))
        p.setPen(QPen(QColor(RED), 4, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(rect, int(a1 * 16), int((ar - a1) * 16))
        p.setPen(QPen(QColor(TEXT), 1.3))
        for i in range(31):
            f = i / 30
            p.drawLine(pt(f, r + 3), pt(f, r + (10 if i % 5 == 0 else 6)))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        for f, label in self.scale:
            p.setPen(QColor(RED if f > self.red_from + 1e-6 else TEXT))
            q = pt(f, r + 21)
            p.drawText(QRectF(q.x() - 22, q.y() - 8, 44, 16), Qt.AlignCenter, label)
        p.setPen(QPen(QColor("#ff4d2e"), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pt(self.value, r * 0.72), pt(self.value, r + 12))
        p.setPen(QColor(AMBER))
        p.drawText(QRectF(0, h - 20, w, 18), Qt.AlignCenter, self.title)


S_SCALE = [(12 / 255, "1"), (40 / 255, "3"), (65 / 255, "5"), (95 / 255, "7"),
           (130 / 255, "9"), (172 / 255, "+20"), (220 / 255, "+40"), (1.0, "+60")]
PO_SCALE = [(0, "0"), (0.25, "25"), (0.5, "50"), (0.75, "75"), (1.0, "100 %")]
SWR_SCALE = [(0, "1"), (52 / 255, "1.5"), (89 / 255, "2"), (150 / 255, "3"), (1.0, "∞")]


# --- fenêtre principale ---------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"CAT Pilot {__version__} — Yaesu FT-991A")
        self.settings = QSettings("F4JCF", "CATPilot")
        self.ctrl = RigController()
        self.server = None
        self.band_mem = json.loads(self.settings.value("band_mem", "{}"))
        self.memories = []
        self.toggles, self.sliders, self.combos = {}, {}, {}
        self.controls = []
        self._updating = False
        self._last = None

        self.ctrl.state_changed.connect(self.on_state)
        self.ctrl.status_changed.connect(self.on_status)
        self.ctrl.memories_loaded.connect(self.on_memories)
        self.ctrl.message.connect(lambda m: self.statusBar().showMessage(m))

        self._build_ui()
        self._build_memory_dock()
        self._load_settings()
        self._set_enabled(False)
        t = QTimer(self)
        t.timeout.connect(self.update_clients)
        t.start(1000)

    # --- fabriques de commandes --------------------------------------------
    def _btn(self, label, slot=None, checkable=False):
        b = QPushButton(label)
        b.setCheckable(checkable)
        if slot:
            b.clicked.connect(slot)
        self.controls.append(b)
        return b

    def _toggle(self, key, label):
        b = self._btn(label, checkable=True)
        b.clicked.connect(lambda c, k=key: self.ctrl.set_param(k, c))
        self.toggles[key] = b
        return b

    def _slider(self, key, lo, hi, fmt, vertical=False, step=1):
        s = QSlider(Qt.Vertical if vertical else Qt.Horizontal)
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setPageStep(step * 5)
        val = QLabel("")
        val.setObjectName("value")
        val.setAlignment(Qt.AlignCenter)

        def changed(v, k=key):
            v = round(v / step) * step
            val.setText(fmt(v))
            if not self._updating:
                self.ctrl.set_param(k, v)
        s.valueChanged.connect(changed)
        self.sliders[key] = (s, val, fmt)
        self.controls.append(s)
        return s, val

    def _vslider(self, key, title, lo, hi, fmt):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        s, val = self._slider(key, lo, hi, fmt, vertical=True)
        s.setMinimumHeight(110)
        v.addWidget(s, 1, Qt.AlignHCenter)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        v.addWidget(val)
        return w

    def _combo(self, key, items, slot=None):
        c = QComboBox()
        c.addItems(items)
        c.activated.connect(slot or (lambda i, k=key: self.ctrl.set_param(k, i)))
        self.combos[key] = c
        self.controls.append(c)
        return c

    # --- construction --------------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        g = QGridLayout(root)
        g.setSpacing(6)
        g.setContentsMargins(6, 6, 6, 6)
        self.setCentralWidget(root)

        # Bandes
        pb = Panel("Bandes")
        bl = QGridLayout(pb.body)
        bl.setSpacing(4)
        self.band_group = QButtonGroup(self)
        self.band_buttons = {}
        for i, (name, *_r) in enumerate(BANDS):
            b = self._btn(name, checkable=True)
            b.clicked.connect(lambda _c=False, n=name: self.goto_band(n))
            self.band_group.addButton(b)
            self.band_buttons[name] = b
            bl.addWidget(b, i // 4, i % 4)
        g.addWidget(pb, 0, 0)

        # RF
        pr = Panel("RF")
        rl = QVBoxLayout(pr.body)
        rl.setSpacing(4)
        rl.addWidget(self._toggle("att", "ATT"))
        self.b_pre = self._btn("IPO", self.cycle_preamp)
        self.b_pre.setToolTip("Clic : IPO → AMP 1 → AMP 2")
        rl.addWidget(self.b_pre)
        rl.addWidget(self._combo("agc", AGC_LABELS))
        rl.addWidget(self._toggle("atu", "ATU"))
        rl.addWidget(self._btn("Tune", lambda: self.ctrl.action("tune")))
        rl.addStretch()
        g.addWidget(pr, 0, 1)

        # VFO
        pv = Panel("VFO")
        vl = QVBoxLayout(pv.body)
        vl.setSpacing(5)
        self.freq = FreqDisplay()
        self.freq.tune.connect(self.tune_by)
        vl.addWidget(self.freq)
        h = QHBoxLayout()
        self.lb_mem = QLabel("VFO")
        self.lb_mem.setObjectName("info")
        self.lb_mem.setMinimumWidth(110)
        self.lb_vfob_t = QLabel("VFO B")
        self.lb_vfob_t.setObjectName("info")
        self.vfob = FreqDisplay("vfob")
        self.vfob.tune.connect(self.tune_b)
        h.addWidget(self.lb_mem)
        h.addStretch()
        h.addWidget(self.lb_vfob_t)
        h.addWidget(self.vfob)
        vl.addLayout(h)
        h = QHBoxLayout()
        h.setSpacing(4)
        for label, act in (("A/B", "swap"), ("A>B", "a_to_b"), ("B>A", "b_to_a")):
            h.addWidget(self._btn(label, lambda _c=False, a=act: self.ctrl.action(a)))
        h.addWidget(self._toggle("split", "Split"))
        h.addSpacing(10)
        self.b_vm = self._btn("V/M", lambda: self.ctrl.action("vm"), checkable=True)
        h.addWidget(self.b_vm)
        h.addWidget(self._btn("UP", lambda: self.step_mem_or_vfo(+1)))
        h.addWidget(self._btn("DN", lambda: self.step_mem_or_vfo(-1)))
        vl.addLayout(h)
        h = QHBoxLayout()
        self.ed_freq = QLineEdit()
        self.ed_freq.setPlaceholderText("Fréquence en MHz, par ex. 145.500, puis Entrée")
        self.ed_freq.returnPressed.connect(self.on_entry)
        self.controls.append(self.ed_freq)
        self.cb_step = QComboBox()
        for label, val in STEPS:
            self.cb_step.addItem(label, val)
        self.cb_step.setCurrentIndex(1)
        self.cb_step.currentIndexChanged.connect(self.on_step)
        h.addWidget(self.ed_freq, 1)
        h.addWidget(QLabel("Pas"))
        h.addWidget(self.cb_step)
        vl.addLayout(h)
        g.addWidget(pv, 0, 2)

        # Mesures
        pm = Panel("Mesures")
        ml = QVBoxLayout(pm.body)
        mh = QHBoxLayout()
        self.meter_s = AnalogMeter("S-mètre", S_SCALE, 130 / 255)
        self.meter_swr = AnalogMeter("ROS", SWR_SCALE, 89 / 255)
        mh.addWidget(self.meter_s)
        mh.addWidget(self.meter_swr)
        ml.addLayout(mh)
        ah = QHBoxLayout()
        ah.addWidget(QLabel("ALC"))
        self.bar_alc = QProgressBar()
        self.bar_alc.setRange(0, 1000)
        self.bar_alc.setTextVisible(False)
        self.bar_alc.setFixedHeight(10)
        ah.addWidget(self.bar_alc, 1)
        self.lb_meter = QLabel("")
        self.lb_meter.setObjectName("value")
        self.lb_meter.setMinimumWidth(130)
        self.lb_meter.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ah.addWidget(self.lb_meter)
        ml.addLayout(ah)
        g.addWidget(pm, 0, 3)

        # Modes
        pmo = Panel("Mode")
        mo = QGridLayout(pmo.body)
        mo.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for i, (mode, label) in enumerate(MODE_BUTTONS):
            b = self._btn(label, checkable=True)
            b.clicked.connect(lambda _c=False, m=mode: self.ctrl.set_mode(m))
            self.mode_group.addButton(b)
            self.mode_buttons[mode] = b
            mo.addWidget(b, i // 3, i % 3)
        g.addWidget(pmo, 1, 0)

        # CW
        pc = Panel("CW")
        cl = QHBoxLayout(pc.body)
        cv = QVBoxLayout()
        cv.addWidget(self._toggle("keyer", "Keyer"))
        cv.addWidget(self._toggle("bkin", "BK-IN"))
        cv.addWidget(self._btn("ZIN", lambda: self.ctrl.action("zin")))
        cv.addStretch()
        cl.addLayout(cv)
        cl.addWidget(self._vslider("wpm", "Vitesse", 4, 60, lambda v: f"{v} wpm"))
        g.addWidget(pc, 1, 1)

        # Clarifier + FM
        pcl = Panel("Clarifier et relais FM")
        ql = QGridLayout(pcl.body)
        ql.setSpacing(4)
        self.b_rxclar = self._btn("RX", checkable=True)
        self.b_rxclar.clicked.connect(lambda c: self.ctrl.action("rx_clar", c))
        self.b_txclar = self._btn("TX", checkable=True)
        self.b_txclar.clicked.connect(lambda c: self.ctrl.action("tx_clar", c))
        self.lb_clar = QLabel("+0000 Hz")
        self.lb_clar.setObjectName("vfob")
        self.lb_clar.setAlignment(Qt.AlignCenter)
        ql.addWidget(self.b_rxclar, 0, 0)
        ql.addWidget(self.lb_clar, 0, 1, 1, 3)
        ql.addWidget(self.b_txclar, 0, 4)
        for i, d in enumerate((-100, -10, 10, 100)):
            ql.addWidget(self._btn(f"{d:+d}", lambda _c=False, d=d: self.ctrl.action("clar_step", d)),
                         1, i if i < 2 else i + 1)
        ql.addWidget(self._btn("CLR", lambda: self.ctrl.action("clar_clear")), 1, 2)
        ql.addWidget(self._combo("rpt_shift", SHIFT_LABELS), 2, 0, 1, 5)
        ql.addWidget(self._combo("tone_mode", TONE_MODES), 3, 0, 1, 3)
        ql.addWidget(self._combo("tone", [f"{t:.1f} Hz" for t in CTCSS]), 3, 3, 1, 2)
        g.addWidget(pcl, 1, 2)

        # Émission
        pt = Panel("Émission")
        tl = QHBoxLayout(pt.body)
        tl.addWidget(self._vslider("pwr", "Puissance", 5, 100, lambda v: f"{v} W"))
        tl.addWidget(self._vslider("mic", "Micro", 0, 100, str))
        tv = QVBoxLayout()
        self.b_ptt = self._btn("MOX", checkable=True)
        self.b_ptt.setObjectName("ptt")
        self.b_ptt.toggled.connect(lambda on: None if self._updating else self.ctrl.set_ptt(on))
        tv.addWidget(self.b_ptt)
        tv.addWidget(self._toggle("vox", "VOX"))
        tv.addWidget(self._toggle("proc", "PROC"))
        tv.addStretch()
        tl.addLayout(tv)
        g.addWidget(pt, 1, 3)

        # Réception
        prx = Panel("Réception")
        xl = QHBoxLayout(prx.body)
        xl.addWidget(self._vslider("af", "Volume", 0, 255, lambda v: f"{round(v / 2.55)} %"))
        xl.addWidget(self._vslider("rf", "Gain HF", 0, 255, lambda v: f"{round(v / 2.55)} %"))
        xl.addWidget(self._vslider("sql", "Squelch", 0, 100, str))
        g.addWidget(prx, 2, 0)

        # Filtres
        pf = Panel("Filtres")
        fl = QGridLayout(pf.body)
        fl.setHorizontalSpacing(10)
        fl.setVerticalSpacing(4)

        def cell(r, c, left, key, lo, hi, fmt, step=1):
            sl, val = self._slider(key, lo, hi, fmt, step=step)
            val.setMinimumWidth(70)
            fl.addWidget(left, r, c)
            fl.addWidget(sl, r, c + 1)
            fl.addWidget(val, r, c + 2)

        cell(0, 0, QLabel("Largeur"), "width", 0, 21, self.width_text)
        cell(1, 0, QLabel("Shift"), "shift", -1200, 1200, lambda v: f"{v:+d} Hz", step=20)
        cell(2, 0, self._toggle("contour", "Contour"), "contour_f", 10, 3200,
             lambda v: f"{v} Hz", step=10)
        cell(0, 3, self._toggle("notch", "Notch"), "notch_f", 1, 320, lambda v: f"{v * 10} Hz")
        cell(1, 3, self._toggle("dnr", "DNR"), "dnr_lvl", 1, 15, lambda v: f"niveau {v}")
        bh = QHBoxLayout()
        for key, label in (("nar", "NAR"), ("nb", "NB"), ("dnf", "DNF"), ("apf", "APF")):
            bh.addWidget(self._toggle(key, label))
        fl.addLayout(bh, 2, 3, 1, 3)
        g.addWidget(pf, 2, 1, 1, 3)

        # Liaison et partage
        pl = Panel("Liaison et partage du CAT")
        ll = QHBoxLayout(pl.body)
        self.cb_rig = QComboBox()
        self.cb_rig.addItems(DRIVERS.keys())
        self.cb_rig.currentTextChanged.connect(self.on_rig_changed)
        self.cb_port = QComboBox()
        self.cb_port.setMinimumWidth(230)
        b_ref = QPushButton("⟳")
        b_ref.setToolTip("Actualiser la liste des ports")
        b_ref.clicked.connect(self.refresh_ports)
        self.cb_baud = QComboBox()
        self.cb_baud.addItems(["4800", "9600", "19200", "38400"])
        self.cb_stop = QComboBox()
        self.cb_stop.addItems(["1", "2"])
        self.b_conn = QPushButton("Connecter")
        self.b_conn.clicked.connect(self.toggle_connection)
        for w in (self.cb_rig, QLabel("Port"), self.cb_port, b_ref, QLabel("Vitesse"),
                  self.cb_baud, QLabel("Stop"), self.cb_stop, self.b_conn):
            ll.addWidget(w)
        ll.addSpacing(20)
        self.ck_srv = QCheckBox("Serveur rigctld")
        self.ck_srv.setToolTip("WSJT-X : Radio « Hamlib NET rigctl », serveur 127.0.0.1:4532, PTT « CAT »")
        self.ck_srv.toggled.connect(self.toggle_server)
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(4532)
        self.lb_clients = QLabel("arrêté")
        self.lb_clients.setObjectName("hint")
        ll.addWidget(self.ck_srv)
        ll.addWidget(self.sp_port)
        ll.addWidget(self.lb_clients)
        ll.addStretch()
        self.b_mems = QPushButton("Mémoires")
        self.b_mems.setCheckable(True)
        ll.addWidget(self.b_mems)
        g.addWidget(pl, 3, 0, 1, 4)

        g.setColumnStretch(2, 1)
        self.statusBar().showMessage("Choisissez le port du FT-991A puis cliquez sur Connecter")
        self.refresh_ports()

    def _build_memory_dock(self):
        dock = QDockWidget("Mémoires du poste", self)
        dock.setObjectName("memdock")
        w = QWidget()
        v = QVBoxLayout(w)
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["Canal", "Nom", "Fréquence", "Mode", "Relais", "Tonalité"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.cellDoubleClicked.connect(self.recall_memory)
        self.tbl.setToolTip("Double-clic : rappeler la mémoire sur le poste")
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        self.b_readmem = self._btn("Lire les mémoires", self.ctrl.read_memories)
        h.addWidget(self.b_readmem)
        h.addWidget(self._btn("Rappeler", lambda: self.recall_memory(self.tbl.currentRow(), 0)))
        h.addStretch()
        b = QPushButton("Exporter CSV")
        b.clicked.connect(self.export_memories)
        h.addWidget(b)
        v.addLayout(h)
        dock.setWidget(w)
        dock.setMinimumWidth(470)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.hide()
        self.mem_dock = dock
        self.b_mems.toggled.connect(dock.setVisible)
        dock.visibilityChanged.connect(self.b_mems.setChecked)

    # --- réglages ----------------------------------------------------------------
    def _load_settings(self):
        s = self.settings
        rig = s.value("rig", "Yaesu FT-991A")
        if rig in DRIVERS:
            self.cb_rig.setCurrentText(rig)
        self.on_rig_changed(self.cb_rig.currentText(), keep_saved=True)
        i = self.cb_port.findData(s.value("port", ""))
        if i >= 0:
            self.cb_port.setCurrentIndex(i)
        self.cb_baud.setCurrentText(str(s.value("baud", "38400")))
        self.cb_stop.setCurrentText(str(s.value("stop", "1")))
        self.sp_port.setValue(int(s.value("tcp_port", 4532)))
        if s.value("geometry"):
            self.restoreGeometry(s.value("geometry"))
        if s.value("server", "false") == "true":
            self.ck_srv.setChecked(True)

    def closeEvent(self, e):
        s = self.settings
        s.setValue("rig", self.cb_rig.currentText())
        s.setValue("port", self.cb_port.currentData() or "")
        s.setValue("baud", self.cb_baud.currentText())
        s.setValue("stop", self.cb_stop.currentText())
        s.setValue("tcp_port", self.sp_port.value())
        s.setValue("server", "true" if self.ck_srv.isChecked() else "false")
        s.setValue("band_mem", json.dumps(self.band_mem))
        s.setValue("geometry", self.saveGeometry())
        self.ctrl.disconnect_rig()
        if self.server:
            self.server.stop()
        super().closeEvent(e)

    # --- liaison -------------------------------------------------------------------
    def refresh_ports(self):
        cur = self.cb_port.currentData()
        self.cb_port.clear()
        enhanced = -1
        for p in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device):
            self.cb_port.addItem(f"{p.device} — {p.description}", p.device)
            if "enhanced" in p.description.lower():
                enhanced = self.cb_port.count() - 1
        i = self.cb_port.findData(cur)
        if i >= 0:
            self.cb_port.setCurrentIndex(i)
        elif enhanced >= 0:          # le CAT du FT-991A est sur le port « Enhanced »
            self.cb_port.setCurrentIndex(enhanced)

    def on_rig_changed(self, name, keep_saved=False):
        cls = DRIVERS.get(name)
        if not cls:
            return
        if not keep_saved:
            self.cb_baud.setCurrentText(str(cls.default_baud))
            self.cb_stop.setCurrentText(str(cls.default_stopbits))
        for w in (self.cb_port, self.cb_baud, self.cb_stop):
            w.setEnabled(cls is not SimDriver)

    def toggle_connection(self):
        if self.ctrl.connected:
            self.ctrl.disconnect_rig()
            return
        cls = DRIVERS[self.cb_rig.currentText()]
        port = "SIM" if cls is SimDriver else self.cb_port.currentData()
        if not port:
            QMessageBox.warning(self, "Aucun port", "Aucun port série n'est sélectionné. "
                                "Branchez le câble USB du FT-991A puis cliquez sur ⟳.")
            return
        try:
            self.ctrl.connect_rig(cls(port, int(self.cb_baud.currentText()),
                                      int(self.cb_stop.currentText())))
        except Exception as e:
            QMessageBox.critical(self, "Connexion impossible",
                                 f"Le port {port} n'a pas pu être ouvert.\n\n{e}\n\n"
                                 "Vérifiez qu'aucun autre logiciel ne l'utilise déjà.")

    def on_status(self, ok, msg):
        if not ok and self.ctrl.driver:          # liaison perdue : on libère le port
            self.ctrl.disconnect_rig()
        self.statusBar().showMessage(msg)
        self.b_conn.setText("Déconnecter" if ok else "Connecter")
        self.cb_rig.setEnabled(not ok)
        for w in (self.cb_port, self.cb_baud, self.cb_stop):
            w.setEnabled(False)
        if not ok:
            self.on_rig_changed(self.cb_rig.currentText(), keep_saved=True)
            self._updating = True
            self.b_ptt.setChecked(False)
            self._updating = False
            self.meter_s.set_value(0)
            self.meter_swr.set_value(0)
        self._set_enabled(ok)

    def _set_enabled(self, on):
        for w in self.controls:
            w.setEnabled(on)

    # --- commandes -------------------------------------------------------------------
    def on_step(self):
        self.freq.default_step = self.cb_step.currentData()

    def tune_by(self, delta):
        f = self.ctrl.snapshot().freq + delta
        self.ctrl.set_freq(max(30000, min(470000000, f)))

    def tune_b(self, delta):
        f = self.ctrl.snapshot().p.get("vfob", 0) + delta
        if f > 0:
            self.ctrl.set_param("vfob", max(30000, min(470000000, f)))

    def on_entry(self):
        txt = self.ed_freq.text().strip().replace(",", ".")
        try:
            val = float(txt)
        except ValueError:
            self.statusBar().showMessage(f"« {txt} » n'est pas une fréquence valide")
            return
        hz = val * 1e6 if val < 1000 else val * 1e3 if val < 1e6 else val
        self.ctrl.set_freq(round(hz))
        self.ed_freq.clear()

    def cycle_preamp(self):
        cur = self.ctrl.snapshot().p.get("pre", 0)
        self.ctrl.set_param("pre", (cur + 1) % 3)

    def step_mem_or_vfo(self, d):
        info = self.ctrl.snapshot().p.get("info", {})
        if info.get("vm") and self.memories:
            chans = [m["ch"] for m in self.memories]
            cur = info.get("ch", chans[0])
            nxt = [c for c in chans if (c > cur if d > 0 else c < cur)]
            if nxt:
                self.ctrl.action("mem_recall", nxt[0] if d > 0 else nxt[-1])
                return
        self.ctrl.action("up" if d > 0 else "down")

    @staticmethod
    def band_of(hz):
        for name, lo, hi, _d in BANDS:
            if lo <= hz <= hi:
                return name
        return None

    def goto_band(self, name):
        cur = self.ctrl.snapshot().freq
        b = self.band_of(cur)
        if b:
            self.band_mem[b] = cur           # dernière fréquence utilisée sur chaque bande
        default = next(d for n, _l, _h, d in BANDS if n == name)
        self.ctrl.set_freq(self.band_mem.get(name, default))

    def width_text(self, v):
        mode = self._last.mode if self._last else "USB"
        if v == 0:
            return "défaut"
        table = WIDTH_CW if mode in CW_LIKE else WIDTH_SSB if mode in ("USB", "LSB") else None
        if table and v in table:
            return f"{table[v]} Hz"
        return f"pos. {v}"

    # --- mémoires ----------------------------------------------------------------------
    def on_memories(self, mems):
        self.memories = mems
        self.tbl.setRowCount(len(mems))
        for r, m in enumerate(mems):
            shift = ["", "+", "−"][m.get("shift", 0)] if m.get("shift", 0) in (0, 1, 2) else ""
            tone = ["", "TSQ", "Tone", "DCS"][m.get("ctcss", 0)] if m.get("ctcss", 0) in range(4) else ""
            cells = [f"{m['ch']:03d}", m.get("tag", ""), self._fmt_f(m["freq"]),
                     MODE_LABELS.get(m.get("mode"), m.get("mode", "")), shift, tone]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignCenter if c != 1 else Qt.AlignLeft | Qt.AlignVCenter)
                self.tbl.setItem(r, c, it)
        self.statusBar().showMessage(f"{len(mems)} mémoires lues sur le poste")
        self.mem_dock.show()

    @staticmethod
    def _fmt_f(hz):
        mhz, rest = divmod(int(hz), 1_000_000)
        return f"{mhz},{rest // 1000:03d}.{rest % 1000:03d}"

    def recall_memory(self, row, _col):
        if 0 <= row < len(self.memories):
            self.ctrl.action("mem_recall", self.memories[row]["ch"])

    def export_memories(self):
        if not self.memories:
            QMessageBox.information(self, "Aucune mémoire",
                                    "Lisez d'abord les mémoires du poste.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les mémoires",
                                              "memoires_ft991a.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Canal", "Nom", "Fréquence (Hz)", "Mode", "Relais", "Tonalité"])
            for m in self.memories:
                w.writerow([m["ch"], m.get("tag", ""), m["freq"], m.get("mode", ""),
                            m.get("shift", ""), m.get("ctcss", "")])
        self.statusBar().showMessage(f"Mémoires exportées dans {path}")

    # --- serveur -----------------------------------------------------------------------
    def toggle_server(self, on):
        if on:
            try:
                self.server = RigctlServer(self.ctrl, self.sp_port.value())
                self.server.start()
            except OSError as e:
                self.server = None
                QMessageBox.warning(self, "Serveur indisponible",
                                    f"Le port TCP {self.sp_port.value()} est déjà utilisé.\n\n{e}")
                self.ck_srv.blockSignals(True)
                self.ck_srv.setChecked(False)
                self.ck_srv.blockSignals(False)
                return
        elif self.server:
            self.server.stop()
            self.server = None
        self.sp_port.setEnabled(not on)
        self.update_clients()

    def update_clients(self):
        if not self.server:
            self.lb_clients.setText("arrêté")
        else:
            n = self.server.clients
            self.lb_clients.setText(f"{n} logiciel connecté" if n < 2 else f"{n} logiciels connectés")

    # --- affichage de l'état -------------------------------------------------------------
    def on_state(self, st):
        if not self.ctrl.connected:
            return
        self._last = st
        self._updating = True
        try:
            self._show_state(st)
        finally:
            self._updating = False

    def _show_state(self, st):
        p, unsup = st.p, st.unsupported
        self.freq.set_freq(st.freq)
        if "vfob" in p:
            self.vfob.set_freq(p["vfob"])

        b = self.mode_buttons.get(st.mode)
        if b:
            b.setChecked(True)
        band = self.band_of(st.freq)
        if band:
            self.band_buttons[band].setChecked(True)
        elif self.band_group.checkedButton():
            self.band_group.setExclusive(False)
            self.band_group.checkedButton().setChecked(False)
            self.band_group.setExclusive(True)

        for key, btn in self.toggles.items():
            if key in p:
                btn.setChecked(bool(p[key]))
            btn.setEnabled(key not in unsup)
        for key, (s, val, fmt) in self.sliders.items():
            if key in p and not s.isSliderDown():
                s.setValue(int(p[key]))
                val.setText(fmt(int(p[key])))
            s.setEnabled(key not in unsup)
        for key, c in self.combos.items():
            if key in p:
                c.setCurrentIndex(min(int(p[key]), 4) if key == "agc" else int(p[key]))
            c.setEnabled(key not in unsup)

        if "pre" in p:
            self.b_pre.setText(PRE_LABELS[p["pre"]] if p["pre"] in (0, 1, 2) else "IPO")
            self.b_pre.setEnabled("pre" not in unsup)

        s_width = self.sliders["width"][0]
        s_width.setMaximum(17 if st.mode in CW_LIKE else 21)
        self.sliders["width"][1].setText(self.width_text(s_width.value()))

        info = p.get("info", {})
        if info:
            self.lb_mem.setText(f"Mémoire {info['ch']:03d}" if info.get("vm") else "VFO")
            self.b_vm.setChecked(bool(info.get("vm")))
            self.b_rxclar.setChecked(bool(info.get("rx_clar")))
            self.b_txclar.setChecked(bool(info.get("tx_clar")))
            self.lb_clar.setText(f"{info.get('clar', 0):+05d} Hz")

        self.b_ptt.setChecked(st.ptt)
        if st.ptt:
            self.meter_s.set_scale("Puissance émise", PO_SCALE, 1.01)
            self.meter_s.set_value(st.po)
            self.meter_swr.set_value(st.swr)
            self.bar_alc.setValue(int(st.alc * 1000))
            self.lb_meter.setText(f"ROS ≈ {st.swr_val:.1f}" if st.swr_val else "")
        else:
            self.meter_s.set_scale("S-mètre", S_SCALE, 130 / 255)
            self.meter_s.set_value(st.smeter)
            self.meter_swr.set_value(0)
            self.bar_alc.setValue(0)
            self.lb_meter.setText(st.s_text)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CAT Pilot")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
