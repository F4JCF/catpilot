"""Département français d'un correspondant : d'après son code postal, ou sa position
(coordonnées de la fiche, sinon centre de son locator).

Contours : france-geojson (G. David), d'après Admin Express de l'IGN, Licence ouverte Etalab.
"""
import json
import os
import sys

DOM = {"971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
       "975": "Saint-Pierre-et-Miquelon", "977": "Saint-Barthélemy", "978": "Saint-Martin",
       "987": "Polynésie française", "988": "Nouvelle-Calédonie", "986": "Wallis-et-Futuna"}
# entités DXCC françaises -> département ou collectivité (outre-mer)
DXCC_DOM = {"FG": "971", "FM": "972", "FY": "973", "FR": "974", "FH": "976", "FP": "975", "FJ": "977",
            "FS": "978", "FO": "987", "FK": "988", "FW": "986"}
FRANCE = {"F", "TK"}

_DATA = None


def _load():
    global _DATA
    if _DATA is None:
        base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
        try:
            with open(os.path.join(base, "assets", "departements.json"), encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        _DATA = {}
        for code, d in raw.items():
            boxes = []
            for ring in d["rings"]:
                xs, ys = [p[0] for p in ring], [p[1] for p in ring]
                boxes.append((min(xs), min(ys), max(xs), max(ys), ring))
            _DATA[code] = (d["nom"], boxes)
    return _DATA


def rings(code=None):
    """Contours (liste d'anneaux [lon, lat]) d'un département, ou de tous."""
    data = _load()
    if code:
        return [b[4] for b in data.get(code, ("", []))[1]]
    return [b[4] for _n, boxes in data.values() for b in boxes]


def name(code):
    if code in DOM:
        return DOM[code]
    d = _load().get(code)
    return d[0] if d else ""


def _inside(x, y, ring):
    ins = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            ins = not ins
        j = i
    return ins


def from_position(lat, lon):
    """Code du département métropolitain qui contient ce point ("" en dehors)."""
    best, best_d = "", None
    for code, (_nom, boxes) in _load().items():
        for x0, y0, x1, y1, ring in boxes:
            if x0 <= lon <= x1 and y0 <= lat <= y1:
                if _inside(lon, lat, ring):
                    return code
                # au cas où le point tombe juste hors du contour simplifié (côte) : le plus proche
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                dd = (cx - lon) ** 2 + (cy - lat) ** 2
                if best_d is None or dd < best_d:
                    best, best_d = code, dd
    return best


def from_zip(zipcode, lat=None, lon=None):
    z = "".join(c for c in (zipcode or "") if c.isdigit())
    if len(z) != 5:
        return ""
    if z.startswith("97") or z.startswith("98"):
        return z[:3] if z[:3] in DOM else ""
    if z.startswith("20"):                         # Corse : 2A (sud) ou 2B (nord)
        if lat is not None and lon is not None:
            c = from_position(lat, lon)
            if c in ("2A", "2B"):
                return c
        return "2A" if int(z) < 20200 else "2B"
    code = z[:2]
    return code if code in _load() else ""


def for_station(call, zipcode="", lat=None, lon=None, grid=""):
    """(code, nom) du département d'une station française, sinon ("", "")."""
    from . import cty
    ent = cty.dxcc(call or "")
    pre = ent["prefix"] if ent else ""
    if pre in DXCC_DOM:
        c = DXCC_DOM[pre]
        return c, DOM[c]
    if pre not in FRANCE:
        return "", ""
    try:
        lat = float(lat) if lat not in (None, "") else None
        lon = float(lon) if lon not in (None, "") else None
    except ValueError:
        lat = lon = None
    if lat == 0 and lon == 0:
        lat = lon = None
    code = from_zip(zipcode, lat, lon)
    if not code and lat is not None and lon is not None:
        code = from_position(lat, lon)
    if not code and grid:
        try:
            from .geo import from_locator
            code = from_position(*from_locator(grid[:6]))
        except ValueError:
            pass
    return (code, name(code)) if code else ("", "")
