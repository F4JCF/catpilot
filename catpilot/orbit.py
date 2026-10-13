"""Calculs d'orbite : position des satellites (SGP4), passages et effet Doppler."""
import datetime
import math

from sgp4.api import Satrec, jday

C = 299_792_458.0
WGS84_A = 6378.137
WGS84_F = 1 / 298.257223563


def parse_tle(text):
    """Texte TLE (2 ou 3 lignes par satellite) -> {norad: (nom, ligne1, ligne2)}."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out, i = {}, 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            name, l1, l2 = f"SAT {lines[i][2:7].strip()}", lines[i], lines[i + 1]
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            i += 3
        else:
            i += 1
            continue
        try:
            out[int(l1[2:7])] = (name, l1, l2)
        except ValueError:
            pass
    return out


def _gmst(jd_ut1):
    t = (jd_ut1 - 2451545.0) / 36525.0
    g = (280.46061837 + 360.98564736629 * (jd_ut1 - 2451545.0) + 0.000387933 * t * t - t ** 3 / 38710000.0)
    return math.radians(g % 360.0)


def observer_ecef(lat, lon, alt_m=0.0):
    la, lo = math.radians(lat), math.radians(lon)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / math.sqrt(1 - e2 * math.sin(la) ** 2)
    h = alt_m / 1000.0
    return ((n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + h) * math.sin(la))


class Satellite:
    def __init__(self, name, l1, l2):
        self.name = name
        self.sat = Satrec.twoline2rv(l1, l2)
        self.norad = self.sat.satnum

    def ecef(self, when):
        jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute,
                      when.second + when.microsecond / 1e6)
        err, r, _v = self.sat.sgp4(jd, fr)
        if err:
            raise ValueError(f"SGP4 : erreur {err}")
        g = _gmst(jd + fr)
        cg, sg = math.cos(g), math.sin(g)
        return (cg * r[0] + sg * r[1], -sg * r[0] + cg * r[1], r[2])

    def look(self, lat, lon, when, alt_m=0.0):
        """Azimut, élévation (degrés), distance (km), vitesse radiale (m/s, positive = s'éloigne)."""
        obs = observer_ecef(lat, lon, alt_m)
        p0 = self.ecef(when)
        p1 = self.ecef(when + datetime.timedelta(seconds=1))
        d0 = [p0[i] - obs[i] for i in range(3)]
        d1 = [p1[i] - obs[i] for i in range(3)]
        rng0, rng1 = math.sqrt(sum(x * x for x in d0)), math.sqrt(sum(x * x for x in d1))
        la, lo = math.radians(lat), math.radians(lon)
        e = -math.sin(lo) * d0[0] + math.cos(lo) * d0[1]
        n = (-math.sin(la) * math.cos(lo) * d0[0] - math.sin(la) * math.sin(lo) * d0[1]
             + math.cos(la) * d0[2])
        u = math.cos(la) * math.cos(lo) * d0[0] + math.cos(la) * math.sin(lo) * d0[1] + math.sin(la) * d0[2]
        az = (math.degrees(math.atan2(e, n)) + 360) % 360
        el = math.degrees(math.asin(u / rng0))
        return az, el, rng0, (rng1 - rng0) * 1000.0

    def subpoint(self, when):
        x, y, z = self.ecef(when)
        lon = math.degrees(math.atan2(y, x))
        r = math.sqrt(x * x + y * y)
        lat = math.degrees(math.atan2(z, r * (1 - WGS84_F) ** 2))
        alt = math.sqrt(x * x + y * y + z * z) - WGS84_A
        return lat, lon, alt

    def passes(self, lat, lon, start, hours=24, min_el=0.0, alt_m=0.0):
        """Liste des passages : dict(aos, tca, los, max_el, az_aos, az_los)."""
        out, step = [], datetime.timedelta(seconds=30)
        t, end = start, start + datetime.timedelta(hours=hours)
        prev_el = self.look(lat, lon, t, alt_m)[1]
        cur = None
        if prev_el > 0:                      # passage en cours au moment du calcul
            cur = {"aos": t, "max_el": prev_el, "tca": t, "az_aos": self.look(lat, lon, t, alt_m)[0],
                   "ongoing": True}
        while t < end:
            t2 = t + step
            az, el, _r, _v = self.look(lat, lon, t2, alt_m)
            if prev_el <= 0 < el:
                aos = self._edge(lat, lon, t, t2, alt_m, rising=True)
                cur = {"aos": aos, "max_el": el, "tca": t2, "az_aos": self.look(lat, lon, aos, alt_m)[0]}
            if cur:
                if el > cur["max_el"]:
                    cur["max_el"], cur["tca"] = el, t2
                if prev_el > 0 >= el:
                    los = self._edge(lat, lon, t, t2, alt_m, rising=False)
                    cur["los"], cur["az_los"] = los, self.look(lat, lon, los, alt_m)[0]
                    if cur["max_el"] >= min_el:
                        out.append(cur)
                    cur = None
            prev_el, t = el, t2
        return out

    def _edge(self, lat, lon, a, b, alt_m, rising):
        for _ in range(12):
            m = a + (b - a) / 2
            above = self.look(lat, lon, m, alt_m)[1] > 0
            if above == rising:
                b = m
            else:
                a = m
        return b if rising else a


def doppler(freq_hz, range_rate):
    """Fréquence reçue au sol pour une émission du satellite sur freq_hz."""
    return freq_hz * (1 - range_rate / C)


def uplink(freq_hz, range_rate):
    """Fréquence à émettre au sol pour que le satellite reçoive freq_hz."""
    return freq_hz * (1 + range_rate / C)
