"""Pays DXCC d'un indicatif, d'après le fichier cty.dat (AD1C, country-files.com).

Une copie est fournie avec le logiciel ; une version plus récente est téléchargée
automatiquement une fois par mois dans Documents/CATPilot.
Pour chaque indicatif : entité DXCC, préfixe principal, zones CQ et ITU,
continent, latitude et longitude (est positif).
"""
import os
import re
import sys
import threading
import time
import urllib.request

URL = "https://www.country-files.com/cty/cty.dat"
_lock = threading.Lock()
_db = None          # (exacts, prefixes, entities)


def _bundled():
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, "assets", "cty.dat")


def _local():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot")
    return os.path.join(d, "cty.dat")


OVR = re.compile(r"\((\d+)\)|\[(\d+)\]|<([-\d.]+)/([-\d.]+)>|\{(\w+)\}|~([-\d.]+)~")


def parse(text):
    exacts, prefixes, entities = {}, {}, []
    ent = None
    buf = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            f = [x.strip() for x in line.split(":")]
            if len(f) < 8:
                continue
            prim = f[7]
            ent = {"name": f[0], "cq": f[1], "itu": f[2], "cont": f[3], "lat": float(f[4]),
                   "lon": -float(f[5]), "prefix": prim.lstrip("*"), "wae": prim.startswith("*")}
            entities.append(ent)
            buf = ""
            continue
        buf += line.strip()
        if not buf.endswith(";"):
            continue
        for item in buf[:-1].split(","):
            item = item.strip()
            if not item or ent is None:
                continue
            info = dict(ent)
            for m in OVR.finditer(item):
                cq, itu, la, lo, cont, _tz = m.groups()
                if cq:
                    info["cq"] = cq
                if itu:
                    info["itu"] = itu
                if la:
                    info["lat"], info["lon"] = float(la), -float(lo)
                if cont:
                    info["cont"] = cont
            key = OVR.sub("", item)
            if key.startswith("="):
                exacts[key[1:].upper()] = info
            else:
                prefixes[key.upper()] = info
        buf = ""
    return exacts, prefixes, entities


def _load():
    global _db
    with _lock:
        if _db is not None:
            return _db
        for path in (_local(), _bundled()):
            try:
                with open(path, encoding="latin-1") as f:
                    db = parse(f.read())
                if len(db[2]) > 300:
                    _db = db
                    break
            except OSError:
                continue
        if _db is None:
            _db = ({}, {}, [])
        return _db


def refresh_in_background(max_age_days=30):
    """Télécharge une version récente de cty.dat si la copie locale a plus d'un mois."""
    def run():
        global _db
        path = _local()
        try:
            if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_days * 86400:
                return
            req = urllib.request.Request(URL, headers={"User-Agent": "CATPilot"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read().decode("latin-1")
            db = parse(data)
            if len(db[2]) > 300:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="latin-1") as f:
                    f.write(data)
                with _lock:
                    _db = db
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


SKIP = {"P", "M", "MM", "AM", "QRP", "A", "B", "LH", "J", "R", "T"}


def base_call(call):
    """Indicatif principal : F4JCF/P -> F4JCF, EA8/F4JCF -> F4JCF, DL8LAS-1 -> DL8LAS."""
    call = (call or "").upper().strip()
    call = re.sub(r"-[0-9#]+$", "", call)
    parts = [p for p in call.split("/") if p]
    if not parts:
        return ""
    return max(parts, key=len)


def lookup(call):
    """Infos DXCC de l'indicatif, ou None."""
    exacts, prefixes, _ents = _load()
    call = (call or "").upper().strip()
    call = re.sub(r"-[0-9#]+$", "", call)          # spotters RBN : DL8LAS-#, DL8LAS-1
    if not call:
        return None
    if call in exacts:
        return exacts[call]
    parts = [p for p in call.split("/") if p]
    if not parts:
        return None
    if parts[-1] == "MM":
        return None                                 # maritime mobile : pas d'entité
    base = max(parts, key=len)
    key = base
    others = [p for p in parts if p is not base and p not in SKIP]
    if others:
        o = others[0]
        if o.isdigit() and len(o) == 1:             # W1AW/4 : change la région
            key = re.sub(r"\d", o, base, count=1)
        elif not o.isdigit():
            key = o                                 # EA8/F4JCF ou F4JCF/EA8
    if base in exacts and key == base:
        return exacts[base]
    for n in range(len(key), 0, -1):
        hit = prefixes.get(key[:n])
        if hit:
            return hit
    return None


WAE_PARENT = {"4U1V": "OE", "GM/s": "GM", "IG9": "I", "IT9": "I", "JW/b": "JW", "TA1": "TA"}


def dxcc(call):
    """Entité DXCC (pour les diplômes) : les entités WAE seules sont rattachées à leur pays."""
    info = lookup(call)
    if not info:
        return None
    if info["wae"]:
        parent = WAE_PARENT.get(info["prefix"])
        for e in _load()[2]:
            if e["prefix"] == parent:
                return e
    return info


def entities():
    return [e for e in _load()[2] if not e["wae"]]
