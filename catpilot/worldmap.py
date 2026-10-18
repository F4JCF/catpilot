"""Carte du monde : ligne grise (jour / nuit), station, spots, stations qui m'entendent, QSO.

Projection équirectangulaire. Molette : zoom, glisser : déplacer, double-clic : vue d'ensemble.
Fond de carte : Natural Earth (domaine public).
"""
import datetime
import json
import math
import os
import sys

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

_MAP = None


def _map_data():
    global _MAP
    if _MAP is None:
        base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
        try:
            with open(os.path.join(base, "assets", "worldmap.json"), encoding="utf-8") as f:
                _MAP = json.load(f)
        except OSError:
            _MAP = {"land": [], "borders": []}
    return _MAP


# --- soleil -------------------------------------------------------------------------------
def subsolar(t=None):
    """Point subsolaire (lat, lon) en degrés à l'instant t (UTC)."""
    t = t or datetime.datetime.now(datetime.timezone.utc)
    jd = t.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    lon = math.degrees(ra) - gmst * 15
    lon = (lon + 180) % 360 - 180
    return math.degrees(dec), lon


def sun_altitude(lat, lon, t=None):
    """Hauteur du soleil (degrés) ; lat/lon peuvent être des tableaux numpy."""
    slat, slon = subsolar(t)
    la, lo = np.radians(lat), np.radians(lon)
    sla, slo = math.radians(slat), math.radians(slon)
    c = np.sin(la) * math.sin(sla) + np.cos(la) * math.cos(sla) * np.cos(lo - slo)
    return np.degrees(np.arcsin(np.clip(c, -1, 1)))


def sun_times(lat, lon, day=None):
    """Lever et coucher du soleil (UTC, datetime) pour une position, ou (None, None)."""
    day = day or datetime.datetime.now(datetime.timezone.utc).date()
    t0 = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    mins = np.arange(0, 24 * 60, 2)
    alts = np.array([float(sun_altitude(lat, lon, t0 + datetime.timedelta(minutes=int(m)))) for m in mins])
    up = alts > -0.833
    rise = set_ = None
    for i in range(1, len(mins)):
        if up[i] and not up[i - 1] and rise is None:
            rise = t0 + datetime.timedelta(minutes=int(mins[i]))
        if up[i - 1] and not up[i] and set_ is None:
            set_ = t0 + datetime.timedelta(minutes=int(mins[i]))
    return rise, set_


def great_circle(lat1, lon1, lat2, lon2, n=48):
    """Points (lat, lon) du grand cercle entre deux positions."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 +
                                math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2))
    if d < 1e-9:
        return [(lat1, lon1)]
    out = []
    for i in range(n + 1):
        f = i / n
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out


class WorldMap(QWidget):
    """Carte. Les couches sont des listes de points :
    {"lat", "lon", "label", "tip", "color", "line" (tracer depuis la station)}."""
    clicked = Signal(object)              # point cliqué (dict) ou None

    LAND = QColor("#2f3b2f")
    SEA = QColor("#16212c")

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 200)
        self.setMouseTracking(True)
        self.view = [-180.0, -90.0, 360.0, 180.0]      # lon0, lat0, largeur, hauteur (degrés)
        self.station = None
        self.layers = {}
        self.greyline = True
        self._night = None
        self._night_t = None
        self._drag = None
        self._paths = None
        self._paths_key = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60_000)

    # --- données ----------------------------------------------------------------------
    def set_layer(self, name, points):
        self.layers[name] = list(points)
        self.update()

    def set_station(self, pos):
        self.station = pos
        self.update()

    def show_world(self):
        self.view = [-180.0, -90.0, 360.0, 180.0]
        self.update()

    def show_region(self, lat, lon, span=60.0):
        w = span * 1.6
        self.view = [lon - w / 2, lat - span / 2, w, span]
        self._clamp()
        self.update()

    def _tick(self):
        self._night = None
        self.update()

    # --- projection -------------------------------------------------------------------
    def _fit(self):
        """Ajuste la vue aux proportions de la fenêtre (degrés par pixel identiques en x et y)."""
        lon0, lat0, w, h = self.view
        W, H = max(1, self.width()), max(1, self.height())
        cx, cy = lon0 + w / 2, lat0 + h / 2
        scale = max(w / W, h / H)
        w, h = W * scale, H * scale
        return cx - w / 2, cy - h / 2, w, h

    def to_xy(self, lat, lon):
        lon0, lat0, w, h = self._fit()
        return ((lon - lon0) / w * self.width(), (lat0 + h - lat) / h * self.height())

    def to_geo(self, x, y):
        lon0, lat0, w, h = self._fit()
        return lat0 + h - y / self.height() * h, lon0 + x / self.width() * w

    def _clamp(self):
        lon0, lat0, w, h = self.view
        w, h = min(w, 360.0), min(h, 180.0)
        lat0 = min(max(lat0, -90.0), 90.0 - h)
        lon0 = min(max(lon0, -180.0 - w * 0.5), 180.0 - w * 0.5)
        self.view = [lon0, lat0, w, h]

    # --- souris -----------------------------------------------------------------------
    def wheelEvent(self, e):
        f = 0.8 if e.angleDelta().y() > 0 else 1.25
        lat, lon = self.to_geo(e.position().x(), e.position().y())
        lon0, lat0, w, h = self.view
        w2, h2 = max(8.0, min(360.0, w * f)), max(5.0, min(180.0, h * f))
        lon0 = lon - (lon - lon0) * w2 / w
        lat0 = lat - (lat - lat0) * h2 / h
        self.view = [lon0, lat0, w2, h2]
        self._clamp()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position(), list(self.view), False)

    def mouseMoveEvent(self, e):
        if self._drag:
            p0, v0, _moved = self._drag
            _l0, _la0, w, h = self._fit()
            dx = (e.position().x() - p0.x()) / self.width() * w
            dy = (e.position().y() - p0.y()) / self.height() * h
            if abs(e.position().x() - p0.x()) + abs(e.position().y() - p0.y()) > 4:
                self._drag = (p0, v0, True)
                self.view = [v0[0] - dx, v0[1] + dy, v0[2], v0[3]]
                self._clamp()
                self.update()
            return
        pt = self._hit(e.position())
        if pt:
            QToolTip.showText(e.globalPosition().toPoint(), pt.get("tip") or pt.get("label", ""), self)
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, e):
        if self._drag and not self._drag[2]:
            self.clicked.emit(self._hit(e.position()))
        self._drag = None

    def mouseDoubleClickEvent(self, _e):
        self.show_world()

    def _hit(self, pos):
        best, bd = None, 9.0
        for pts in self.layers.values():
            for p in pts:
                x, y = self.to_xy(p["lat"], p["lon"])
                d = math.hypot(x - pos.x(), y - pos.y())
                if d < bd:
                    best, bd = p, d
        return best

    # --- dessin -----------------------------------------------------------------------
    def _night_image(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        if self._night is not None and self._night_t and (now - self._night_t).total_seconds() < 60:
            return self._night
        lat = np.linspace(90, -90, 181)[:, None]
        lon = np.linspace(-180, 180, 361)[None, :]
        alt = sun_altitude(lat, lon, now)
        # nuit : jusqu'à 60 % d'ombre ; crépuscule (0 à -12°) en dégradé = la ligne grise
        a = np.clip(-alt / 12.0, 0, 1) * 150
        img = np.zeros((181, 361), np.uint32)
        img[:] = (a.astype(np.uint32) << 24) | 0x000814
        self._night_buf = img
        q = QImage(img.data, 361, 181, 361 * 4, QImage.Format_ARGB32)
        self._night, self._night_t = q.copy(), now
        return self._night

    def _land_paths(self):
        key = (tuple(round(v, 3) for v in self._fit()), self.width(), self.height())
        if self._paths_key == key:
            return self._paths
        data = _map_data()
        land, borders = QPainterPath(), QPainterPath()
        for target, rings in ((land, data["land"]), (borders, data["borders"])):
            for r in rings:
                pts = [QPointF(*self.to_xy(r[i + 1], r[i])) for i in range(0, len(r) - 1, 2)]
                if len(pts) >= 3:
                    target.addPolygon(QPolygonF(pts))
                    target.closeSubpath()
        self._paths, self._paths_key = (land, borders), key
        return self._paths

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self.SEA)
        land, borders = self._land_paths()
        p.setPen(Qt.NoPen)
        p.setBrush(self.LAND)
        p.drawPath(land)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 0.7))
        p.drawPath(borders)
        # graticule tous les 30°
        p.setPen(QPen(QColor(255, 255, 255, 22), 1, Qt.DotLine))
        for lon in range(-180, 181, 30):
            x, _ = self.to_xy(0, lon)
            p.drawLine(int(x), 0, int(x), self.height())
        for lat in range(-60, 61, 30):
            _, y = self.to_xy(lat, 0)
            p.drawLine(0, int(y), self.width(), int(y))
        if self.greyline:
            x0, y0 = self.to_xy(90, -180)
            x1, y1 = self.to_xy(-90, 180)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(x0, y0, x1 - x0, y1 - y0), self._night_image())
            # soleil
            slat, slon = subsolar()
            sx, sy = self.to_xy(slat, slon)
            p.setPen(QPen(QColor("#ffcc33"), 1.5))
            p.setBrush(QColor(255, 204, 51, 120))
            p.drawEllipse(QPointF(sx, sy), 6, 6)
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        st = self.station
        p.setBrush(Qt.NoBrush)
        for name, pts in self.layers.items():
            for pt in pts:
                col = QColor(pt.get("color", "#ff9933"))
                if st and pt.get("line"):
                    c = QColor(col)
                    c.setAlpha(150)
                    p.setPen(QPen(c, 1.2))
                    path = QPainterPath()
                    prev = None
                    for la, lo in great_circle(st[0], st[1], pt["lat"], pt["lon"]):
                        x, y = self.to_xy(la, lo)
                        if prev is None or abs(lo - prev) > 180:
                            path.moveTo(x, y)
                        else:
                            path.lineTo(x, y)
                        prev = lo
                    p.drawPath(path)
        for name, pts in self.layers.items():
            for pt in pts:
                col = QColor(pt.get("color", "#ff9933"))
                x, y = self.to_xy(pt["lat"], pt["lon"])
                p.setPen(QPen(QColor(0, 0, 0, 160), 1))
                p.setBrush(col)
                r = pt.get("size", 4)
                p.drawEllipse(QPointF(x, y), r, r)
                if pt.get("label") and self.view[2] < 200:
                    p.setPen(QColor(235, 235, 235))
                    p.drawText(QPointF(x + r + 2, y + 4), pt["label"])
        if st:
            x, y = self.to_xy(*st)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QColor("#e8412c"))
            p.drawEllipse(QPointF(x, y), 5, 5)
        p.setPen(QColor(200, 200, 200, 150))
        p.drawText(QRectF(4, self.height() - 16, self.width() - 8, 14), Qt.AlignRight,
                   "Molette : zoom · glisser : déplacer · double-clic : monde")
