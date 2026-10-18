"""Données de propagation (hamqsl.com, N0NBH), lues en arrière-plan."""
import threading
import urllib.request
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, QTimer, Signal

URL = "https://www.hamqsl.com/solarxml.php"
REFRESH_MS = 20 * 60 * 1000          # hamqsl.com met à jour environ toutes les heures
FR = {"Good": "bonne", "Fair": "moyenne", "Poor": "mauvaise"}


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    d = root.find("solardata")
    if d is None:
        d = root
    get = lambda tag: (d.findtext(tag) or "").strip()
    data = {k: get(k) for k in ("solarflux", "aindex", "kindex", "sunspots", "xray",
                                "geomagfield", "signalnoise", "updated")}
    bands = {}
    for b in d.iter("band"):
        if b.get("name") and b.get("time"):
            bands[(b.get("name"), b.get("time"))] = (b.text or "").strip()
    data["bands"] = bands
    vhf = {}
    for ph in d.iter("phenomenon"):
        if ph.get("name") and ph.get("location"):
            vhf[(ph.get("name"), ph.get("location"))] = (ph.text or "").strip()
    data["vhf"] = vhf
    data["aurora"] = get("aurora")
    data["latdegree"] = get("latdegree")
    return data


def openings(data):
    """Alertes : sporadique E sur 6 m / 4 m / 2 m en Europe, aurore, orage magnétique."""
    out = []
    vhf = data.get("vhf", {})
    for loc, band in (("europe_6m", "6 m"), ("europe_4m", "4 m"), ("europe", "2 m")):
        v = vhf.get(("E-Skip", loc), "")
        if v and "closed" not in v.lower():
            out.append(("es", f"sporadique E en Europe sur {band} ({v})"))
    au = vhf.get(("vhf-aurora", "northern_hemi"), "")
    if au and "closed" not in au.lower():
        out.append(("aurora", f"aurore possible en VHF ({au})"))
    try:
        k = float(data.get("kindex") or 0)
    except ValueError:
        k = 0
    if k >= 5:
        out.append(("storm", f"orage magnétique (indice K {k:g}) : HF perturbées, aurore possible"))
    return out


class Propagation(QObject):
    updated = Signal(object)          # dict, ou une exception

    def __init__(self):
        super().__init__()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

    def refresh(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "CATPilot"})
            with urllib.request.urlopen(req, timeout=15) as r:
                self.updated.emit(parse(r.read()))
        except Exception as e:
            self.updated.emit(e)
