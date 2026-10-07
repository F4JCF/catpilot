"""Données de propagation (hamqsl.com, N0NBH), lues en arrière-plan."""
import threading
import urllib.request
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, QTimer, Signal

URL = "https://www.hamqsl.com/solarxml.php"
REFRESH_MS = 30 * 60 * 1000          # les données changent environ toutes les 3 h
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
    return data


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
