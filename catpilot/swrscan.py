"""Analyseur de SWR : balayage d'une bande en émettant brièvement une porteuse à faible puissance,
puis tracé de la courbe du SWR (réglage d'antenne).

Sécurités : uniquement dans les limites de la bande amateur, puissance minimale, émission
coupée entre deux points, arrêt immédiat (bouton Stop ou Échap) et si le SWR dépasse le seuil.
Le poste retrouve à la fin sa fréquence, son mode et sa puissance.
"""
import math
import statistics
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


class Plot(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 280)
        self.pts = []
        self.f0 = self.f1 = 0

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#000"))
        L, R, T, B = 48, 14, 14, 34
        W, H = self.width() - L - R, self.height() - T - B
        ymax = 5.0

        def y_of(s):
            s = max(1.0, min(ymax, s))
            return T + H - (math.log(s) / math.log(ymax)) * H

        def x_of(f):
            return L + (f - self.f0) / max(1, self.f1 - self.f0) * W
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        for s, col in ((1.0, "#2fbf3a"), (1.5, "#2fbf3a"), (2.0, "#f2b705"), (3.0, "#e5463b"), (5.0, "#e5463b")):
            y = y_of(s)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.DashLine))
            p.drawLine(L, int(y), L + W, int(y))
            p.setPen(QColor(col))
            p.drawText(QRectF(0, y - 8, L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{s:g}")
        if self.f1 > self.f0:
            for k in range(6):
                fr = self.f0 + (self.f1 - self.f0) * k / 5
                x = x_of(fr)
                p.setPen(QPen(QColor(255, 255, 255, 30), 1, Qt.DotLine))
                p.drawLine(int(x), T, int(x), T + H)
                p.setPen(QColor("#bbb"))
                p.drawText(QRectF(x - 40, T + H + 4, 80, 14), Qt.AlignCenter, f"{fr / 1e6:.3f}")
        p.setPen(QColor("#888"))
        p.drawText(QRectF(L, self.height() - 16, W, 14), Qt.AlignCenter, "MHz")
        if len(self.pts) >= 1:
            path = QPainterPath()
            for i, (fr, s) in enumerate(self.pts):
                pt = QPointF(x_of(fr), y_of(s))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(QColor("#4fc3f7"), 2))
            p.drawPath(path)
            p.setBrush(QColor("#4fc3f7"))
            for fr, s in self.pts:
                p.drawEllipse(QPointF(x_of(fr), y_of(s)), 2.5, 2.5)
            fb, sb = min(self.pts, key=lambda t: t[1])
            p.setPen(QPen(QColor("#8cff3a"), 1))
            p.setBrush(QColor("#8cff3a"))
            p.drawEllipse(QPointF(x_of(fb), y_of(sb)), 4.5, 4.5)
            p.drawText(QRectF(x_of(fb) - 70, y_of(sb) - 22, 140, 14), Qt.AlignCenter,
                       f"{sb:.2f} à {fb / 1e6:.3f}")


class Sweeper(QObject):
    point = Signal(int, float)          # fréquence (Hz), SWR
    done = Signal(str)

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self, freqs, power, abort_swr):
        self._stop.clear()
        threading.Thread(target=self._run, args=(freqs, power, abort_swr), daemon=True).start()

    def _run(self, freqs, power, abort_swr):
        c = self.ctrl
        st0 = c.snapshot()
        f0, m0, p0 = st0.freq, st0.mode, st0.p.get("pwr")
        msg = "Balayage terminé"
        try:
            carrier = next((m for m in ("FM", "AM") if m in c.driver.modes), None)
            if not carrier:
                msg = "ce poste ne sait pas émettre de porteuse (FM ou AM)"
                return
            c.set_mode(carrier)
            if p0 is not None:
                c.set_param("pwr", power)
            time.sleep(0.6)
            for f in freqs:
                if self._stop.is_set():
                    msg = "Balayage arrêté"
                    break
                c.set_freq(int(f))
                time.sleep(0.35)
                c.set_ptt(True)
                time.sleep(0.7)                    # laisser la mesure du poste s'établir
                vals = []
                end = time.time() + 0.5
                while time.time() < end and not self._stop.is_set():
                    v = c.snapshot().swr_val
                    if v:
                        vals.append(v)
                    time.sleep(0.05)
                c.set_ptt(False)
                if vals:
                    s = statistics.median(vals)
                    self.point.emit(int(f), float(s))
                    if s > abort_swr:
                        msg = f"Balayage arrêté : SWR {s:.1f} au-dessus du seuil ({abort_swr:g})"
                        break
                time.sleep(0.25)
        except Exception as e:
            msg = f"Erreur : {e}"
        finally:
            c.set_ptt(False)
            time.sleep(0.3)
            try:
                c.set_freq(f0)
                c.set_mode(m0)
                if p0 is not None:
                    c.set_param("pwr", p0)
            except Exception:
                pass
            self.done.emit(msg)


class SwrDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Analyseur de SWR")
        self.resize(720, 500)
        from .gui import BANDS
        v = QVBoxLayout(self)
        t = QLabel("Le poste émet une porteuse à faible puissance, quelques dixièmes de seconde par point, sur toute "
                   "la bande choisie, puis trace la courbe du SWR. Vérifiez que la bande est libre et que "
                   "l'antenne est branchée. Stop ou Échap arrêtent immédiatement l'émission.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        v.addWidget(t)
        h = QHBoxLayout()
        h.addWidget(QLabel("Bande"))
        self.cb_band = QComboBox()
        drv = win.ctrl.driver
        lo, hi = getattr(drv, "min_freq", 0), getattr(drv, "max_freq", 470_000_000)
        for name, a, b, *_r in BANDS:
            if lo <= a and b <= hi:
                self.cb_band.addItem(name, (a, b))
        cur = win.band_of(win._last.freq) if win._last else None
        if cur:
            self.cb_band.setCurrentText(cur)
        h.addWidget(self.cb_band)
        h.addWidget(QLabel("Points"))
        self.sp_n = QSpinBox()
        self.sp_n.setRange(5, 60)
        self.sp_n.setValue(21)
        h.addWidget(self.sp_n)
        h.addWidget(QLabel("Puissance"))
        self.sp_p = QSpinBox()
        self.sp_p.setRange(1, 20)
        self.sp_p.setSuffix(" W")
        self.sp_p.setValue(max(5, 1 if getattr(drv, "max_power", 100) < 20 else 5))
        h.addWidget(self.sp_p)
        h.addWidget(QLabel("Arrêt si SWR >"))
        self.sp_abort = QDoubleSpinBox()
        self.sp_abort.setRange(1.5, 10)
        self.sp_abort.setSingleStep(0.5)
        self.sp_abort.setValue(3.0)
        h.addWidget(self.sp_abort)
        h.addStretch()
        v.addLayout(h)
        self.plot = Plot()
        v.addWidget(self.plot, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        h = QHBoxLayout()
        self.ck = QCheckBox("La bande est libre et l'antenne (ou une charge) est branchée")
        h.addWidget(self.ck)
        h.addStretch()
        self.b_go = QPushButton("Lancer le balayage")
        self.b_go.clicked.connect(self.start)
        h.addWidget(self.b_go)
        b = QPushButton("Stop")
        b.clicked.connect(self.stop)
        h.addWidget(b)
        b = QPushButton("Enregistrer l'image…")
        b.clicked.connect(self.save_png)
        h.addWidget(b)
        v.addLayout(h)
        self.sw = Sweeper(win.ctrl)
        self.sw.point.connect(self.on_point)
        self.sw.done.connect(self.on_done)
        self.running = False

    def start(self):
        if not self.win.ctrl.connected:
            self.lb.setText("Pas de poste connecté")
            return
        if not self.ck.isChecked():
            self.lb.setText("Cochez d'abord la case de vérification (bande libre, antenne branchée)")
            return
        a, b = self.cb_band.currentData()
        n = self.sp_n.value()
        margin = (b - a) * 0.01
        freqs = [a + margin + (b - a - 2 * margin) * i / (n - 1) for i in range(n)]
        freqs = [int(round(f / 1000) * 1000) for f in freqs]
        if QMessageBox.question(self, "Analyseur de SWR",
                                f"Émettre {n} fois une porteuse de {self.sp_p.value()} W entre "
                                f"{freqs[0] / 1e6:.3f} et {freqs[-1] / 1e6:.3f} MHz (environ {n * 1.6:.0f} s) ?") \
                != QMessageBox.Yes:
            return
        self.plot.pts = []
        self.plot.f0, self.plot.f1 = freqs[0], freqs[-1]
        self.plot.update()
        self.running = True
        self.b_go.setEnabled(False)
        self.lb.setText("Balayage en cours… (Stop ou Échap pour arrêter)")
        self.sw.run(freqs, self.sp_p.value(), self.sp_abort.value())

    def stop(self):
        self.sw.stop()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.running:
            self.sw.stop()
            return
        super().keyPressEvent(e)

    def on_point(self, f, s):
        self.plot.pts.append((f, s))
        self.plot.update()

    def on_done(self, msg):
        self.running = False
        self.b_go.setEnabled(True)
        pts = self.plot.pts
        if pts:
            fb, sb = min(pts, key=lambda t: t[1])
            ok = [f for f, s in pts if s <= 2.0]
            bw = f" · SWR ≤ 2 de {min(ok) / 1e6:.3f} à {max(ok) / 1e6:.3f} MHz" if ok else " · SWR > 2 partout"
            msg += f" — meilleur SWR {sb:.2f} à {fb / 1e6:.3f} MHz{bw}"
        self.lb.setText(msg)

    def save_png(self):
        import os
        from .logbook import data_dir
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer la courbe", os.path.join(
            data_dir(), f"SWR_{self.cb_band.currentText()}.png"), "Image PNG (*.png)")
        if path:
            self.plot.grab().save(path)

    def done(self, r):
        self.sw.stop()
        super().done(r)
