"""Locator Maidenhead, distances et caps, et lecture d'un GPS NMEA (port COM)."""
import math
import threading
import time

import serial
from PySide6.QtCore import QObject, Signal

EARTH_KM = 6371.0


def to_locator(lat, lon, precision=6):
    lon += 180
    lat += 90
    loc = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    loc += str(int((lon % 20) // 2)) + str(int(lat % 10))
    if precision >= 6:
        loc += chr(97 + int((lon % 2) * 12)) + chr(97 + int((lat % 1) * 24))
    return loc[:2].upper() + loc[2:4] + loc[4:].lower()


def from_locator(loc):
    """Centre du carré locator (4, 6 ou 8 caractères). ValueError si invalide."""
    loc = loc.strip()
    if len(loc) not in (4, 6, 8) or not loc[:2].isalpha() or not loc[2:4].isdigit():
        raise ValueError(f"locator invalide : {loc}")
    L = loc.upper()
    lon = (ord(L[0]) - 65) * 20 - 180 + int(L[2]) * 2
    lat = (ord(L[1]) - 65) * 10 - 90 + int(L[3])
    if not (0 <= ord(L[0]) - 65 < 18 and 0 <= ord(L[1]) - 65 < 18):
        raise ValueError(f"locator invalide : {loc}")
    dlon, dlat = 2.0, 1.0
    if len(L) >= 6:
        a, b = ord(L[4]) - 65, ord(L[5]) - 65
        if not (0 <= a < 24 and 0 <= b < 24):
            raise ValueError(f"locator invalide : {loc}")
        lon += a * 2 / 24
        lat += b / 24
        dlon, dlat = 2 / 24, 1 / 24
    if len(L) == 8:
        lon += int(L[6]) * 2 / 240
        lat += int(L[7]) / 240
        dlon, dlat = 2 / 240, 1 / 240
    return lat + dlat / 2, lon + dlon / 2


def distance_bearing(lat1, lon1, lat2, lon2):
    """Distance orthodromique (km) et cap initial (degrés) de 1 vers 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return d, (math.degrees(math.atan2(y, x)) + 360) % 360


def _nmea_coord(value, hemi, deg_digits):
    if not value:
        return None
    v = float(value[:deg_digits]) + float(value[deg_digits:]) / 60
    return -v if hemi in ("S", "W") else v


def parse_nmea(line):
    """Renvoie (lat, lon, alt ou None) pour une phrase RMC/GGA valide, sinon None."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return None
    body, _, chk = line[1:].partition("*")
    try:
        x = 0
        for ch in body:
            x ^= ord(ch)
        if int(chk[:2], 16) != x:
            return None
    except ValueError:
        return None
    f = body.split(",")
    kind = f[0][2:]
    try:
        if kind == "RMC" and len(f) > 6 and f[2] == "A":
            return _nmea_coord(f[3], f[4], 2), _nmea_coord(f[5], f[6], 3), None
        if kind == "GGA" and len(f) > 9 and f[6] not in ("", "0"):
            alt = float(f[9]) if f[9] else None
            return _nmea_coord(f[2], f[3], 2), _nmea_coord(f[4], f[5], 3), alt
    except (ValueError, IndexError):
        return None
    return None


class NmeaReader(QObject):
    """Lit un GPS NMEA (GPS USB, sortie GPS de l'IC-705 sur son 2e port COM…)."""
    position = Signal(float, float)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self._run = False
        self._thread = None

    def start(self, port, baud):
        self.stop()
        self._run = True
        self._thread = threading.Thread(target=self._loop, args=(port, baud), daemon=True)
        self._thread.start()

    def stop(self):
        self._run = False
        if self._thread:
            self._thread.join(2)
            self._thread = None

    def _loop(self, port, baud):
        try:
            ser = serial.Serial(port, baud, timeout=1)
        except Exception as e:
            self.status.emit(f"GPS : port {port} impossible à ouvrir ({e})")
            return
        last = 0.0
        try:
            while self._run:
                raw = ser.readline().decode("ascii", "ignore")
                pos = parse_nmea(raw)
                if pos and pos[0] is not None and time.monotonic() - last > 2:
                    last = time.monotonic()
                    self.position.emit(pos[0], pos[1])
        finally:
            ser.close()
