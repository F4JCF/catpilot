"""Confort d'utilisation : QSY récents, annonces vocales, barre d'état, dispositions des panneaux,
grand panoramique, plein écran, afficheur de fréquence agrandi.
"""
import base64
import datetime
import json
import os
import subprocess
import time

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDockWidget, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)


# --- annonces vocales -------------------------------------------------------------------------
class Speaker:
    """Synthèse vocale de Windows (module Qt, sinon PowerShell / System.Speech)."""

    def __init__(self):
        self.tts = None
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            engines = QTextToSpeech.availableEngines()
            pref = next((e for e in ("winrt", "sapi") if e in engines), None)
            self.tts = QTextToSpeech(pref) if pref else (QTextToSpeech() if engines else None)
            if self.tts:
                from PySide6.QtCore import QLocale
                for loc in self.tts.availableLocales():
                    if loc.language() == QLocale.French:
                        self.tts.setLocale(loc)
                        break
        except Exception:
            self.tts = None

    def say(self, text):
        if not text:
            return
        if self.tts:
            try:
                self.tts.say(text)
                return
            except Exception:
                pass
        if os.name == "nt":
            safe = text.replace("'", " ").replace('"', " ")
            cmd = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                   f"$s.Speak('{safe}')")
            try:
                subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd],
                                 creationflags=0x08000000)
            except Exception:
                pass


def spoken_freq(hz):
    """14 074 000 -> « 14 mégahertz 074 » (lisible par la synthèse vocale)."""
    mhz, rest = divmod(int(hz), 1_000_000)
    khz = rest // 1000
    hund = (rest % 1000) // 100
    s = f"{mhz} mégahertz {khz:03d}"
    if hund:
        s += f" virgule {hund}"
    return s


MODE_SPOKEN = {"USB": "B L U supérieure", "LSB": "B L U inférieure", "CW": "C W", "CWR": "C W inversé",
               "AM": "A M", "FM": "F M", "PKTUSB": "data U", "PKTLSB": "data L", "PKTFM": "data F M",
               "RTTY": "R T T Y", "RTTYR": "R T T Y inversé", "C4FM": "C 4 F M"}


# --- grand panoramique ------------------------------------------------------------------------
class BigWaterfallDock(QDockWidget):
    """Seconde chute d'eau, grande et détachable (même audio, mêmes repères, clic = accord)."""

    def __init__(self, win):
        super().__init__("Panoramique", win)
        self.win = win
        self.setObjectName("bigwf")
        from .waterfall import Waterfall
        self.wf = Waterfall()
        self.wf.ROWS = 300
        import numpy as np
        self.wf.img = np.full((self.wf.ROWS, self.wf.COLS), 0xFF000000, np.uint32)
        self.wf.message = "Lancez la chute d'eau (panneau Mesures)"
        self.wf.setMinimumHeight(260)
        self.wf.clicked.connect(lambda hz: self._click(hz))
        self.wf.hover.connect(win.on_wf_hover)
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self.wf, 1)
        h = QHBoxLayout()
        for label, attr, lo, hi, val in (("Contraste", "contrast", 15, 80, 45), ("Seuil", "offset", -15, 30, 5)):
            h.addWidget(QLabel(label))
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(val)
            sl.setMaximumWidth(140)
            sl.valueChanged.connect(lambda x, a=attr: setattr(self.wf, a, float(x)))
            h.addWidget(sl)
        h.addStretch()
        t = QLabel("Clic : accorder le poste · ce panneau peut être détaché et agrandi (double-clic sur son titre)")
        t.setObjectName("hint")
        h.addWidget(t)
        v.addLayout(h)
        self.setWidget(w)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._sync)
        self.timer.start(200)
        self.visibilityChanged.connect(self._vis)

    def _click(self, hz):
        self.win.wf.last_mods = self.wf.last_mods
        self.win.on_wf_click(hz)

    def _feed(self, x, sr):
        self.wf.sr = sr
        self.wf.chunks.append(x)

    def _vis(self, on):
        lst = self.win.wf.listeners
        if on and self._feed not in lst:
            lst.append(self._feed)
        elif not on and self._feed in lst:
            lst.remove(self._feed)

    def _sync(self):
        src = self.win.wf
        self.wf.marker, self.wf.cw_marker, self.wf.markers = src.marker, src.cw_marker, src.markers
        self.wf.message = "" if src.running else "Lancez la chute d'eau (panneau Mesures)"
        if not src.running:
            self.wf.update()


# --- dispositions des panneaux ----------------------------------------------------------------
PRESETS = {
    "Trafic CW": ["cw", "logdock", "spots"],
    "FT8 / numérique": ["digi", "logdock", "mapdock"],
    "ADRASEC": ["mc", "logdock", "mem"],
    "Chasse POTA / DX": ["spots", "mapdock", "logdock"],
    "Tout fermer": [],
}


class Layouts:
    def __init__(self, win, menu):
        self.win, self.menu = win, menu
        self.rebuild()

    def saved(self):
        try:
            return json.loads(self.win.settings.value("layouts", "{}") or "{}")
        except ValueError:
            return {}

    def rebuild(self):
        m = self.menu
        m.clear()
        for name in PRESETS:
            a = QAction(name, self.win)
            a.triggered.connect(lambda _c=False, n=name: self.apply_preset(n))
            m.addAction(a)
        sv = self.saved()
        if sv:
            m.addSeparator()
            for name in sorted(sv):
                a = QAction(f"{name}", self.win)
                a.triggered.connect(lambda _c=False, n=name: self.restore(n))
                m.addAction(a)
        m.addSeparator()
        a = QAction("Enregistrer la disposition actuelle…", self.win)
        a.triggered.connect(self.save)
        m.addAction(a)
        if sv:
            d = m.addMenu("Supprimer une disposition")
            for name in sorted(sv):
                a = QAction(name, self.win)
                a.triggered.connect(lambda _c=False, n=name: self.delete(n))
                d.addAction(a)

    def docks(self):
        return {n: getattr(self.win, n) for n in ("mem", "cw", "txa", "dvk", "spots", "logdock", "wsjtx", "rotor",
                                                   "sat", "sdr", "remote", "mapdock", "mc", "digi", "bigwf")
                if getattr(self.win, n, None) is not None}

    def apply_preset(self, name):
        docks = self.docks()
        want = PRESETS[name]
        for n, d in docks.items():
            if n not in want:
                d.hide()
        for n in want:
            if n in docks:
                docks[n].show()
        if want and want[0] in docks:
            docks[want[0]].raise_()
        self.win.statusBar().showMessage(f"Disposition « {name} »", 4000)

    def save(self):
        name, ok = QInputDialog.getText(self.win, "Disposition", "Nom de la disposition :")
        if not ok or not name.strip():
            return
        sv = self.saved()
        sv[name.strip()] = base64.b64encode(bytes(self.win.saveState())).decode()
        self.win.settings.setValue("layouts", json.dumps(sv))
        self.rebuild()

    def restore(self, name):
        data = self.saved().get(name)
        if data:
            self.win.restoreState(QByteArray(base64.b64decode(data)))

    def delete(self, name):
        sv = self.saved()
        sv.pop(name, None)
        self.win.settings.setValue("layouts", json.dumps(sv))
        self.rebuild()


# --- barre d'état ------------------------------------------------------------------------------
class StatusInfo:
    """Bande, mode, puissance, SWR max de la dernière émission, QSO du jour (à droite de la barre d'état)."""

    def __init__(self, win):
        self.win = win
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        win.statusBar().addPermanentWidget(self.lb)
        self.swr_max = 0.0
        self.last_tx_swr = None
        self._was_tx = False
        self._qso_today = None
        win.log.changed.connect(lambda: setattr(self, "_qso_today", None))
        t = QTimer(win)
        t.timeout.connect(self.refresh)
        t.start(1000)

    def on_state(self, st):
        if st.ptt:
            if not self._was_tx:
                self.swr_max = 0.0
            if st.swr_val:
                self.swr_max = max(self.swr_max, st.swr_val)
        elif self._was_tx:
            self.last_tx_swr = self.swr_max or None
        self._was_tx = st.ptt

    def refresh(self):
        w = self.win
        parts = []
        me = (w.settings.value("mycall", "") or "").upper()
        if me:
            parts.append(me)
        st = w._last
        if st and w.ctrl.connected:
            from .gui import MODE_LABELS
            band = w.band_of(st.freq)
            if band:
                parts.append(band)
            parts.append(MODE_LABELS.get(st.mode, st.mode))
            ant = getattr(w, "antennas", None)
            if ant and ant.label():
                parts.append(f"Ant. {ant.label()}")
            if "pwr" in st.p:
                parts.append(f"{st.p['pwr']} W")
            if self.last_tx_swr:
                parts.append(f"SWR max {self.last_tx_swr:.1f}")
        if self._qso_today is None:
            d = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
            with w.log.lock:
                self._qso_today = w.log.db.execute("SELECT COUNT(*) FROM qso WHERE qso_date = ?", (d,)).fetchone()[0]
        parts.append(f"{self._qso_today} QSO aujourd'hui")
        self.lb.setText("  ·  ".join(parts) + "  ")


# --- QSY récents ------------------------------------------------------------------------------
class QsyHistory:
    """Retient les 10 dernières fréquences où le poste est resté au moins 4 secondes."""

    def __init__(self, win, button):
        self.win, self.button = win, button
        try:
            self.items = json.loads(win.settings.value("qsy_history", "[]") or "[]")
        except ValueError:
            self.items = []
        self.cand = None
        self.menu = QMenu(button)
        button.setMenu(self.menu)
        self.menu.aboutToShow.connect(self.fill)

    def on_state(self, st):
        if st.ptt or not st.freq:
            return
        now = time.monotonic()
        key = (int(st.freq), st.mode)
        if self.cand is None or abs(self.cand[0][0] - key[0]) > 500 or self.cand[0][1] != key[1]:
            self.cand = (key, now)
            return
        if now - self.cand[1] >= 4.0:
            f, m = self.cand[0]
            if not self.items or abs(self.items[0][0] - f) > 500 or self.items[0][1] != m:
                self.items = [x for x in self.items if abs(x[0] - f) > 500 or x[1] != m]
                self.items.insert(0, [f, m, datetime.datetime.now().strftime("%H:%M")])
                del self.items[10:]
            self.cand = (self.cand[0], float("inf"))

    def fill(self):
        from .gui import MODE_LABELS
        self.menu.clear()
        if not self.items:
            a = self.menu.addAction("(aucune fréquence récente)")
            a.setEnabled(False)
            return
        for f, m, t in self.items:
            mhz, rest = divmod(f, 1_000_000)
            a = self.menu.addAction(f"{mhz}.{rest // 1000:03d}.{rest % 1000:03d}   {MODE_LABELS.get(m, m)}   ({t})")
            a.triggered.connect(lambda _c=False, ff=f, mm=m: self.go(ff, mm))
        self.menu.addSeparator()
        a = self.menu.addAction("Effacer la liste")
        a.triggered.connect(lambda: setattr(self, "items", []))

    def go(self, f, m):
        ctrl = self.win.ctrl
        if not ctrl.connected:
            return
        ctrl.set_freq(int(f))
        if ctrl.driver and m in ctrl.driver.modes:
            ctrl.set_mode(m)

    def save(self, s):
        s.setValue("qsy_history", json.dumps(self.items))


# --- annonce de la fréquence -------------------------------------------------------------------
class FreqAnnouncer:
    """Annonce la fréquence et le mode 1,5 s après la fin d'un réglage."""

    def __init__(self, win, speaker):
        self.win, self.sp = win, speaker
        self.enabled = False
        self.last = None
        self.said = None
        self.t = QTimer(win)
        self.t.setSingleShot(True)
        self.t.timeout.connect(self._say)

    def on_state(self, st):
        if not self.enabled or st.ptt:
            return
        key = (int(st.freq) // 100, st.mode)
        if key != self.last:
            self.last = key
            self.t.start(1500)

    def _say(self):
        if self.last and self.last != self.said:
            self.said = self.last
            self.sp.say(f"{spoken_freq(self.last[0] * 100)}, {MODE_SPOKEN.get(self.last[1], self.last[1])}")


# --- panneaux en grand ---------------------------------------------------------------------------
class FocusHeader(QWidget):
    """Bandeau réduit de la face avant : fréquence, plan de bande, S-mètre, SWR et ALC."""

    def __init__(self, win):
        super().__init__()
        from PySide6.QtWidgets import QFrame, QProgressBar
        from .bandplan import BandPlanBar
        from .gui import BANDS, AnalogMeter, FreqDisplay, S_SCALE, SWR_SCALE
        self.win = win
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 6, 6, 0)
        left = QFrame()
        left.setObjectName("panel")
        lv = QVBoxLayout(left)
        self.freq = FreqDisplay()
        self.freq.tune.connect(win.tune_by)
        lv.addWidget(self.freq)
        self.bp = BandPlanBar(BANDS)
        lv.addWidget(self.bp)
        lv.addStretch()
        right = QFrame()
        right.setObjectName("panel")
        rv = QVBoxLayout(right)
        mh = QHBoxLayout()
        self.ms = AnalogMeter("S-mètre", S_SCALE, 130 / 255)
        self.mw = AnalogMeter("SWR", SWR_SCALE, 89 / 255)
        mh.addWidget(self.ms)
        mh.addWidget(self.mw)
        rv.addLayout(mh)
        ah = QHBoxLayout()
        ah.addWidget(QLabel("ALC"))
        self.alc = QProgressBar()
        self.alc.setRange(0, 1000)
        self.alc.setTextVisible(False)
        self.alc.setFixedHeight(10)
        ah.addWidget(self.alc, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        self.lb.setMinimumWidth(110)
        self.lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ah.addWidget(self.lb)
        rv.addLayout(ah)
        h.addWidget(left, 1)
        h.addWidget(right, 1)
        self.t = QTimer(self)
        self.t.timeout.connect(self.sync)
        self.t.start(40)

    def sync(self):
        if not self.isVisible():
            return
        w = self.win
        if self.freq.text() != w.freq.text():
            self.freq.setText(w.freq.text())
        if self.freq.styleSheet() != w.freq.styleSheet():
            self.freq.setStyleSheet(w.freq.styleSheet())
        for dst, src in ((self.ms, w.meter_s), (self.mw, w.meter_swr)):
            if (dst.title, dst.scale, dst.red_from) != (src.title, src.scale, src.red_from):
                dst.set_scale(src.title, src.scale, src.red_from)
            dst.target = src.target
        self.alc.setValue(w.bar_alc.value())
        self.lb.setText(w.lb_meter.text())
        self.bp.dim = w.bandplan.dim
        st = w._last
        if st and w.ctrl.connected:
            self.bp.set_freq(st.freq, st.ptt)


class FocusMode:
    """Un panneau ouvert prend toute la fenêtre ; la face avant se réduit au bandeau ci-dessus."""

    def __init__(self, win, docks, stack, header):
        self.win, self.docks, self.stack, self.header = win, docks, stack, header
        self.on = False
        self.enabled = win.settings.value("focus_panels", "true") in (True, "true")
        self.last = None
        self.current = None
        for d in docks:
            d.visibilityChanged.connect(lambda vis, dd=d: self._changed(dd, vis))
            d.topLevelChanged.connect(lambda _f: QTimer.singleShot(0, self.update))

    def _open(self, d):
        return d.toggleViewAction().isChecked() and not d.isFloating()

    def _changed(self, d, vis):
        if vis and self.enabled and not d.isFloating() and d is not self.current:
            # un seul panneau à la fois : celui qu'on ouvre remplace le précédent
            self.current = d
            for o in self.docks:
                if o is not d and self._open(o):
                    o.close()
        QTimer.singleShot(0, self.update)

    def set_enabled(self, on):
        self.enabled = on
        self.win.settings.setValue("focus_panels", "true" if on else "false")
        self.update()

    def update(self):
        w = self.win
        opened = [d for d in self.docks if self._open(d)]
        want = self.enabled and bool(opened)
        if want:
            for d in opened:
                if w.dockWidgetArea(d) != Qt.BottomDockWidgetArea:
                    w.addDockWidget(Qt.BottomDockWidgetArea, d)
                    d.show()
        if not opened:
            self.current = None
        if want == self.on:
            return
        self.on = want
        if want:
            self.stack.setCurrentIndex(1)
            self.stack.setMaximumHeight(self.header.sizeHint().height() + 6)
            self.header.sync()
        else:
            self.stack.setCurrentIndex(0)
            self.stack.setMaximumHeight(16777215)
            for d in self.docks:              # prochaine ouverture hors de ce mode : à droite, comme avant
                if not self._open(d) and w.dockWidgetArea(d) == Qt.BottomDockWidgetArea:
                    w.addDockWidget(Qt.RightDockWidgetArea, d)
                    d.hide()
