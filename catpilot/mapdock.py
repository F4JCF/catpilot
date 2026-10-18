"""Panneau « Carte » : ligne grise, qui m'entend (RBN), spots, QSO du carnet."""
import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from . import cty
from .geo import from_locator
from .worldmap import WorldMap, sun_times

BAND_COLORS = {"160m": "#9e9e9e", "80m": "#a1887f", "60m": "#795548", "40m": "#ff7043", "30m": "#ef5350",
               "20m": "#ab47bc", "17m": "#5c6bc0", "15m": "#29b6f6", "12m": "#26c6da", "10m": "#66bb6a",
               "6m": "#d4e157", "2m": "#ffee58", "70cm": "#ffa726"}


def band_color(hz):
    from .logbook import band_of_mhz
    return BAND_COLORS.get(band_of_mhz(hz / 1e6), "#bdbdbd")


class MapDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Carte", win)
        self.win = win
        self.setObjectName("mapdock")
        s = win.settings
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        self.ck = {}
        for key, label, default, tip in (
                ("grey", "Ligne grise", True, "Nuit et crépuscule : la propagation est souvent meilleure le long de la ligne grise"),
                ("me", "Qui m'entend", True, "Stations du RBN qui vous entendent (panneau Spots)"),
                ("dx", "Spots DX", True, "Spots du DX cluster des 30 dernières minutes, couleur selon la bande"),
                ("pota", "POTA", False, "Activations POTA en cours"),
                ("beacons", "Balises", False, "Balises NCDXF qui émettent en ce moment (changent toutes les 10 s)"),
                ("log", "Mes QSO", False, "QSO du carnet")):
            c = QCheckBox(label)
            c.setToolTip(tip)
            c.setChecked(s.value(f"map_{key}", "true" if default else "false") in (True, "true"))
            c.toggled.connect(self._now)
            h.addWidget(c)
            self.ck[key] = c
        self.cb_log = QComboBox()
        self.cb_log.addItems(["aujourd'hui", "7 jours", "30 jours", "tout le carnet"])
        self.cb_log.setCurrentIndex(int(s.value("map_log_range", 1)))
        self.cb_log.currentIndexChanged.connect(self._now)
        h.addWidget(self.cb_log)
        h.addStretch()
        for label, slot in (("Monde", lambda: self.map.show_world()), ("Europe", lambda: self.map.show_region(48, 12, 34)),
                            ("Ma région", self.zoom_home)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.map = WorldMap()
        self.map.clicked.connect(self.on_click)
        v.addWidget(self.map, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        v.addWidget(self.lb)
        self.setWidget(w)
        self.setMinimumWidth(520)
        self._dirty = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2000)
        self.visibilityChanged.connect(lambda vis: vis and self._tick())
        win.log.changed.connect(self.update_layers)

    def zoom_home(self):
        st = getattr(self.win, "station", None)
        if st:
            self.map.show_region(st[0], st[1], 24)

    def update_layers(self, *_):
        self._dirty = True                  # redessiné au prochain tour du minuteur (2 s)

    def _now(self, *_):
        self._dirty = True
        self._tick()

    def _tick(self):
        if not self.isVisible():
            return
        if self._dirty:
            self._dirty = False
            self._rebuild()
        self._beacons()
        self._sun_info()

    def _sun_info(self):
        st = getattr(self.win, "station", None)
        if not st:
            self.lb.setText("Réglez la position de la station (clic sur le locator, en haut) pour la voir sur la carte")
            return
        rise, set_ = sun_times(*st)
        loc = lambda t: t.astimezone().strftime("%H:%M") if t else "—"
        utc = lambda t: t.strftime("%H:%M") if t else "—"
        self.lb.setText(f"À la station : lever du soleil {utc(rise)} UTC ({loc(rise)}), coucher {utc(set_)} UTC "
                        f"({loc(set_)}). La ligne grise passe chez vous autour de ces heures.")

    def _rebuild(self):
        m = self.map
        m.greyline = self.ck["grey"].isChecked()
        m.set_station(getattr(self.win, "station", None))
        spots = getattr(self.win, "spots", None)
        # qui m'entend
        pts = []
        if self.ck["me"].isChecked() and spots:
            for sp in spots.data.get("me", []):
                if "lat" in sp:
                    tip = (f"{sp['spotter']} vous entend : {sp.get('snr', '?')} dB, "
                           f"{sp['hz'] / 1e3:.1f} kHz {sp.get('mode', '')}")
                    if sp.get("km") is not None:
                        tip += f", {sp['km']:.0f} km"
                    pts.append({"lat": sp["lat"], "lon": sp["lon"], "label": sp["spotter"], "tip": tip,
                                "color": "#ffb300", "line": True, "size": 4})
        m.set_layer("me", pts)
        # spots DX
        pts = []
        if self.ck["dx"].isChecked() and spots:
            now = datetime.datetime.now(datetime.timezone.utc)
            for sp in spots.data.get("dx", [])[:150]:
                if "lat" not in sp:
                    continue
                try:
                    hh, mm = map(int, sp["time"].split(":"))
                    age = (now.hour * 60 + now.minute - hh * 60 - mm) % 1440
                    if age > 30:
                        continue
                except ValueError:
                    pass
                pts.append({"lat": sp["lat"], "lon": sp["lon"], "label": sp["call"],
                            "tip": f"{sp['call']} {sp['hz'] / 1e3:.1f} kHz {sp['mode']} — {sp['time']} UTC"
                                   + (f"\nAlerte : {sp['alert']}" if sp.get("alert") else ""),
                            "color": "#ff3d00" if sp.get("alert") else band_color(sp["hz"]),
                            "size": 5 if sp.get("alert") else 3, "spot": ("dx", sp)})
        m.set_layer("dx", pts)
        pts = []
        if self.ck["pota"].isChecked() and spots:
            for sp in spots.data.get("pota", []):
                if "lat" in sp:
                    pts.append({"lat": sp["lat"], "lon": sp["lon"], "label": sp["call"],
                                "tip": f"{sp['call']} — {sp['ref']} {sp.get('info', '')}\n"
                                       f"{sp['hz'] / 1e3:.1f} kHz {sp['mode']}",
                                "color": "#43a047", "size": 3, "spot": ("pota", sp)})
        m.set_layer("pota", pts)
        # QSO du carnet
        pts = []
        if self.ck["log"].isChecked():
            days = (1, 7, 30, None)[self.cb_log.currentIndex()]
            where, args = "1", ()
            if days:
                d0 = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days - 1)).strftime("%Y%m%d")
                where, args = "qso_date >= ?", (d0,)
            seen = set()
            for r in self.win.log.query(where, args, limit=3000):
                pos = None
                if r.get("gridsquare"):
                    try:
                        pos = from_locator(r["gridsquare"][:6])
                    except ValueError:
                        pos = None
                if not pos:
                    info = cty.lookup(r["call"])
                    pos = (info["lat"], info["lon"]) if info else None
                if not pos or (r["call"], r.get("band")) in seen:
                    continue
                seen.add((r["call"], r.get("band")))
                pts.append({"lat": pos[0], "lon": pos[1], "label": r["call"],
                            "tip": f"{r['call']} — {r.get('band', '')} {r.get('mode', '')} le "
                                   f"{r['qso_date'][6:8]}/{r['qso_date'][4:6]}/{r['qso_date'][:4]}",
                            "color": "#4fc3f7", "size": 3, "line": days == 1})
        m.set_layer("log", pts)

    def _beacons(self):
        spots = getattr(self.win, "spots", None)
        on = self.ck["beacons"].isChecked() and spots is not None
        cur = spots.current_beacons() if on else []
        key = tuple(c for c, *_r in cur)
        if key == getattr(self, "_bkey", None):
            return
        self._bkey = key
        pts = []
        for call, grid, band, hz in cur:
            try:
                lat, lon = from_locator(grid)
            except ValueError:
                continue
            pts.append({"lat": lat, "lon": lon, "label": f"{call} {band}",
                        "tip": f"Balise {call} émet sur {hz / 1e3:.0f} kHz ({band})", "color": band_color(hz),
                        "size": 5, "line": True, "beacon": hz})
        self.map.set_layer("beacons", pts)

    def on_click(self, pt):
        if pt and pt.get("beacon") and self.win.ctrl.connected:
            self.win.ctrl.set_freq(pt["beacon"])
            if "CW" in self.win.ctrl.driver.modes:
                self.win.ctrl.set_mode("CW")
            return
        if pt and pt.get("spot") and self.win.spots:
            kind, sp = pt["spot"]
            rows = self.win.spots.tables[kind].property("rows") or []
            if sp in rows:
                self.win.spots.tune(kind, rows.index(sp))

    def save_settings(self, s):
        for k, c in self.ck.items():
            s.setValue(f"map_{k}", c.isChecked())
        s.setValue("map_log_range", self.cb_log.currentIndex())
