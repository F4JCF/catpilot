"""Carnet de trafic : base SQLite, recherche HamQTH, import/export ADIF."""
import datetime
import os
import re
import sqlite3
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, adif

FIELDS = ["call", "qso_date", "time_on", "freq", "band", "mode", "submode", "rst_sent", "rst_rcvd",
          "name", "qth", "gridsquare", "sig", "sig_info", "my_sig", "my_sig_info", "comment",
          "tx_pwr", "my_gridsquare", "station_callsign", "operator", "country",
          "contest_id", "stx", "srx", "stx_string", "srx_string",
          "qsl_via", "eqsl_qsl_rcvd", "eqsl_qslrdate", "lotw_qsl_rcvd", "lotw_qslrdate",
          "qsl_sent", "qsl_rcvd", "qsl_sent_via", "qslsdate", "qslrdate", "state"]
# Champs propres aux confirmations : jamais envoyés aux carnets en ligne
QSL_FIELDS = ("eqsl_qsl_rcvd", "eqsl_qslrdate", "lotw_qsl_rcvd", "lotw_qslrdate")

BAND_EDGES = [("2200m", 0.1357, 0.1378), ("630m", 0.472, 0.479), ("160m", 1.8, 2.0), ("80m", 3.5, 4.0),
              ("60m", 5.06, 5.45), ("40m", 7.0, 7.3), ("30m", 10.1, 10.15), ("20m", 14.0, 14.35),
              ("17m", 18.068, 18.168), ("15m", 21.0, 21.45), ("12m", 24.89, 24.99), ("10m", 28.0, 29.7),
              ("6m", 50.0, 54.0), ("4m", 70.0, 71.0), ("2m", 144.0, 148.0), ("70cm", 420.0, 450.0),
              ("23cm", 1240.0, 1300.0)]


def band_of_mhz(mhz):
    try:
        f = float(mhz)
    except (TypeError, ValueError):
        return ""
    return next((b for b, lo, hi in BAND_EDGES if lo <= f <= hi), "")


def data_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot")
    os.makedirs(d, exist_ok=True)
    return d


UP_COLS = ("up_qrz", "up_eqsl", "up_clublog", "up_lotw")
EXTRA_COLS = ("audio_file",)          # colonnes propres à CAT Pilot (hors ADIF)


class Log(QObject):
    changed = Signal()
    added = Signal(int)                     # identifiant du QSO ajouté
    fields = FIELDS

    def __init__(self, path=None):
        super().__init__()
        self.path = path or os.path.join(data_dir(), "carnet.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.Lock()
        cols = ", ".join(f"{f} TEXT" for f in FIELDS)
        with self.lock:
            self.db.execute(f"CREATE TABLE IF NOT EXISTS qso (id INTEGER PRIMARY KEY, {cols})")
            have = {r[1] for r in self.db.execute("PRAGMA table_info(qso)")}
            for f in FIELDS + list(UP_COLS) + list(EXTRA_COLS):
                if f not in have:
                    self.db.execute(f"ALTER TABLE qso ADD COLUMN {f} TEXT")
                    if f in UP_COLS:          # les QSO déjà présents ne sont pas envoyés d'office
                        self.db.execute(f"UPDATE qso SET {f} = 'ancien'")
            self.db.execute("CREATE INDEX IF NOT EXISTS qso_call ON qso(call)")
            self.db.commit()

    def add(self, rec, notify=True):
        rec = {k: (str(v).strip() if v is not None else "") for k, v in rec.items() if k in FIELDS}
        rec["call"] = rec.get("call", "").upper()
        if not rec.get("band") and rec.get("freq"):
            rec["band"] = band_of_mhz(rec["freq"])
        keys = list(rec)
        with self.lock:
            cur = self.db.execute(f"INSERT INTO qso ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                                  [rec[k] for k in keys])
            self.db.commit()
            qid = cur.lastrowid
        if notify:
            self.changed.emit()
            self.added.emit(qid)
        return qid

    def pending(self, svc, ids=None):
        """QSO pas encore envoyés à ce service (QRZ, eQSL, Club Log, LoTW)."""
        col = f"up_{svc}"
        where, args = f"({col} IS NULL OR {col} = '')", ()
        if ids:
            where += f" AND id IN ({', '.join('?' * len(ids))})"
            args = tuple(ids)
        return list(reversed(self.query(where, args)))

    def reset_upload(self, svc):
        """Tout le carnet sera renvoyé à ce service."""
        with self.lock:
            self.db.execute(f"UPDATE qso SET up_{svc} = NULL")
            self.db.commit()

    def mark_all_uploaded(self, ids, value="import"):
        with self.lock:
            for qid in ids:
                self.db.execute("UPDATE qso SET up_qrz = ?, up_eqsl = ?, up_clublog = ?, up_lotw = ? WHERE id = ?",
                                (value, value, value, value, qid))
            self.db.commit()

    def mark_uploaded(self, qid, svc):
        with self.lock:
            self.db.execute(f"UPDATE qso SET up_{svc} = ? WHERE id = ?",
                            (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d"), qid))
            self.db.commit()

    def upload_counts(self):
        with self.lock:
            return {c[3:]: self.db.execute(f"SELECT COUNT(*) FROM qso WHERE {c} IS NULL OR {c} = ''").fetchone()[0]
                    for c in UP_COLS}

    def update(self, qid, rec, notify=True):
        rec = {k: (str(v).strip() if v is not None else "") for k, v in rec.items()
               if k in FIELDS or k in EXTRA_COLS}
        if not rec:
            return
        with self.lock:
            self.db.execute(f"UPDATE qso SET {', '.join(k + ' = ?' for k in rec)} WHERE id = ?",
                            list(rec.values()) + [qid])
            self.db.commit()
        if notify:
            self.changed.emit()

    def delete(self, qid):
        with self.lock:
            self.db.execute("DELETE FROM qso WHERE id = ?", (qid,))
            self.db.commit()
        self.changed.emit()

    def is_dupe(self, rec, minutes=3):
        """Même indicatif, même bande, même mode, à quelques minutes près."""
        try:
            t = datetime.datetime.strptime(rec["qso_date"] + rec["time_on"][:4], "%Y%m%d%H%M")
        except (KeyError, ValueError):
            return False
        for r in self.query("call = ? AND qso_date = ? AND band = ?",
                            (rec.get("call", "").upper(), rec["qso_date"], rec.get("band", ""))):
            try:
                t2 = datetime.datetime.strptime(r["qso_date"] + r["time_on"][:4], "%Y%m%d%H%M")
            except ValueError:
                continue
            if abs((t - t2).total_seconds()) <= minutes * 60 and r.get("mode") == rec.get("mode"):
                return True
        return False

    def query(self, where="1", args=(), limit=None):
        cols = FIELDS + list(UP_COLS) + list(EXTRA_COLS)
        sql = f"SELECT id, {', '.join(cols)} FROM qso WHERE {where} ORDER BY qso_date DESC, time_on DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [dict(zip(["id"] + cols, r)) for r in rows]

    def confirmed_counts(self):
        with self.lock:
            return {svc: self.db.execute(f"SELECT COUNT(*) FROM qso WHERE {svc}_qsl_rcvd = 'Y'").fetchone()[0]
                    for svc in ("eqsl", "lotw")}

    def worked(self, call):
        """Bandes et modes déjà contactés avec cet indicatif."""
        rows = self.query("call = ?", (call.upper(),))
        return rows

    def count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM qso").fetchone()[0]

    def export_records(self, rows):
        out = []
        for r in rows:
            out.append({k: r.get(k) for k in FIELDS if r.get(k)})
        return out


class HamQTH(QObject):
    """Recherche d'indicatif sur plusieurs sites, dans l'ordre :
    QRZ.com (si compte), HamQTH.com (si compte), callook.info (indicatifs US, sans compte),
    puis pays et zones déduits du préfixe (sans Internet).
    Les champs manquants d'une source sont complétés par la suivante."""
    result = Signal(str, object)          # indicatif, dict ou message d'erreur (str)

    URL = "https://www.hamqth.com/xml.php"
    NS = "{https://www.hamqth.com}"
    QRZ_URL = "https://xmldata.qrz.com/xml/current/"
    QRZCQ_URL = "https://ssl.qrzcq.com/xml"
    KEYS = ("name", "qth", "country", "grid", "itu", "cq", "lat", "lon")

    def __init__(self):
        super().__init__()
        self.user = self.password = ""
        self.qrz_user = self.qrz_password = ""
        self.session = None
        self.qrz_session = None
        self.qrzcq_user = self.qrzcq_password = ""
        self.qrzcq_session = None
        self.cache = {}

    def lookup(self, call):
        call = call.strip().upper()
        if not call:
            return
        if call in self.cache:
            self.result.emit(call, self.cache[call])
            return
        threading.Thread(target=self._lookup, args=(call,), daemon=True).start()

    def _open(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": f"CATPilot/{__version__}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    def _get(self, params):
        return ET.fromstring(self._open(self.URL + "?" + urllib.parse.urlencode(params)))

    @staticmethod
    def _find(root, tag):
        for el in root.iter():
            if el.tag.split("}")[-1] == tag:
                return (el.text or "").strip()
        return ""

    def _text(self, root, tag):
        return self._find(root, tag)

    # --- sources -----------------------------------------------------------------------
    def _qrz(self, call):
        if not self.qrz_user or not self.qrz_password:
            return None, None
        for attempt in range(2):
            if not self.qrz_session:
                root = ET.fromstring(self._open(self.QRZ_URL + "?" + urllib.parse.urlencode(
                    {"username": self.qrz_user, "password": self.qrz_password,
                     "agent": f"CATPilot{__version__}"})))
                self.qrz_session = self._find(root, "Key") or None
                if not self.qrz_session:
                    return None, "QRZ.com : " + (self._find(root, "Error") or "connexion refusée")
            root = ET.fromstring(self._open(self.QRZ_URL + "?" + urllib.parse.urlencode(
                {"s": self.qrz_session, "callsign": call})))
            err = self._find(root, "Error")
            if not self._find(root, "call"):
                if err and "session" in err.lower() and attempt == 0:
                    self.qrz_session = None
                    continue
                return None, (f"QRZ.com : {err}" if err and "not found" not in err.lower() else None)
            f = lambda t: self._find(root, t)
            qth = ", ".join(x for x in (f("addr2"), f("state")) if x)
            return {"name": full_name(" ".join(x for x in (f("fname"), f("name")) if x)) or f("nickname"),
                    "qth": qth, "country": f("country"), "grid": f("grid"), "itu": f("ituzone"),
                    "cq": f("cqzone"), "lat": f("lat"), "lon": f("lon"), "qsl_via": f("qslmgr"),
                    "lotw": f("lotw") == "1", "eqsl": f("eqsl") == "1", "photo": f("image"),
                    "zip": f("zip"), "src": "QRZ.com"}, None
        return None, None

    def _hamqth(self, call):
        if not self.user or not self.password:
            return None, None
        for attempt in range(2):
            if not self.session:
                root = self._get({"u": self.user, "p": self.password})
                self.session = self._text(root, "session_id") or None
                if not self.session:
                    return None, "HamQTH : " + (self._text(root, "error") or "connexion refusée")
            root = self._get({"id": self.session, "callsign": call, "prg": "CATPilot"})
            err = self._text(root, "error")
            if err and "session" in err.lower() and attempt == 0:
                self.session = None
                continue
            if err:
                return None, (None if "not found" in err.lower() else f"HamQTH : {err}")
            info = {k: self._text(root, k) for k in
                    ("nick", "adr_name", "qth", "country", "grid", "itu", "cq", "lat", "lon", "qsl_via")}
            info["photo"] = self._text(root, "picture")
            info["zip"] = self._text(root, "adr_zip")
            info["lotw"] = self._text(root, "lotw").upper() == "Y"
            info["eqsl"] = self._text(root, "eqsl").upper() == "Y"
            full = full_name(info.pop("adr_name", ""))
            nick = info.pop("nick", "")
            info["name"] = full if full and (not nick or nick.split(" ")[0].lower() in full.lower()) else (nick or full)
            info["src"] = "HamQTH"
            return info, None
        return None, None

    def _qrzcq(self, call):
        """QRZCQ.com (compte gratuit ; certaines fiches demandent l'abonnement « premium »)."""
        if not self.qrzcq_user or not self.qrzcq_password:
            return None, None
        agent = f"CATPilot{__version__}"
        for attempt in range(2):
            if not self.qrzcq_session:
                root = ET.fromstring(self._open(self.QRZCQ_URL + "?" + urllib.parse.urlencode(
                    {"username": self.qrzcq_user, "password": self.qrzcq_password, "agent": agent})))
                self.qrzcq_session = self._find(root, "Key") or None
                if not self.qrzcq_session:
                    return None, "QRZCQ : " + (self._find(root, "Error") or "connexion refusée")
            root = ET.fromstring(self._open(self.QRZCQ_URL + "?" + urllib.parse.urlencode(
                {"s": self.qrzcq_session, "callsign": call, "agent": agent})))
            err = self._find(root, "Error")
            if not self._find(root, "call"):
                if err and ("session" in err.lower() or "key" in err.lower()) and attempt == 0:
                    self.qrzcq_session = None
                    continue
                return None, (f"QRZCQ : {err}" if err and "not found" not in err.lower() else None)
            f = lambda t: self._find(root, t)
            name = f("name")
            return {"name": full_name(name),
                    "qth": f("city") or f("qth"), "country": f("country"), "grid": f("locator"),
                    "itu": f("itu"), "cq": f("cq"), "lat": f("latitude"), "lon": f("longitude"),
                    "qsl_via": f("manager"), "lotw": f("lotw").upper() in ("1", "Y", "YES"),
                    "eqsl": (f("eqsl") or f("eqsle")).upper() in ("1", "Y", "YES"),
                    "photo": f("picture") or f("image") or f("qslpic"), "zip": f("zip"), "src": "QRZCQ"}, None
        return None, None

    def _callook(self, call):
        if not re.match(r"^(A[A-L]|[KNW])[A-Z]?\d[A-Z]{1,3}$", call.split("/")[0]):
            return None, None
        import json
        d = json.loads(self._open(f"https://callook.info/{urllib.parse.quote(call.split('/')[0])}/json"))
        if d.get("status") != "VALID":
            return None, None
        loc, adr = d.get("location") or {}, d.get("address") or {}
        name = (d.get("name") or "").title()
        return {"name": name, "qth": (adr.get("line2") or "").title(),
                "country": "États-Unis", "grid": loc.get("gridsquare", ""),
                "lat": loc.get("latitude", ""), "lon": loc.get("longitude", ""), "src": "callook.info"}, None

    def _lookup(self, call):
        info, errors, sources = {}, [], []
        for fn in (self._qrz, self._hamqth, self._qrzcq, self._callook):
            try:
                got, err = fn(call)
            except Exception as e:
                got, err = None, f"{fn.__name__.strip('_')} injoignable : {e}"
            if err:
                errors.append(err)
            if got:
                sources.append(got.pop("src", ""))
                for k, v in got.items():
                    if v and not info.get(k):
                        info[k] = v
            if all(info.get(k) for k in ("name", "qth", "grid")):
                break
        if not info.get("grid") and info.get("lat") and info.get("lon"):
            try:
                from .geo import to_locator
                lat, lon = float(info["lat"]), float(info["lon"])
                if lat or lon:
                    info["grid"] = to_locator(lat, lon)
            except ValueError:
                pass
        pre = prefix_info(call)
        if pre:
            for k in ("country", "cq", "itu"):
                if pre.get(k) and not info.get(k):
                    info[k] = pre[k]
        if not info:
            self.result.emit(call, " ; ".join(errors) or "Indicatif inconnu")
            return
        info["sources"] = ", ".join(s for s in sources if s) or "préfixe"
        if not sources and not self.qrz_user and not self.user and not self.qrzcq_user:
            info["hint"] = "pour le nom et le QTH, ajoutez un compte HamQTH, QRZCQ ou QRZ.com (Carnet > Réglages)"
        if errors and not sources:
            info["hint"] = " ; ".join(errors)
        if sources:
            self.cache[call] = info
        self.result.emit(call, info)


TABLE_COLS = ["Date", "UTC", "Indicatif", "Nom", "Pays", "Dépt", "Fréquence", "Bande", "Mode", "Env.", "Reçu",
              "QSL", "eQSL", "LoTW", "♪", "Réf."]
C_PAYS, C_DEPT, C_FREQ, C_QSL, C_EQSL, C_LOTW, C_AUDIO = 4, 5, 6, 11, 12, 13, 14


class PhotoLoader(QObject):
    """Télécharge la photo d'un opérateur (adresse donnée par HamQTH, QRZ.com ou QRZCQ)."""
    loaded = Signal(str, bytes)

    def __init__(self):
        super().__init__()
        self.cache = {}

    def get(self, call, url):
        if call in self.cache:
            self.loaded.emit(call, self.cache[call])
            return
        if not url.startswith("http"):
            url = "https:" + url if url.startswith("//") else "https://" + url
        threading.Thread(target=self._run, args=(call, url), daemon=True).start()

    def _run(self, call, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"CATPilot/{__version__}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read(4_000_000)
            self.cache[call] = data
            self.loaded.emit(call, data)
        except Exception:
            pass


CALL_RE = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}[A-Z](/[A-Z0-9]{1,4})*$")


def my_calls(s):
    import json
    try:
        calls = json.loads(s.value("mycalls", "[]") or "[]")
    except ValueError:
        calls = []
    cur = (s.value("mycall", "") or "").upper()
    if cur and cur not in calls:
        calls.insert(0, cur)
    return calls


def describe_mycall(call):
    """« portable, depuis La Réunion » : ce que veut dire l'indicatif choisi."""
    if not call:
        return "indiquez votre indicatif"
    parts = call.split("/")
    notes = []
    suffix = {"P": "portable", "M": "mobile", "MM": "maritime mobile", "AM": "aéronautique mobile",
              "QRP": "QRP", "A": "autre adresse"}
    for p in parts[1:]:
        if p in suffix:
            notes.append(suffix[p])
    try:
        from .qsl import country_of
        _iso, country = country_of(call)
        _iso0, home = country_of(max(parts, key=len))
        if country and country != home:
            notes.append(f"depuis {country}")
    except Exception:
        pass
    return " · ".join(notes)


def full_name(name):
    """« MARC DUPONT » ou « marc dupont » -> « Marc Dupont » ; un nom déjà écrit proprement est gardé."""
    name = " ".join((name or "").split())
    if name and (name.isupper() or name.islower()):
        name = " ".join(w.capitalize() if "-" not in w else "-".join(x.capitalize() for x in w.split("-"))
                        for w in name.split(" "))
    return name


ACTIVITIES = ["", "POTA", "SOTA", "WWFF", "BOTA", "IOTA", "LLOTA", "DFCF", "DMF", "Autre"]
ACTIVITY_HINT = {"POTA": "ex. FR-0123", "SOTA": "ex. F/AM-123", "WWFF": "ex. FFF-0123", "BOTA": "ex. B/F-0123",
                 "IOTA": "ex. EU-005", "LLOTA": "ex. FR-0001", "DFCF": "ex. 06-001", "DMF": "ex. 06-001",
                 "Autre": "référence"}


def guess_activity(ref):
    r = (ref or "").upper()
    if re.match(r"^[A-Z0-9]{1,3}/[A-Z]{2}-\d+$", r):
        return "SOTA"
    if re.match(r"^B/", r):
        return "BOTA"
    if re.match(r"^[A-Z0-9]{1,2}FF-\d+$", r):
        return "WWFF"
    if re.match(r"^(AF|AN|AS|EU|NA|OC|SA)-\d{3}$", r):
        return "IOTA"
    return "POTA" if r else ""


# Préfixe -> (pays, zone CQ, zone ITU). Les plus longs sont testés en premier.
PREFIXES = {
    "F": ("France", 14, 27), "TK": ("Corse", 15, 28), "FR": ("La Réunion", 39, 53),
    "FM": ("Martinique", 8, 11), "FG": ("Guadeloupe", 8, 11), "FY": ("Guyane", 9, 12),
    "FK": ("Nouvelle-Calédonie", 32, 56), "FO": ("Polynésie française", 32, 63),
    "FH": ("Mayotte", 39, 53), "FP": ("Saint-Pierre-et-Miquelon", 5, 9), "FS": ("Saint-Martin", 8, 11),
    "3A": ("Monaco", 14, 27), "ON": ("Belgique", 14, 27), "OO": ("Belgique", 14, 27),
    "OR": ("Belgique", 14, 27), "OT": ("Belgique", 14, 27), "LX": ("Luxembourg", 14, 27),
    "HB0": ("Liechtenstein", 14, 28), "HB": ("Suisse", 14, 28), "HE": ("Suisse", 14, 28),
    "EA6": ("Baléares", 14, 37), "EA8": ("Canaries", 33, 36), "EA9": ("Ceuta et Melilla", 33, 37),
    "EA": ("Espagne", 14, 37), "EB": ("Espagne", 14, 37), "EC": ("Espagne", 14, 37), "ED": ("Espagne", 14, 37),
    "EE": ("Espagne", 14, 37), "EF": ("Espagne", 14, 37), "EG": ("Espagne", 14, 37), "EH": ("Espagne", 14, 37),
    "C3": ("Andorre", 14, 27), "CT3": ("Madère", 33, 36), "CU": ("Açores", 14, 36), "CT": ("Portugal", 14, 37),
    "CQ": ("Portugal", 14, 37), "CS": ("Portugal", 14, 37),
    "IS0": ("Sardaigne", 15, 28), "IM0": ("Sardaigne", 15, 28), "IT9": ("Sicile", 15, 28),
    "I": ("Italie", 15, 28), "T7": ("Saint-Marin", 15, 28), "HV": ("Vatican", 15, 28),
    "9H": ("Malte", 15, 28), "DA": ("Allemagne", 14, 28), "DB": ("Allemagne", 14, 28),
    "DC": ("Allemagne", 14, 28), "DD": ("Allemagne", 14, 28), "DF": ("Allemagne", 14, 28),
    "DG": ("Allemagne", 14, 28), "DH": ("Allemagne", 14, 28), "DJ": ("Allemagne", 14, 28),
    "DK": ("Allemagne", 14, 28), "DL": ("Allemagne", 14, 28), "DM": ("Allemagne", 14, 28),
    "DO": ("Allemagne", 14, 28), "DP": ("Allemagne", 14, 28), "DQ": ("Allemagne", 14, 28),
    "DR": ("Allemagne", 14, 28), "OE": ("Autriche", 15, 28), "PA": ("Pays-Bas", 14, 27),
    "PB": ("Pays-Bas", 14, 27), "PC": ("Pays-Bas", 14, 27), "PD": ("Pays-Bas", 14, 27),
    "PE": ("Pays-Bas", 14, 27), "PF": ("Pays-Bas", 14, 27), "PG": ("Pays-Bas", 14, 27),
    "PH": ("Pays-Bas", 14, 27), "PI": ("Pays-Bas", 14, 27),
    "G": ("Angleterre", 14, 27), "M": ("Angleterre", 14, 27), "2E": ("Angleterre", 14, 27),
    "GM": ("Écosse", 14, 27), "MM": ("Écosse", 14, 27), "2M": ("Écosse", 14, 27),
    "GW": ("Pays de Galles", 14, 27), "MW": ("Pays de Galles", 14, 27), "2W": ("Pays de Galles", 14, 27),
    "GI": ("Irlande du Nord", 14, 27), "MI": ("Irlande du Nord", 14, 27), "2I": ("Irlande du Nord", 14, 27),
    "GD": ("Île de Man", 14, 27), "MD": ("Île de Man", 14, 27), "GJ": ("Jersey", 14, 27),
    "MJ": ("Jersey", 14, 27), "GU": ("Guernesey", 14, 27), "MU": ("Guernesey", 14, 27),
    "EI": ("Irlande", 14, 27), "EJ": ("Irlande", 14, 27),
    "OZ": ("Danemark", 14, 18), "OX": ("Groenland", 40, 5), "OY": ("Féroé", 14, 18),
    "LA": ("Norvège", 14, 18), "LB": ("Norvège", 14, 18), "JW": ("Svalbard", 40, 18),
    "SM": ("Suède", 14, 18), "SA": ("Suède", 14, 18), "SK": ("Suède", 14, 18), "7S": ("Suède", 14, 18),
    "OH0": ("Åland", 15, 18), "OH": ("Finlande", 15, 18), "OG": ("Finlande", 15, 18), "TF": ("Islande", 40, 17),
    "SP": ("Pologne", 15, 28), "SQ": ("Pologne", 15, 28), "SN": ("Pologne", 15, 28), "SO": ("Pologne", 15, 28),
    "3Z": ("Pologne", 15, 28), "HF": ("Pologne", 15, 28),
    "OK": ("Tchéquie", 15, 28), "OL": ("Tchéquie", 15, 28), "OM": ("Slovaquie", 15, 28),
    "HA": ("Hongrie", 15, 28), "HG": ("Hongrie", 15, 28), "S5": ("Slovénie", 15, 28),
    "9A": ("Croatie", 15, 28), "E7": ("Bosnie-Herzégovine", 15, 28), "YU": ("Serbie", 15, 28),
    "4O": ("Monténégro", 15, 28), "Z3": ("Macédoine du Nord", 15, 28), "ZA": ("Albanie", 15, 28),
    "YO": ("Roumanie", 20, 28), "YP": ("Roumanie", 20, 28), "YR": ("Roumanie", 20, 28),
    "LZ": ("Bulgarie", 20, 28), "SV9": ("Crète", 20, 28), "SV": ("Grèce", 20, 28), "SX": ("Grèce", 20, 28),
    "SY": ("Grèce", 20, 28), "SZ": ("Grèce", 20, 28), "J4": ("Grèce", 20, 28),
    "5B": ("Chypre", 20, 39), "C4": ("Chypre", 20, 39), "P3": ("Chypre", 20, 39),
    "TA": ("Turquie", 20, 39), "TB": ("Turquie", 20, 39), "TC": ("Turquie", 20, 39), "YM": ("Turquie", 20, 39),
    "UR": ("Ukraine", 16, 29), "US": ("Ukraine", 16, 29), "UT": ("Ukraine", 16, 29), "UX": ("Ukraine", 16, 29),
    "UY": ("Ukraine", 16, 29), "EM": ("Ukraine", 16, 29), "EN": ("Ukraine", 16, 29), "EO": ("Ukraine", 16, 29),
    "ER": ("Moldavie", 16, 29), "EU": ("Biélorussie", 16, 29), "EW": ("Biélorussie", 16, 29),
    "LY": ("Lituanie", 15, 29), "YL": ("Lettonie", 15, 29), "ES": ("Estonie", 15, 29),
    "UA2": ("Kaliningrad", 15, 29), "RA2": ("Kaliningrad", 15, 29),
    "UA9": ("Russie d'Asie", 17, 30), "UA0": ("Russie d'Asie", 19, 30), "RA9": ("Russie d'Asie", 17, 30),
    "RA0": ("Russie d'Asie", 19, 30), "R9": ("Russie d'Asie", 17, 30), "R0": ("Russie d'Asie", 19, 30),
    "UA": ("Russie", 16, 29), "RA": ("Russie", 16, 29), "R": ("Russie", 16, 29), "U": ("Russie", 16, 29),
    "4X": ("Israël", 20, 39), "4Z": ("Israël", 20, 39), "OD": ("Liban", 20, 39), "JY": ("Jordanie", 20, 39),
    "A4": ("Oman", 21, 39), "A6": ("Émirats arabes unis", 21, 39), "A7": ("Qatar", 21, 39),
    "A9": ("Bahreïn", 21, 39), "HZ": ("Arabie saoudite", 21, 39), "9K": ("Koweït", 21, 39),
    "CN": ("Maroc", 33, 37), "7X": ("Algérie", 33, 37), "3V": ("Tunisie", 33, 37), "SU": ("Égypte", 34, 38),
    "6W": ("Sénégal", 35, 46), "TU": ("Côte d'Ivoire", 35, 46), "TR": ("Gabon", 36, 52),
    "TJ": ("Cameroun", 36, 47), "5N": ("Nigeria", 35, 46), "ZS": ("Afrique du Sud", 38, 57),
    "5Z": ("Kenya", 37, 48), "5R": ("Madagascar", 39, 53), "3B8": ("Maurice", 39, 53),
    "D4": ("Cap-Vert", 35, 46), "EA8": ("Canaries", 33, 36),
    "VE": ("Canada", 5, 9), "VA": ("Canada", 5, 9), "VO1": ("Terre-Neuve (Canada)", 5, 9),
    "VO2": ("Labrador (Canada)", 2, 9), "VY": ("Canada", 1, 2), "CY": ("Canada", 5, 9), "CF": ("Canada", 5, 9),
    "XE": ("Mexique", 6, 10), "KP4": ("Porto Rico", 8, 11), "NP4": ("Porto Rico", 8, 11), "WP4": ("Porto Rico", 8, 11),
    "KH6": ("Hawaï", 31, 61), "NH6": ("Hawaï", 31, 61), "WH6": ("Hawaï", 31, 61), "AH6": ("Hawaï", 31, 61),
    "KL7": ("Alaska", 1, 1), "NL7": ("Alaska", 1, 1), "WL7": ("Alaska", 1, 1), "AL7": ("Alaska", 1, 1),
    "K": ("États-Unis", 5, 8), "N": ("États-Unis", 5, 8), "W": ("États-Unis", 5, 8), "AA": ("États-Unis", 5, 8),
    "AB": ("États-Unis", 5, 8), "AC": ("États-Unis", 5, 8), "AD": ("États-Unis", 5, 8), "AE": ("États-Unis", 5, 8),
    "AF": ("États-Unis", 5, 8), "AG": ("États-Unis", 5, 8), "AI": ("États-Unis", 5, 8), "AJ": ("États-Unis", 5, 8),
    "AK": ("États-Unis", 5, 8),
    "PY": ("Brésil", 11, 15), "PP": ("Brésil", 11, 15), "PU": ("Brésil", 11, 15), "PT": ("Brésil", 11, 15),
    "LU": ("Argentine", 13, 14), "CE": ("Chili", 12, 14), "CX": ("Uruguay", 13, 14), "OA": ("Pérou", 10, 12),
    "HK": ("Colombie", 9, 12), "YV": ("Venezuela", 9, 12), "HC": ("Équateur", 10, 12), "CO": ("Cuba", 8, 11),
    "CM": ("Cuba", 8, 11), "HI": ("République dominicaine", 8, 11), "HH": ("Haïti", 8, 11),
    "JA": ("Japon", 25, 45), "JE": ("Japon", 25, 45), "JF": ("Japon", 25, 45), "JG": ("Japon", 25, 45),
    "JH": ("Japon", 25, 45), "JI": ("Japon", 25, 45), "JJ": ("Japon", 25, 45), "JK": ("Japon", 25, 45),
    "JL": ("Japon", 25, 45), "JM": ("Japon", 25, 45), "JN": ("Japon", 25, 45), "JO": ("Japon", 25, 45),
    "JP": ("Japon", 25, 45), "JQ": ("Japon", 25, 45), "JR": ("Japon", 25, 45), "JS": ("Japon", 25, 45),
    "7J": ("Japon", 25, 45), "7K": ("Japon", 25, 45), "7L": ("Japon", 25, 45), "7M": ("Japon", 25, 45),
    "7N": ("Japon", 25, 45), "8J": ("Japon", 25, 45),
    "HL": ("Corée du Sud", 25, 44), "DS": ("Corée du Sud", 25, 44), "6K": ("Corée du Sud", 25, 44),
    "BV": ("Taïwan", 24, 44), "BY": ("Chine", 24, 44), "BG": ("Chine", 24, 44), "BH": ("Chine", 24, 44),
    "BD": ("Chine", 24, 44), "BA": ("Chine", 24, 44), "BI": ("Chine", 24, 44), "VR": ("Hong Kong", 24, 44),
    "VU": ("Inde", 22, 41), "HS": ("Thaïlande", 26, 49), "E2": ("Thaïlande", 26, 49), "9M2": ("Malaisie", 28, 54),
    "9V": ("Singapour", 28, 54), "YB": ("Indonésie", 28, 54), "YC": ("Indonésie", 28, 54),
    "YD": ("Indonésie", 28, 54), "DU": ("Philippines", 27, 50), "4X": ("Israël", 20, 39),
    "VK": ("Australie", 30, 59), "ZL": ("Nouvelle-Zélande", 32, 60), "UN": ("Kazakhstan", 17, 30),
    "4L": ("Géorgie", 21, 29), "EK": ("Arménie", 21, 29), "4K": ("Azerbaïdjan", 21, 29),
}
_PREFIXES_SORTED = sorted(PREFIXES, key=len, reverse=True)


def french_name(info):
    """Nom français d'une entité cty.dat quand on le connaît."""
    return PREFIXES.get(info["prefix"], (info["name"],))[0]


def prefix_info(call):
    """Pays, zones et position d'après le préfixe (fichier cty.dat ; gère EA8/F4ABC, F4ABC/P)."""
    from . import cty
    info = cty.lookup(call)
    if info:
        return {"country": french_name(info), "cq": str(int(info["cq"])), "itu": str(int(info["itu"])),
                "cont": info["cont"], "lat": info["lat"], "lon": info["lon"], "dxcc": info["prefix"]}
    return _prefix_info_table(call)


def _prefix_info_table(call):
    """Ancienne méthode (table intégrée), si cty.dat est absent."""
    parts = [p for p in call.upper().split("/") if p]
    if not parts:
        return None
    base = max(parts, key=len)
    for p in parts:
        if p is not base and len(p) <= 4 and p not in ("P", "M", "MM", "AM", "QRP", "A") and not p.isdigit():
            base = p
            break
    for pre in _PREFIXES_SORTED:
        if base.startswith(pre):
            c, cq, itu = PREFIXES[pre]
            return {"country": c, "cq": str(cq), "itu": str(itu)}
    return None


class LogDock(QDockWidget):
    def __init__(self, win, log):
        super().__init__("Carnet de trafic", win)
        self.win, self.ctrl, self.log = win, win.ctrl, log
        self.setObjectName("logdock")
        self.hamqth = HamQTH()
        s = win.settings
        self.hamqth.user = s.value("hamqth_user", "")
        self.hamqth.password = s.value("hamqth_pass", "")
        self.hamqth.qrz_user = s.value("qrz_user", "")
        self.hamqth.qrz_password = s.value("qrz_pass", "")
        self.hamqth.qrzcq_user = s.value("qrzcq_user", "")
        self.hamqth.qrzcq_password = s.value("qrzcq_pass", "")
        self.hamqth.result.connect(self.on_lookup)
        from .qsl import Members
        self.members = Members()
        self._qsl_via = ""
        self._lookup_timer = QTimer(self)
        self._lookup_timer.setSingleShot(True)
        self._lookup_timer.setInterval(900)
        self._lookup_timer.timeout.connect(self.auto_lookup)
        self._auto = {}                     # champ -> texte rempli automatiquement
        self._country = ""
        self.t_start = None

        w = QWidget()
        v = QVBoxLayout(w)
        hm = QHBoxLayout()
        hm.addWidget(QLabel("Je trafique en"))
        self.cb_mycall = QComboBox()
        self.cb_mycall.setEditable(True)
        self.cb_mycall.setMinimumWidth(180)
        self.cb_mycall.setToolTip("Votre indicatif pour les prochains QSO : F4JCF, F4JCF/P, FR/F4JCF/P…\n"
                                  "Tapez-en un nouveau puis Entrée pour l'ajouter à la liste.")
        self.cb_mycall.lineEdit().setPlaceholderText("mon indicatif")
        self.fill_mycalls()
        self.cb_mycall.activated.connect(lambda _i: self.win.set_active_call(self.cb_mycall.currentText()))
        self.cb_mycall.lineEdit().returnPressed.connect(lambda: self.win.set_active_call(self.cb_mycall.currentText()))
        hm.addWidget(self.cb_mycall)
        b = QPushButton("Matériel…")
        b.setToolTip("Associer un poste (FT-991A, FT-891, FT-817…) et un port à chaque indicatif")
        b.clicked.connect(lambda: self.win.stations_dialog())
        hm.addWidget(b)
        b = QPushButton("Retirer")
        b.setToolTip("Retirer cet indicatif de la liste")
        b.clicked.connect(lambda: self.win.remove_call(self.cb_mycall.currentText()))
        hm.addWidget(b)
        self.lb_mycall = QLabel("")
        self.lb_mycall.setObjectName("hint")
        hm.addWidget(self.lb_mycall, 1)
        v.addLayout(hm)
        g = QGridLayout()
        self.ed_call = QLineEdit()
        self.ed_call.setPlaceholderText("Indicatif, puis Entrée")
        self.ed_call.returnPressed.connect(self.on_call_entered)
        self.ed_call.textEdited.connect(self.on_call_edit)
        self.ed_name, self.ed_qth, self.ed_grid = QLineEdit(), QLineEdit(), QLineEdit()
        self.ed_sent, self.ed_rcvd = QLineEdit("59"), QLineEdit("59")
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(adif.LOG_MODES)
        self.cb_mode.currentTextChanged.connect(self.on_mode)
        self.ed_ref = QLineEdit()
        self.ed_myref = QLineEdit(s.value("log_myref", ""))
        self.cb_sig, self.cb_mysig = QComboBox(), QComboBox()
        for cb in (self.cb_sig, self.cb_mysig):
            cb.addItems(ACTIVITIES)
            cb.setItemText(0, "Aucune")
        self.cb_mysig.setCurrentText(s.value("log_mysig", "") or guess_activity(self.ed_myref.text()) or "Aucune")
        for cb, ed, who in ((self.cb_sig, self.ed_ref, "sa"), (self.cb_mysig, self.ed_myref, "votre")):
            cb.currentTextChanged.connect(lambda t, e=ed, w=who: self._sig_changed(t, e, w))
            self._sig_changed(cb.currentText(), ed, who)
        self.ed_comment = QLineEdit()
        self.lb_flag = QLabel()
        self.lb_flag.setFixedSize(40, 30)
        self.lb_flag.setAlignment(Qt.AlignCenter)
        call_box = QWidget()
        hc = QHBoxLayout(call_box)
        hc.setContentsMargins(0, 0, 0, 0)
        hc.setSpacing(6)
        hc.addWidget(self.lb_flag)
        hc.addWidget(self.ed_call, 1)
        self.lb_freq = QLabel("—")
        self.lb_freq.setObjectName("value")
        rst_box = QWidget()
        hr = QHBoxLayout(rst_box)
        hr.setContentsMargins(0, 0, 0, 0)
        for ed in (self.ed_sent, self.ed_rcvd):
            ed.setMaximumWidth(70)
        hr.addWidget(QLabel("envoyé"))
        hr.addWidget(self.ed_sent)
        hr.addSpacing(12)
        hr.addWidget(QLabel("reçu"))
        hr.addWidget(self.ed_rcvd)
        hr.addStretch()

        def stack(cb, ed):
            box = QWidget()
            vb = QVBoxLayout(box)
            vb.setContentsMargins(0, 0, 0, 0)
            vb.setSpacing(3)
            vb.addWidget(cb)
            vb.addWidget(ed)
            return box
        self.ed_name.setPlaceholderText("prénom et nom")
        self.ed_dept = QLineEdit()
        self.ed_dept.setPlaceholderText("stations françaises : trouvé d'après le code postal ou le locator")
        self.ed_dept.setToolTip("Numéro et nom du département (ex. 06 Alpes-Maritimes) ; enregistré dans le QSO")
        self.ed_grid.textEdited.connect(self._grid_edited)
        rows = [("Indicatif", call_box), ("Nom", self.ed_name), ("QTH", self.ed_qth),
                ("Département", self.ed_dept), ("Locator", self.ed_grid), ("Mode", self.cb_mode),
                ("RST", rst_box), ("Fréquence", self.lb_freq), ("Commentaire", self.ed_comment), ("", QWidget()),
                ("Son activité", stack(self.cb_sig, self.ed_ref)),
                ("Mon activité", stack(self.cb_mysig, self.ed_myref))]
        for i, (label, wd) in enumerate(rows):
            g.addWidget(QLabel(label), i // 2, (i % 2) * 2, Qt.AlignLeft | Qt.AlignVCenter)
            g.addWidget(wd, i // 2, (i % 2) * 2 + 1)
        v.addLayout(g)
        # --- concours ---
        from PySide6.QtWidgets import QCheckBox, QSpinBox
        ch = QHBoxLayout()
        self.ck_contest = QCheckBox("Concours")
        self.ck_contest.setToolTip("Numéros de série, contrôle des doublons du concours, export Cabrillo")
        self.ck_contest.setChecked(s.value("contest_on", "false") in (True, "true"))
        self.ck_contest.toggled.connect(self._contest_toggled)
        ch.addWidget(self.ck_contest)
        self.ed_contest = QLineEdit(s.value("contest_id", ""))
        self.ed_contest.setPlaceholderText("nom (ex. CQ-WW-CW, REF-CW)")
        self.ed_contest.setMaximumWidth(150)
        ch.addWidget(self.ed_contest)
        ch.addWidget(QLabel("N° envoyé"))
        self.sp_serial = QSpinBox()
        self.sp_serial.setRange(1, 99999)
        self.sp_serial.setValue(int(s.value("contest_serial", 1)))
        self.sp_serial.setToolTip("Numéro de série du prochain QSO ({NR} dans les messages CW)")
        ch.addWidget(self.sp_serial)
        self.ed_xsent = QLineEdit(s.value("contest_xsent", "{NR}"))
        self.ed_xsent.setToolTip("Échange envoyé : {NR} = numéro de série, ou texte fixe (département, zone…)")
        self.ed_xsent.setMaximumWidth(90)
        ch.addWidget(QLabel("Échange"))
        ch.addWidget(self.ed_xsent)
        ch.addWidget(QLabel("Reçu"))
        self.ed_xrcvd = QLineEdit()
        self.ed_xrcvd.setPlaceholderText("n° ou échange reçu")
        self.ed_xrcvd.setMaximumWidth(110)
        self.ed_xrcvd.returnPressed.connect(self.save_qso)
        ch.addWidget(self.ed_xrcvd)
        ch.addStretch()
        self.contest_row = [self.ed_contest, self.sp_serial, self.ed_xsent, self.ed_xrcvd]
        v.addLayout(ch)
        self._contest_toggled(self.ck_contest.isChecked())
        self.lb_info = QLabel("")
        self.lb_info.setObjectName("value")
        self.lb_info.setWordWrap(True)
        hi = QHBoxLayout()
        self.lb_photo = QLabel()
        self.lb_photo.setFixedSize(84, 84)
        self.lb_photo.setAlignment(Qt.AlignCenter)
        self.lb_photo.setCursor(Qt.PointingHandCursor)
        self.lb_photo.setToolTip("Photo de l'opérateur (clic pour l'agrandir)")
        self.lb_photo.mousePressEvent = lambda _e: self.show_photo()
        self.lb_photo.hide()
        self._photo = None
        self.photos = PhotoLoader()
        self.photos.loaded.connect(self._on_photo)
        hi.addWidget(self.lb_photo)
        hi.addWidget(self.lb_info, 1)
        from .worldmap import WorldMap
        self.minimap = WorldMap()
        self.minimap.greyline = False
        self.minimap.setFixedSize(420, 210)
        self.minimap.setToolTip("Position du correspondant et trajet depuis votre locator (molette : zoom)")
        self.minimap.hide()
        hi.addWidget(self.minimap)
        b = QPushButton("QRZ.com")
        b.setToolTip("Ouvrir la fiche de l'indicatif sur QRZ.com")
        b.clicked.connect(lambda: self.open_web("https://www.qrz.com/db/{}"))
        hi.addWidget(b)
        b = QPushButton("HamQTH")
        b.setToolTip("Ouvrir la fiche de l'indicatif sur HamQTH.com")
        b.clicked.connect(lambda: self.open_web("https://www.hamqth.com/{}"))
        hi.addWidget(b)
        b = QPushButton("QRZCQ")
        b.setToolTip("Ouvrir la fiche de l'indicatif sur QRZCQ.com")
        b.clicked.connect(lambda: self.open_web("https://www.qrzcq.com/call/{}"))
        hi.addWidget(b)
        v.addLayout(hi)
        h = QHBoxLayout()
        b = QPushButton("Enregistrer le QSO")
        b.setToolTip("Raccourci : Entrée dans le champ Commentaire, ou Ctrl+L")
        b.clicked.connect(self.save_qso)
        self.ed_comment.returnPressed.connect(self.save_qso)
        h.addWidget(b)
        b = QPushButton("Effacer")
        b.clicked.connect(self.clear_form)
        h.addWidget(b)
        from PySide6.QtWidgets import QCheckBox
        self.b_qrec = QPushButton("● Enregistrer le son")
        self.b_qrec.setCheckable(True)
        self.b_qrec.setToolTip("Enregistre le son reçu pendant le QSO ; le fichier est rattaché au QSO à son "
                               "enregistrement (♪ dans la liste). Nécessite la chute d'eau (entrée audio du poste).")
        self.b_qrec.toggled.connect(self.toggle_qso_rec)
        h.addWidget(self.b_qrec)
        self.ck_autorec = QCheckBox("auto")
        self.ck_autorec.setToolTip("Démarrer l'enregistrement dès qu'on tape un indicatif")
        self.ck_autorec.setChecked(s.value("log_autorec", "false") in (True, "true"))
        h.addWidget(self.ck_autorec)
        v.addLayout(h)
        self._rec_path = None

        h = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Rechercher un indicatif dans le carnet")
        self.ed_search.textChanged.connect(self.refresh)
        h.addWidget(self.ed_search, 1)
        self.lb_count = QLabel("")
        self.lb_count.setObjectName("hint")
        h.addWidget(self.lb_count)
        v.addLayout(h)
        self.tbl = QTableWidget(0, len(TABLE_COLS))
        self.tbl.setHorizontalHeaderLabels(TABLE_COLS)
        for c in (C_EQSL, C_LOTW):
            self.tbl.horizontalHeaderItem(c).setToolTip("✔ confirmé · ↑ envoyé, en attente de confirmation")
        self.tbl.horizontalHeaderItem(C_QSL).setToolTip("Carte QSL papier : ✔ reçue · ↑ envoyée · ✉ à envoyer")
        self.tbl.horizontalHeaderItem(C_AUDIO).setToolTip("♪ enregistrement du QSO : clic pour l'écouter")
        self.tbl.setToolTip("Double-clic : modifier ou supprimer · clic droit : cartes QSL, étiquettes")
        self.tbl.cellDoubleClicked.connect(self.edit_row)
        self.tbl.cellClicked.connect(self._cell_clicked)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self.table_menu)
        self.tbl.verticalHeader().setVisible(False)
        from PySide6.QtCore import QSize
        self.tbl.setIconSize(QSize(24, 18))
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.tbl, 1)
        h = QHBoxLayout()
        for label, slot in (("Supprimer", self.delete_selected), ("Importer ADIF", self.import_adif),
                            ("Exporter ADIF", self.export_adif), ("Exporter une activation", self.export_activation),
                            ("Envoi en ligne…", lambda: self.win.upload_dialog()),
                            ("Confirmations eQSL / LoTW", lambda: self.win.qsl_sync_now()),
                            ("Diplômes…", lambda: self.win.awards_dialog())):
            b = QPushButton(label)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.setWidget(w)
        self.setMinimumWidth(520)
        self.log.changed.connect(self.refresh)
        self.ctrl.state_changed.connect(self.on_state)
        self._last = None
        self.refresh()

    # --- formulaire --------------------------------------------------------------------
    def on_state(self, st):
        self._last = st
        if self.isVisible():
            self.lb_freq.setText(f"{st.freq / 1e6:.4f} MHz".replace(".", ","))

    def suggest_mode(self, rig_mode, freq):
        if rig_mode in ("USB", "LSB"):
            return "SSB"
        if rig_mode in ("CW", "CWR"):
            return "CW"
        if rig_mode in ("RTTY", "RTTYR"):
            return "RTTY"
        if rig_mode in ("PKTUSB", "PKTLSB"):
            return "FT4" if any(abs(freq - f) < 3000 for f in
                                (7047500, 10140000, 14080000, 18104000, 21140000, 28180000)) else "FT8"
        return {"AM": "AM", "FM": "FM", "PKTFM": "FM", "C4FM": "C4FM"}.get(rig_mode, "SSB")

    def on_call_edit(self, txt):
        if self.t_start is None and txt.strip():
            self.t_start = datetime.datetime.now(datetime.timezone.utc)
            if self._last:
                self.cb_mode.setCurrentText(self.suggest_mode(self._last.mode, self._last.freq))
        self.ed_call.setText(txt.upper())
        for ed, val in list(self._auto.items()):   # l'indicatif change : on retire l'ancienne fiche
            if ed.text() == val:
                ed.clear()
        self._auto.clear()
        self._qsl_via = ""
        self._photo = None
        self.lb_photo.hide()
        self.minimap.hide()
        self.update_flag(txt.strip())
        if txt.strip() and self.ck_autorec.isChecked() and not self.b_qrec.isChecked() and \
                getattr(self.win, "wf", None) is not None and self.win.wf.running:
            self.b_qrec.setChecked(True)
        prev = self.log.worked(txt.strip()) if len(txt.strip()) >= 3 else []
        dupe = self.contest_dupe(txt.strip())
        if dupe:
            self.lb_info.setText(f"DOUBLON : déjà contacté dans ce concours ({dupe})")
            self.lb_info.setStyleSheet("color: #ff5a4a; font-weight: bold;")
            self._lookup_timer.start()
            return
        self.lb_info.setStyleSheet("")
        head = self._country + " — " if self._country and len(txt.strip()) >= 2 else ""
        if prev:
            bands = sorted({f"{r['band']} {r['mode']}" for r in prev})
            conf = sum(1 for r in prev if "Y" in ((r.get("eqsl_qsl_rcvd") or "") + (r.get("lotw_qsl_rcvd") or "")).upper())
            self.lb_info.setText(head + f"Déjà contacté {len(prev)} fois : " + ", ".join(bands[:8])
                                 + (f" ({conf} confirmé{'s' if conf > 1 else ''})" if conf else ""))
        else:
            self.lb_info.setText(head + ("Nouvel indicatif" if len(txt.strip()) >= 3 else ""))
        self._lookup_timer.start()

    def fill_mycalls(self):
        s = self.win.settings
        cur = (s.value("mycall", "") or "").upper()
        calls = my_calls(s)
        self.cb_mycall.blockSignals(True)
        self.cb_mycall.clear()
        self.cb_mycall.addItems(calls)
        self.cb_mycall.setCurrentText(cur)
        self.cb_mycall.blockSignals(False)
        if hasattr(self, "lb_mycall"):
            self.lb_mycall.setText(describe_mycall(cur))

    def _sig_changed(self, text, ed, who):
        on = text not in ("", "Aucune")
        ed.setEnabled(on)
        ed.setPlaceholderText(f"{who} référence {text} : {ACTIVITY_HINT.get(text, '')}".replace(" : ex.", ", ex.")
                              if on else "choisissez d'abord l'activité")

    def update_dept(self, call, info=None):
        """Département d'une station française (code postal, position de la fiche, ou locator)."""
        from .departements import for_station
        info = info or {}
        code, dname = for_station(call, info.get("zip", ""), info.get("lat"), info.get("lon"),
                                  self.ed_grid.text().strip() or info.get("grid", ""))
        txt = f"{code} {dname}" if code else ""
        if txt and (not self.ed_dept.text() or self.ed_dept.text() == self._auto.get(self.ed_dept)):
            self.ed_dept.setText(txt)
            self._auto[self.ed_dept] = txt
        return code, dname

    def _grid_edited(self, _t):
        call = self.ed_call.text().strip().upper()
        if len(self.ed_grid.text().strip()) >= 4 and call:
            self.update_dept(call)
            self.update_minimap(call, {})

    def update_minimap(self, call, info):
        """Petite carte : le correspondant et le trajet (orthodromie) depuis la station."""
        from .geo import distance_bearing, from_locator
        pos = None
        grid = self.ed_grid.text().strip() or info.get("grid", "")
        if grid:
            try:
                pos = from_locator(grid[:6])
            except ValueError:
                pos = None
        if not pos:
            try:
                la, lo = float(info.get("lat") or 0), float(info.get("lon") or 0)
                pos = (la, lo) if (la or lo) else None
            except ValueError:
                pos = None
        if not pos:
            from . import cty
            e = cty.lookup(call)
            pos = (e["lat"], e["lon"]) if e else None
        if not pos:
            self.minimap.hide()
            return
        st = getattr(self.win, "station", None)
        m = self.minimap
        m.set_station(st)
        from . import departements as DEP
        code = (self.ed_dept.text().split() or [""])[0].upper()
        shapes = []
        if code in DEP._load():
            shapes.append({"rings": DEP.rings(), "pen": "#40ffffff", "width": 0.5})
            shapes.append({"rings": DEP.rings(code), "pen": "#ffb300", "width": 1.2, "fill": "#40ffb300"})
        m.shapes = shapes
        tip = call
        if st:
            d, b = distance_bearing(*st, *pos)
            tip += f" — {d:.0f} km, cap {b:.0f}°"
        m.set_layer("qso", [{"lat": pos[0], "lon": pos[1], "label": call, "tip": tip, "color": "#ffb300",
                             "size": 5, "line": True}])
        if st:
            dlat, dlon = abs(st[0] - pos[0]), abs(st[1] - pos[1])
            if dlon > 180:
                dlon = 360 - dlon
            if max(dlat, dlon) > 70:
                m.show_world()
            else:
                span = max(dlat * 2.2, dlon / 1.6 * 2.2, 1.5)
                clat, clon = (st[0] + pos[0]) / 2, (st[1] + pos[1]) / 2
                if abs(st[1] - pos[1]) > 180:
                    clon = ((st[1] + pos[1]) / 2 + 180) % 360 - 180
                m.show_region(clat, clon, span)
        else:
            m.show_region(pos[0], pos[1], 8)
        m.show()

    def update_flag(self, call):
        from .qsl import country_of, flag_pixmap
        iso, name = country_of(call) if len(call) >= 1 else (None, "")
        self._country = name
        pm = flag_pixmap(iso) if iso else None
        if pm:
            self.lb_flag.setPixmap(pm.scaled(40, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lb_flag.clear()
        self.lb_flag.setToolTip(name)

    # --- concours ----------------------------------------------------------------------------
    def _contest_toggled(self, on):
        for w in self.contest_row:
            w.setEnabled(on)

    def contest_on(self):
        return self.ck_contest.isChecked() and bool(self.ed_contest.text().strip())

    def sent_exchange(self):
        return self.ed_xsent.text().replace("{NR}", f"{self.sp_serial.value():03d}").strip()

    def contest_dupe(self, call):
        """Même indicatif, même bande et même mode dans ce concours."""
        if not self.contest_on() or len(call) < 3:
            return ""
        band = band_of_mhz(self._last.freq / 1e6) if self._last and self._last.freq else ""
        mode = adif.ADIF_MODES.get(self.cb_mode.currentText(), (self.cb_mode.currentText(), ""))[0]
        for r in self.log.query("call = ? AND contest_id = ?", (call.upper(), self.ed_contest.text().strip().upper())):
            if r["band"] == band and r["mode"] == mode:
                return f"{r['band']} {r['submode'] or r['mode']} à {(r['time_on'] or '')[:4]}"
        return ""

    def auto_lookup(self):
        call = self.ed_call.text().strip().upper()
        if re.match(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}\d[A-Z]{1,4}(/[A-Z0-9]{1,4})?$", call):
            self.hamqth.lookup(call)

    def open_web(self, url):
        call = self.ed_call.text().strip().upper()
        if call:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(url.format(urllib.parse.quote(call.split("/")[0] if len(
                call.split("/")[0]) >= 3 else call))))

    def on_call_entered(self):
        call = self.ed_call.text().strip().upper()
        if call:
            self._lookup_timer.stop()
            self.hamqth.lookup(call)
            self.ed_name.setFocus()

    def on_lookup(self, call, info):
        if call != self.ed_call.text().strip().upper():
            return
        if isinstance(info, str):
            self.lb_info.setText(info)
            return
        for ed, key in ((self.ed_name, "name"), (self.ed_qth, "qth"), (self.ed_grid, "grid")):
            if info.get(key) and (not ed.text() or ed.text() == self._auto.get(ed)):
                ed.setText(info[key])
                self._auto[ed] = info[key]
        extra = " — ".join(x for x in (info.get("qth"), self._country or info.get("country")) if x)
        zones = " ".join(x for x in ((f"CQ {info['cq']}" if info.get("cq") else ""),
                                     (f"ITU {info['itu']}" if info.get("itu") else "")) if x)
        if zones:
            extra += f" ({zones})"
        pos = getattr(self.win, "station", None)
        if pos and info.get("grid"):
            from .geo import distance_bearing, from_locator
            try:
                d, b = distance_bearing(*pos, *from_locator(info["grid"][:6]))
                extra += f" — {d:.0f} km, cap {b:.0f}°"
            except ValueError:
                pass
        code, dname = self.update_dept(call, info)
        if dname:
            extra = f"{dname} ({code})" + (" — " + extra if extra else "")
        self.update_minimap(call, info)
        txt = f"{call} : {extra}" if extra else f"{call} trouvé"
        if info.get("photo"):
            self.photos.get(call, info["photo"])
        qsl = []
        if info.get("qsl_via"):
            self._qsl_via = info["qsl_via"].upper()
            qsl.append(f"QSL via {self._qsl_via}")
        mem = self.members.describe(call)
        if mem:
            qsl.append(mem)
        else:
            if info.get("lotw"):
                qsl.append("LoTW ✓")
            if info.get("eqsl"):
                qsl.append("eQSL ✓")
        if qsl:
            txt += "\n" + " · ".join(qsl)
        if info.get("sources"):
            txt += f"  [{info['sources']}]"
        if info.get("hint"):
            txt += f"\n{info['hint']}"
        self.lb_info.setText(txt)
        if info.get("grid"):
            self.win.point_rotor_to_grid(info["grid"][:6])

    def on_mode(self, mode):
        self.ed_sent.setText(adif.default_rst(mode))
        self.ed_rcvd.setText(adif.default_rst(mode))

    def prefill(self, call, ref="", mode=None):
        """Appelé depuis un spot : prépare le QSO."""
        self.clear_form()
        self.ed_call.setText(call.upper())
        self.on_call_edit(call)
        if ref:
            self.cb_sig.setCurrentText(guess_activity(ref))
            self.ed_ref.setText(ref)
        if mode:
            self.cb_mode.setCurrentText(mode)

    def clear_form(self):
        self._auto.clear()
        self._lookup_timer.stop()
        self.minimap.hide()
        for ed in (self.ed_call, self.ed_name, self.ed_qth, self.ed_grid, self.ed_ref, self.ed_comment, self.ed_dept):
            ed.clear()
        self.cb_sig.setCurrentIndex(0)
        self.lb_info.clear()
        self.lb_flag.clear()
        self.lb_photo.hide()
        self._photo = None
        self._country = self._qsl_via = ""
        self._finish_rec(None, None)
        self.t_start = None
        self.on_mode(self.cb_mode.currentText())
        self.ed_call.setFocus()

    def save_qso(self):
        call = self.ed_call.text().strip().upper()
        if not call:
            self.lb_info.setText("Indicatif manquant")
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        t = self.t_start or now
        st = self._last
        mode, sub = adif.ADIF_MODES.get(self.cb_mode.currentText(), (self.cb_mode.currentText(), ""))
        ref, myref = self.ed_ref.text().strip().upper(), self.ed_myref.text().strip().upper()
        sig = lambda cb, r: (cb.currentText() if cb.currentIndex() > 0 else guess_activity(r)).upper()
        rec = {"call": call, "qso_date": t.strftime("%Y%m%d"), "time_on": t.strftime("%H%M%S"),
               "freq": f"{st.freq / 1e6:.6f}" if st and st.freq else "", "mode": mode, "submode": sub,
               "rst_sent": self.ed_sent.text(), "rst_rcvd": self.ed_rcvd.text(),
               "name": self.ed_name.text(), "qth": self.ed_qth.text(), "gridsquare": self.ed_grid.text(),
               "comment": self.ed_comment.text(), "qsl_via": self._qsl_via, "country": self._country,
               "state": (self.ed_dept.text().split() or [""])[0].upper(),
               "tx_pwr": str(st.p.get("pwr", "")) if st else "",
               "station_callsign": self.win.settings.value("mycall", "").upper(),
               "my_gridsquare": self.win.b_loc.text().split()[0] if getattr(self.win, "station", None) else ""}
        if ref and self.cb_sig.currentIndex() > 0:
            rec["sig"], rec["sig_info"] = sig(self.cb_sig, ref), ref
        if myref and self.cb_mysig.currentIndex() > 0:
            rec["my_sig"], rec["my_sig_info"] = sig(self.cb_mysig, myref), myref
        if self.contest_on():
            rcvd = self.ed_xrcvd.text().strip().upper()
            rec.update({"contest_id": self.ed_contest.text().strip().upper(), "stx": str(self.sp_serial.value()),
                        "stx_string": self.sent_exchange(), "srx_string": rcvd,
                        "srx": rcvd if rcvd.isdigit() else ""})
            self.sp_serial.setValue(self.sp_serial.value() + 1)
            self.ed_xrcvd.clear()
        if self.win.settings.value("qsl_default_r", "false") in (True, "true"):
            rec["qsl_sent"] = "R"
        qid = self.log.add(rec)
        self._finish_rec(qid, rec)
        self.win.statusBar().showMessage(f"QSO avec {call} enregistré")
        self.clear_form()

    # --- tableau -----------------------------------------------------------------------------
    def refresh(self):
        from .qsl import country_of, flag_icon
        q = self.ed_search.text().strip().upper()
        rows = self.log.query("call LIKE ?", (f"%{q}%",), limit=500) if q else self.log.query(limit=300)
        self.rows = rows
        self.tbl.setUpdatesEnabled(False)
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            d = r["qso_date"] or ""
            iso, country = country_of(r["call"])
            try:
                fq = f"{float(r['freq']):.4f}".replace(".", ",") if r["freq"] else ""
            except ValueError:
                fq = r["freq"]
            ref = " ".join(x for x in ((r["sig"] or "") + " " + (r["sig_info"] or ""),
                                       ("moi : " + (r["my_sig"] or "") + " " + r["my_sig_info"]) if r["my_sig_info"] else "")
                           if x.strip())
            vals = [f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else d, (r["time_on"] or "")[:4],
                    r["call"], r["name"], country, r.get("state") or "", fq, r["band"], r["submode"] or r["mode"], r["rst_sent"],
                    r["rst_rcvd"], "", "", "", "♪" if r.get("audio_file") else "", ref.strip()]
            for c, val in enumerate(vals):
                self.tbl.setItem(i, c, QTableWidgetItem(val or ""))
            ic = flag_icon(iso)
            if ic:
                self.tbl.item(i, C_PAYS).setIcon(ic)
            self.tbl.item(i, C_FREQ).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it = self.tbl.item(i, C_QSL)
            it.setTextAlignment(Qt.AlignCenter)
            qs, qr = (r.get("qsl_sent") or "").upper(), (r.get("qsl_rcvd") or "").upper()
            via = {"B": "par le bureau", "D": "en direct", "M": "par le manager"}.get((r.get("qsl_sent_via") or "").upper(), "")
            fmt = lambda x: f"{x[6:8]}/{x[4:6]}/{x[:4]}" if x and len(x) == 8 else ""
            if qr == "Y":
                it.setText("✔")
                it.setForeground(QColor("#4caf50"))
                it.setToolTip(f"Carte reçue {fmt(r.get('qslrdate'))}".strip()
                              + (f" · envoyée {via} {fmt(r.get('qslsdate'))}".rstrip() if qs == "Y" else ""))
            elif qs == "Y":
                it.setText("↑")
                it.setForeground(QColor("#9e9e9e"))
                it.setToolTip(f"Carte envoyée {via} {fmt(r.get('qslsdate'))}".strip())
            elif qs in ("R", "Q"):
                it.setText("✉")
                it.setForeground(QColor("#ffb300"))
                it.setToolTip("Carte à envoyer (étiquette à imprimer)")
            self.tbl.item(i, C_AUDIO).setTextAlignment(Qt.AlignCenter)
            for c, svc in ((C_EQSL, "eqsl"), (C_LOTW, "lotw")):
                it = self.tbl.item(i, c)
                it.setTextAlignment(Qt.AlignCenter)
                rd = r.get(f"{svc}_qslrdate") or ""
                if (r.get(f"{svc}_qsl_rcvd") or "").upper() == "Y":
                    it.setText("✔")
                    it.setForeground(QColor("#4caf50"))
                    it.setToolTip("Confirmé" + (f" le {rd[6:8]}/{rd[4:6]}/{rd[:4]}" if len(rd) == 8 else ""))
                elif (r.get(f"up_{svc}") or "") not in ("", "ancien", "import"):
                    it.setText("↑")
                    it.setForeground(QColor("#9e9e9e"))
                    it.setToolTip("Envoyé, pas encore confirmé")
        self.tbl.resizeColumnsToContents()
        self.tbl.setUpdatesEnabled(True)
        cc = self.log.confirmed_counts()
        self.lb_count.setText(f"{self.log.count()} QSO · confirmés : eQSL {cc['eqsl']}, LoTW {cc['lotw']}")

    # --- cartes QSL papier, étiquettes, enregistrements ----------------------------------------
    def selected_records(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()})
        return [self.rows[r] for r in rows if 0 <= r < len(self.rows)]

    def table_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        recs = self.selected_records()
        if not recs:
            return
        n = len(recs)
        m = QMenu(self)
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        acts = [
            (f"Carte à envoyer ({n} QSO) — pour les étiquettes", {"qsl_sent": "R"}),
            (f"Carte envoyée par le bureau ({n})", {"qsl_sent": "Y", "qsl_sent_via": "B", "qslsdate": today}),
            (f"Carte envoyée en direct ({n})", {"qsl_sent": "Y", "qsl_sent_via": "D", "qslsdate": today}),
            (f"Carte reçue ({n})", {"qsl_rcvd": "Y", "qslrdate": today}),
            ("Effacer l'état des cartes papier", {"qsl_sent": "", "qsl_rcvd": "", "qsl_sent_via": "", "qslsdate": "",
                                                   "qslrdate": ""}),
        ]
        for label, rec in acts:
            a = m.addAction(label)
            a.triggered.connect(lambda _c=False, rc=rec: self.mark_qsl(recs, rc))
        m.addSeparator()
        a = m.addAction(f"Imprimer les étiquettes QSL de la sélection ({n})…")
        a.triggered.connect(lambda: self.win.qsl_labels(recs))
        a = m.addAction("Imprimer les étiquettes de toutes les cartes à envoyer…")
        a.triggered.connect(lambda: self.win.qsl_labels(None))
        m.addSeparator()
        if n == 1:
            a = m.addAction("Modifier ce QSO…")
            a.triggered.connect(lambda: QsoEditDialog(self, recs[0]).exec())
            if recs[0].get("audio_file"):
                a = m.addAction("Écouter l'enregistrement")
                a.triggered.connect(lambda: self.play_audio(recs[0]))
        a = m.addAction(f"Supprimer ({n})…")
        a.triggered.connect(self.delete_selected)
        m.exec(self.tbl.viewport().mapToGlobal(pos))

    def mark_qsl(self, recs, rec):
        for r in recs:
            self.log.update(r["id"], rec, notify=False)
        self.log.changed.emit()

    def _cell_clicked(self, row, col):
        if col == C_AUDIO and 0 <= row < len(self.rows) and self.rows[row].get("audio_file"):
            self.play_audio(self.rows[row])

    def play_audio(self, r):
        path = r.get("audio_file") or ""
        if not os.path.exists(path):
            QMessageBox.information(self, "Enregistrement", f"Fichier introuvable :\n{path}")
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @staticmethod
    def rec_dir():
        d = os.path.join(data_dir(), "enregistrements", "QSO")
        os.makedirs(d, exist_ok=True)
        return d

    def toggle_qso_rec(self, on):
        wf = getattr(self.win, "wf", None)
        if on:
            if wf is None:
                return
            if not wf.running:
                self.win.b_wf.setChecked(True)
            if not wf.running:
                self.b_qrec.blockSignals(True)
                self.b_qrec.setChecked(False)
                self.b_qrec.blockSignals(False)
                self.lb_info.setText("Enregistrement impossible : lancez d'abord la chute d'eau (entrée audio du poste)")
                return
            path = os.path.join(self.rec_dir(), f"en_cours_{datetime.datetime.now():%Y%m%d_%H%M%S}.wav")
            try:
                wf.start_recording(path)
            except Exception as e:
                self.lb_info.setText(f"Enregistrement impossible : {e}")
                return
            self._rec_path = path
            self.b_qrec.setText("■ Arrêter le son")
            self.win._uncheck(self.win.b_rec)
        else:
            if wf and self._rec_path and wf.rec_path == self._rec_path:
                wf.stop_recording()
            self.b_qrec.setText("● Enregistrer le son")

    def _finish_rec(self, qid, rec):
        """Fin de QSO : le fichier en cours est renommé et rattaché au QSO."""
        if not self._rec_path:
            return
        self.b_qrec.setChecked(False)
        src, self._rec_path = self._rec_path, None
        if qid is None:
            try:
                os.remove(src)
            except OSError:
                pass
            return
        name = f"{rec['call'].replace('/', '-')}_{rec['qso_date']}_{rec['time_on'][:4]}.wav"
        dst = os.path.join(os.path.dirname(src), name)
        try:
            os.replace(src, dst)
        except OSError:
            dst = src
        self.log.update(qid, {"audio_file": dst})

    def show_photo(self):
        if not self._photo:
            return
        d = QDialog(self)
        d.setWindowTitle(self.ed_call.text().strip().upper() or "Photo")
        lv = QVBoxLayout(d)
        lb = QLabel()
        pm = self._photo
        if pm.width() > 640 or pm.height() > 640:
            pm = pm.scaled(640, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lb.setPixmap(pm)
        lv.addWidget(lb)
        d.exec()

    def _on_photo(self, call, data):
        if call != self.ed_call.text().strip().upper() or not data:
            return
        from PySide6.QtGui import QPixmap
        pm = QPixmap()
        if not pm.loadFromData(data) or pm.isNull():
            return
        self._photo = pm
        self.lb_photo.setPixmap(pm.scaled(84, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.lb_photo.show()

    def edit_row(self, row, _col=0):
        if 0 <= row < len(self.rows):
            QsoEditDialog(self, self.rows[row]).exec()

    def delete_selected(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()})
        if not rows:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer {len(rows)} QSO du carnet ?") != QMessageBox.Yes:
            return
        for r in rows:
            self.log.delete(self.rows[r]["id"])

    def import_adif(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer un fichier ADIF", "", "ADIF (*.adi *.adif)")
        if not path:
            return
        with open(path, encoding="utf-8", errors="replace") as f:
            recs = adif.parse(f.read())
        n = dup = 0
        new_ids = []
        for r in recs:
            if not r.get("call"):
                continue
            if not r.get("band"):
                r["band"] = band_of_mhz(r.get("freq"))
            if self.log.is_dupe(r):
                dup += 1
                continue
            new_ids.append(self.log.add(r, notify=False))
            n += 1
        if new_ids and QMessageBox.question(
                self, "Import ADIF", f"{n} QSO importés. Faut-il aussi les envoyer aux carnets en ligne "
                "(QRZ.com, eQSL, Club Log, LoTW) lors du prochain envoi ?\n\n"
                "Répondez Non s'ils y sont déjà.") != QMessageBox.Yes:
            self.log.mark_all_uploaded(new_ids)
        self.log.changed.emit()
        QMessageBox.information(self, "Import ADIF", f"{n} QSO importés, {dup} doublons ignorés.")

    def _save_adif(self, rows, default):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en ADIF", os.path.join(data_dir(), default),
                                              "ADIF (*.adi)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(adif.write(self.log.export_records(rows), "CAT Pilot", __version__))
        self.win.statusBar().showMessage(f"{len(rows)} QSO exportés dans {path}")

    def export_adif(self):
        self._save_adif(self.log.query(), "carnet_catpilot.adi")

    def export_activation(self):
        """Export au format attendu par POTA/SOTA : une référence, une date."""
        myref = self.ed_myref.text().strip().upper()
        if not myref:
            QMessageBox.information(self, "Activation", "Choisissez votre activité et indiquez votre référence "
                                    "dans « Mon activité ».")
            return
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        rows = self.log.query("my_sig_info = ? AND qso_date = ?", (myref, today))
        if not rows:
            QMessageBox.information(self, "Activation", f"Aucun QSO aujourd'hui (UTC) depuis {myref}.")
            return
        call = (self.win.settings.value("mycall", "") or "INDICATIF").upper().replace("/", "-")
        self._save_adif(rows, f"{call}@{myref.replace('/', '-')}-{today}.adi")

    def save_settings(self, s):
        s.setValue("log_myref", self.ed_myref.text())
        s.setValue("log_autorec", self.ck_autorec.isChecked())
        s.setValue("log_mysig", self.cb_mysig.currentText() if self.cb_mysig.currentIndex() > 0 else "")
        s.setValue("contest_on", self.ck_contest.isChecked())
        s.setValue("contest_id", self.ed_contest.text())
        s.setValue("contest_serial", self.sp_serial.value())
        s.setValue("contest_xsent", self.ed_xsent.text())

    def export_cabrillo(self):
        """Fichier Cabrillo (format des concours) pour le concours choisi."""
        from PySide6.QtWidgets import QInputDialog
        with self.log.lock:
            ids = [r[0] for r in self.log.db.execute(
                "SELECT DISTINCT contest_id FROM qso WHERE contest_id IS NOT NULL AND contest_id != ''")]
        if not ids:
            QMessageBox.information(self, "Cabrillo", "Aucun QSO de concours dans le carnet (cochez « Concours »).")
            return
        cid, ok = QInputDialog.getItem(self, "Cabrillo", "Concours :", ids, 0, False)
        if not ok:
            return
        rows = sorted(self.log.query("contest_id = ?", (cid,)),
                      key=lambda r: (r["qso_date"] or "", r["time_on"] or "", r["id"]))
        me = (self.win.settings.value("mycall", "") or "").upper()
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en Cabrillo", os.path.join(data_dir(), f"{cid}_{me}.log"),
                                              "Cabrillo (*.log *.cbr)")
        if not path:
            return
        cab_mode = {"CW": "CW", "SSB": "PH", "FM": "FM", "AM": "PH", "RTTY": "RY"}
        out = ["START-OF-LOG: 3.0", f"CONTEST: {cid}", f"CALLSIGN: {me}", "CATEGORY-OPERATOR: SINGLE-OP",
               "CATEGORY-TRANSMITTER: ONE", f"CREATED-BY: CAT Pilot {__version__}"]
        st = getattr(self.win, "station", None)
        if st:
            out.append(f"GRID-LOCATOR: {self.win.b_loc.text().split()[0]}")
        for r in rows:
            try:
                khz = f"{float(r['freq']) * 1000:.0f}" if r["freq"] else "0"
            except ValueError:
                khz = "0"
            d = r["qso_date"] or ""
            mo = cab_mode.get(r["mode"], "DG")
            sent = f"{r['rst_sent'] or ''} {r['stx_string'] or r['stx'] or ''}".strip()
            rcvd = f"{r['rst_rcvd'] or ''} {r['srx_string'] or r['srx'] or ''}".strip()
            out.append(f"QSO: {khz:>5} {mo} {d[:4]}-{d[4:6]}-{d[6:8]} {(r['time_on'] or '')[:4]} "
                       f"{me:<13} {sent:<10} {r['call']:<13} {rcvd}")
        out.append("END-OF-LOG:")
        with open(path, "w", encoding="ascii", errors="replace") as f:
            f.write("\n".join(out) + "\n")
        self.win.statusBar().showMessage(f"{len(rows)} QSO exportés en Cabrillo dans {path}")


class HamQTHDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("Réglages du carnet")
        f = QFormLayout(self)
        s = win.settings
        self.ed_call = QLineEdit(s.value("mycall", ""))
        self.ed_user = QLineEdit(s.value("hamqth_user", ""))
        self.ed_pass = QLineEdit(s.value("hamqth_pass", ""))
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_qrz_user = QLineEdit(s.value("qrz_user", ""))
        self.ed_qrz_pass = QLineEdit(s.value("qrz_pass", ""))
        self.ed_qrz_pass.setEchoMode(QLineEdit.Password)
        f.addRow("Mon indicatif", self.ed_call)
        f.addRow("Compte QRZ.com", self.ed_qrz_user)
        f.addRow("Mot de passe QRZ.com", self.ed_qrz_pass)
        f.addRow("Compte HamQTH", self.ed_user)
        f.addRow("Mot de passe HamQTH", self.ed_pass)
        self.ed_qrzcq_user = QLineEdit(s.value("qrzcq_user", ""))
        self.ed_qrzcq_pass = QLineEdit(s.value("qrzcq_pass", ""))
        self.ed_qrzcq_pass.setEchoMode(QLineEdit.Password)
        f.addRow("Compte QRZCQ (indicatif)", self.ed_qrzcq_user)
        f.addRow("Mot de passe QRZCQ", self.ed_qrzcq_pass)
        t = QLabel("Tous les comptes sont facultatifs. HamQTH.com et QRZCQ.com sont gratuits et donnent nom, QTH, "
                   "locator et manager QSL (QRZCQ peut réserver certaines fiches à ses abonnés). "
                   "QRZ.com donne la fiche complète avec un abonnement XML, et seulement une partie sans. "
                   "Sans compte, CAT Pilot trouve quand même le pays et les zones, et les indicatifs "
                   "américains via callook.info. Les mots de passe sont enregistrés sur ce PC.")
        t.setObjectName("hint")
        t.setWordWrap(True)
        f.addRow(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


class QsoEditDialog(QDialog):
    """Modification (ou suppression) d'un QSO du carnet."""

    def __init__(self, dock, rec):
        super().__init__(dock)
        self.dock, self.log, self.rec = dock, dock.log, rec
        self.setWindowTitle(f"QSO avec {rec['call']}")
        self.resize(560, 0)
        v = QVBoxLayout(self)
        f = QFormLayout()
        d, t = rec.get("qso_date") or "", (rec.get("time_on") or "") + "000000"
        self.ed = {}

        def line(key, label, value, hint=""):
            e = QLineEdit(value or "")
            if hint:
                e.setPlaceholderText(hint)
            f.addRow(label, e)
            self.ed[key] = e
            return e
        line("call", "Indicatif", rec.get("call"))
        line("date", "Date (UTC)", f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else d, "jj/mm/aaaa")
        line("time", "Heure (UTC)", f"{t[:2]}:{t[2:4]}", "hh:mm")
        try:
            fq = f"{float(rec['freq']):.6f}".rstrip("0").rstrip(".") if rec.get("freq") else ""
        except ValueError:
            fq = rec.get("freq") or ""
        line("freq", "Fréquence (MHz)", fq.replace(".", ","), "ex. 7,127")
        self.cb_mode = QComboBox()
        self.cb_mode.setEditable(True)
        self.cb_mode.addItems(adif.LOG_MODES)
        self.cb_mode.setCurrentText(rec.get("submode") or rec.get("mode") or "")
        f.addRow("Mode", self.cb_mode)
        line("rst_sent", "RST envoyé", rec.get("rst_sent"))
        line("rst_rcvd", "RST reçu", rec.get("rst_rcvd"))
        line("name", "Nom", rec.get("name"), "prénom et nom")
        line("qth", "QTH", rec.get("qth"))
        line("gridsquare", "Locator", rec.get("gridsquare"))
        line("state", "Département", rec.get("state"), "numéro, ex. 06")
        self.cb_sig, self.cb_mysig = QComboBox(), QComboBox()
        for cb, key in ((self.cb_sig, "sig"), (self.cb_mysig, "my_sig")):
            cb.setEditable(True)
            cb.addItems(ACTIVITIES)
            cb.setCurrentText((rec.get(key) or "").upper())
        f.addRow("Son activité", self.cb_sig)
        line("sig_info", "Sa référence", rec.get("sig_info"))
        f.addRow("Mon activité", self.cb_mysig)
        line("my_sig_info", "Ma référence", rec.get("my_sig_info"))
        line("qsl_via", "QSL via", rec.get("qsl_via"))
        line("comment", "Commentaire", rec.get("comment"))
        self.cb_qs = QComboBox()
        for label, val in (("non envoyée", ""), ("à envoyer", "R"), ("envoyée par le bureau", "Y/B"),
                           ("envoyée en direct", "Y/D"), ("envoyée par le manager", "Y/M")):
            self.cb_qs.addItem(label, val)
        cur = (rec.get("qsl_sent") or "").upper()
        cur = f"Y/{(rec.get('qsl_sent_via') or 'B').upper()}" if cur == "Y" else ("R" if cur in ("R", "Q") else "")
        self.cb_qs.setCurrentIndex(max(0, self.cb_qs.findData(cur)))
        self.cb_qr = QComboBox()
        self.cb_qr.addItems(["non reçue", "reçue"])
        self.cb_qr.setCurrentIndex(1 if (rec.get("qsl_rcvd") or "").upper() == "Y" else 0)
        hq = QHBoxLayout()
        hq.addWidget(self.cb_qs)
        hq.addWidget(self.cb_qr)
        f.addRow("Carte QSL papier", hq)
        v.addLayout(f)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        h = QHBoxLayout()
        b = QPushButton("Supprimer ce QSO")
        b.clicked.connect(self.remove)
        h.addWidget(b)
        if rec.get("audio_file"):
            b = QPushButton("♪ Écouter")
            b.clicked.connect(lambda: dock.play_audio(rec))
            h.addWidget(b)
        h.addStretch()
        b = QPushButton("Annuler")
        b.clicked.connect(self.reject)
        h.addWidget(b)
        b = QPushButton("Enregistrer")
        b.setDefault(True)
        b.clicked.connect(self.save)
        h.addWidget(b)
        v.addLayout(h)

    def save(self):
        g = lambda k: self.ed[k].text().strip()
        try:
            dt = datetime.datetime.strptime(g("date") + " " + g("time"), "%d/%m/%Y %H:%M")
        except ValueError:
            self.lb.setText("Date ou heure invalide : jj/mm/aaaa et hh:mm")
            return
        call = g("call").upper()
        if not call:
            self.lb.setText("Indicatif manquant")
            return
        freq = g("freq").replace(",", ".")
        if freq:
            try:
                freq = f"{float(freq):.6f}"
            except ValueError:
                self.lb.setText("Fréquence invalide")
                return
        mode, sub = adif.ADIF_MODES.get(self.cb_mode.currentText(), (self.cb_mode.currentText().upper(), ""))
        sec = (self.rec.get("time_on") or "000000")[4:6] if dt.strftime("%H%M") == (self.rec.get("time_on") or "")[:4] else "00"
        rec = {"call": call, "qso_date": dt.strftime("%Y%m%d"), "time_on": dt.strftime("%H%M") + (sec or "00"),
               "freq": freq, "band": band_of_mhz(freq) if freq else self.rec.get("band", ""),
               "mode": mode, "submode": sub,
               "sig": self.cb_sig.currentText().strip().upper() if g("sig_info") else "",
               "my_sig": self.cb_mysig.currentText().strip().upper() if g("my_sig_info") else ""}
        for k in ("rst_sent", "rst_rcvd", "name", "qth", "gridsquare", "sig_info", "my_sig_info", "qsl_via", "comment",
                  "state"):
            rec[k] = g(k).upper() if k in ("gridsquare", "sig_info", "my_sig_info", "qsl_via") and k != "gridsquare" else g(k)
        if rec["gridsquare"]:
            gs = rec["gridsquare"]
            rec["gridsquare"] = gs[:2].upper() + gs[2:4] + gs[4:].lower()
        from .qsl import country_of
        rec["country"] = country_of(call)[1]
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        qs = self.cb_qs.currentData()
        old_sent = (self.rec.get("qsl_sent") or "").upper()
        if qs.startswith("Y/"):
            rec["qsl_sent"], rec["qsl_sent_via"] = "Y", qs[2]
            rec["qslsdate"] = self.rec.get("qslsdate") if old_sent == "Y" and self.rec.get("qslsdate") else today
        else:
            rec["qsl_sent"], rec["qsl_sent_via"], rec["qslsdate"] = qs, "", ""
        if self.cb_qr.currentIndex() == 1:
            rec["qsl_rcvd"] = "Y"
            rec["qslrdate"] = self.rec.get("qslrdate") or today
        else:
            rec["qsl_rcvd"], rec["qslrdate"] = "", ""
        self.log.update(self.rec["id"], rec)
        self.dock.win.statusBar().showMessage(f"QSO avec {call} modifié")
        self.accept()

    def remove(self):
        if QMessageBox.question(self, "Supprimer", f"Supprimer le QSO avec {self.rec['call']} du carnet ?") \
                == QMessageBox.Yes:
            self.log.delete(self.rec["id"])
            self.accept()
