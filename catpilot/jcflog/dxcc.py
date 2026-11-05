import os, re, sys, urllib.request
from .db import appdir

URL = "https://www.country-files.com/cty/cty.csv"


def _bundled():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for p in (os.path.join(base, "cty.csv"), os.path.join(base, "assets", "cty.csv"),   # CAT Pilot : assets/
              os.path.join(os.path.dirname(base), "assets", "cty.csv")):
        if os.path.exists(p):
            return p
    return os.path.join(base, "cty.csv")


class DXCC:
    def __init__(self):
        self.exact, self.prefix, self.entities = {}, {}, {}
        self.load()

    def path(self):
        p = os.path.join(appdir(), "cty.csv")
        return p if os.path.exists(p) else _bundled()

    def update(self):
        data = urllib.request.urlopen(URL, timeout=30).read()
        with open(os.path.join(appdir(), "cty.csv"), "wb") as f:
            f.write(data)
        self.load()

    def load(self):
        p = self.path()
        if not os.path.exists(p):
            return
        self.exact.clear(); self.prefix.clear(); self.entities.clear()
        for line in open(p, encoding="latin-1"):
            parts = line.strip().rstrip(";").split(",")
            if len(parts) < 10:
                continue
            base = dict(name=parts[1], dxcc=parts[2].lstrip("*"), cont=parts[3], cqz=parts[4], ituz=parts[5],
                        lat=float(parts[6]), lon=-float(parts[7]), pfx=parts[0].lstrip("*"))
            if not parts[0].startswith("*"):
                self.entities[base["dxcc"]] = base
            for tok in parts[9].split():
                tok = tok.strip(";")
                e = dict(base)
                m = re.search(r"\((\d+)\)", tok)
                if m: e["cqz"] = m.group(1)
                m = re.search(r"\[(\d+)\]", tok)
                if m: e["ituz"] = m.group(1)
                m = re.search(r"\{(\w+)\}", tok)
                if m: e["cont"] = m.group(1)
                m = re.search(r"<([-\d.]+)/([-\d.]+)>", tok)
                if m: e["lat"], e["lon"] = float(m.group(1)), -float(m.group(2))
                key = re.sub(r"[\(\[\{<~].*", "", tok)
                if key.startswith("="):
                    self.exact[key[1:]] = e
                elif key:
                    self.prefix[key] = e

    def lookup(self, call):
        call = (call or "").upper().strip()
        if not call:
            return None
        if call in self.exact:
            return self.exact[call]
        parts = call.split("/")
        if len(parts) > 1:
            suffixes = {"P", "M", "MM", "AM", "QRP", "A", "B"}
            cands = [p for p in parts if p not in suffixes and not p.isdigit()]
            if cands:
                call = min(cands, key=len) if len(cands) > 1 and len(min(cands, key=len)) < len(max(cands, key=len)) else cands[0]
            if call in self.exact:
                return self.exact[call]
        for i in range(len(call), 0, -1):
            e = self.prefix.get(call[:i])
            if e:
                return e
        return None
