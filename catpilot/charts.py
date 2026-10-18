"""Petits histogrammes dessinés avec QPainter (statistiques du carnet).

Une seule teinte par graphique (une seule série), barres fines aux extrémités arrondies,
quadrillage discret, valeur au survol, étiquettes de valeur seulement s'il y a peu de barres.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

BAR = QColor("#4fc3f7")
BAR_HOVER = QColor("#9be7ff")
GRID = QColor(255, 255, 255, 28)
INK = QColor("#d0d0d0")
MUTED = QColor("#8a8a8a")


def nice_max(v):
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


class BarChart(QWidget):
    def __init__(self, title, unit="QSO"):
        super().__init__()
        self.title, self.unit = title, unit
        self.data = []                 # [(étiquette, valeur, infobulle)]
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumSize(360, 220)

    def set_data(self, data):
        self.data = [(d[0], d[1], d[2] if len(d) > 2 else "") for d in data]
        self.update()

    def _geom(self):
        L, R, T, B = 40, 10, 30, 34
        return QRectF(L, T, max(10, self.width() - L - R), max(10, self.height() - T - B))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(INK)
        total = sum(v for _l, v, _t in self.data)
        p.drawText(QRectF(8, 4, self.width() - 16, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{self.title}  ·  {total} {self.unit}")
        g = self._geom()
        f.setBold(False)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        if not self.data:
            p.setPen(MUTED)
            p.drawText(g, Qt.AlignCenter, "Pas encore de données")
            return
        top = max(4, nice_max(max(v for _l, v, _t in self.data)))
        for k in range(5):
            y = g.bottom() - g.height() * k / 4
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(g.left(), y), QPointF(g.right(), y))
            p.setPen(MUTED)
            val = top * k / 4
            p.drawText(QRectF(0, y - 8, g.left() - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{val:g}" if val != int(val) else f"{int(val)}")
        n = len(self.data)
        slot = g.width() / n
        bw = max(2.0, min(28.0, slot * 0.62))
        show_vals = n <= 14
        every = max(1, math.ceil(n / max(1, int(g.width() / 46))))     # étiquettes d'axe sans chevauchement
        for i, (lab, v, _tip) in enumerate(self.data):
            x = g.left() + slot * i + (slot - bw) / 2
            h = g.height() * v / top if top else 0
            if h > 0:
                r = min(4.0, bw / 2, h)
                path = QPainterPath()
                rect = QRectF(x, g.bottom() - h, bw, h)
                path.moveTo(rect.left(), rect.bottom())
                path.lineTo(rect.left(), rect.top() + r)
                path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
                path.lineTo(rect.right() - r, rect.top())
                path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
                path.lineTo(rect.right(), rect.bottom())
                path.closeSubpath()
                p.fillPath(path, BAR_HOVER if i == self.hover else BAR)
                if show_vals and v:
                    p.setPen(INK)
                    p.drawText(QRectF(x - 20, g.bottom() - h - 16, bw + 40, 14), Qt.AlignCenter, str(v))
            if i % every == 0:
                p.setPen(MUTED)
                p.drawText(QRectF(g.left() + slot * i - 20, g.bottom() + 4, slot + 40, 14), Qt.AlignCenter, lab)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawLine(QPointF(g.left(), g.bottom()), QPointF(g.right(), g.bottom()))

    def mouseMoveEvent(self, e):
        g = self._geom()
        if not self.data or not g.contains(e.position()) and not (g.left() <= e.position().x() <= g.right()):
            self._leave()
            return
        i = int((e.position().x() - g.left()) / (g.width() / len(self.data)))
        if 0 <= i < len(self.data):
            if i != self.hover:
                self.hover = i
                self.update()
            lab, v, tip = self.data[i]
            QToolTip.showText(e.globalPosition().toPoint(), f"{tip or lab} : {v} {self.unit}", self)
        else:
            self._leave()

    def _leave(self):
        if self.hover != -1:
            self.hover = -1
            self.update()
        QToolTip.hideText()

    def leaveEvent(self, _e):
        self._leave()
