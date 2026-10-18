"""Drapeaux des pays, listes des membres LoTW / eQSL, et relevé des confirmations (QSL reçues)
sur eQSL.cc et LoTW.

- Drapeaux : images de flag-icons (licence MIT, assets/flags), pays DXCC -> code pays dans
  assets/dxcc_fr.json (avec le nom français).
- Membres : la liste d'activité LoTW (date du dernier envoi de chaque indicatif) et la liste
  des membres eQSL « AG », téléchargées une fois par semaine dans Documents/CATPilot.
- Confirmations : la boîte de réception eQSL et les QSL LoTW sont téléchargées en ADIF, puis
  rapprochées des QSO du carnet (même indicatif, même bande, à 30 minutes près).
"""
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

from . import __version__, adif, cty
from .logbook import data_dir

UA = {"User-Agent": f"CATPilot/{__version__}"}


def _assets():
    return os.path.join(getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), "..")), "assets")


_DXCC = None


def dxcc_table():
    global _DXCC
    if _DXCC is None:
        try:
            with open(os.path.join(_assets(), "dxcc_fr.json"), encoding="utf-8") as f:
                _DXCC = json.load(f)
        except (OSError, ValueError):
            _DXCC = {}
    return _DXCC


def country_of(call):
    """(code du drapeau, nom français du pays) d'après l'indicatif, ou (None, "")."""
    info = cty.lookup(call or "")
    if not info:
        return None, ""
    iso, name = dxcc_table().get(info["prefix"], ("", info["name"]))
    return iso or None, name or info["name"]


def flag_path(iso):
    if not iso:
        return ""
    p = os.path.join(_assets(), "flags", f"{iso}.png")
    return p if os.path.exists(p) else ""


_ICONS = {}


def flag_pixmap(iso):
    from PySide6.QtGui import QPixmap
    if iso not in _ICONS:
        p = flag_path(iso)
        _ICONS[iso] = QPixmap(p) if p else None
    return _ICONS[iso]


def flag_icon(iso):
    from PySide6.QtGui import QIcon
    pm = flag_pixmap(iso) if iso else None
    return QIcon(pm) if pm else None


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# --- membres LoTW / eQSL ---------------------------------------------------------------------
class Members:
    LOTW_URL = "https://lotw.arrl.org/lotw-user-activity.csv"
    EQSL_URL = "https://www.eqsl.cc/qslcard/DownloadedFiles/AGMemberList.txt"
    MAX_AGE = 7 * 86400

    def __init__(self):
        self.lotw = {}           # indicatif -> date du dernier envoi (AAAA-MM-JJ)
        self.eqsl = set()
        self.ready = False
        threading.Thread(target=self._load, daemon=True).start()

    @staticmethod
    def _path(name):
        return os.path.join(data_dir(), name)

    def _fetch(self, url, name):
        path = self._path(name)
        try:
            fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < self.MAX_AGE
        except OSError:
            fresh = False
        if not fresh:
            try:
                data = _get(url, timeout=120)
                if len(data) > 1000:
                    with open(path + ".tmp", "wb") as f:
                        f.write(data)
                    os.replace(path + ".tmp", path)
            except Exception:
                pass             # hors ligne : on garde l'ancienne liste
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def _load(self):
        txt = self._fetch(self.LOTW_URL, "lotw_membres.csv")
        lotw = {}
        for line in txt.splitlines():
            p = line.split(",")
            if len(p) >= 2 and p[0]:
                lotw[p[0].strip().upper()] = p[1].strip()
        txt = self._fetch(self.EQSL_URL, "eqsl_membres_ag.txt")
        eq = {ln.strip().upper() for ln in txt.splitlines()
              if ln.strip() and " " not in ln.strip() and any(c.isdigit() for c in ln)}
        self.lotw, self.eqsl, self.ready = lotw, eq, True

    def describe(self, call):
        """Texte court : utilisateur LoTW (et date du dernier envoi), membre eQSL AG."""
        call = (call or "").upper()
        keys = [call] + [p for p in call.split("/") if len(p) >= 3]
        out = []
        d = next((self.lotw[k] for k in keys if k in self.lotw), None)
        if d:
            try:
                dt = datetime.date.fromisoformat(d)
                age = (datetime.date.today() - dt).days
                out.append(f"LoTW ✓ (dernier envoi {dt:%d/%m/%Y})" if age < 365 else
                           f"LoTW (inactif depuis {dt:%m/%Y})")
            except ValueError:
                out.append("LoTW ✓")
        if any(k in self.eqsl for k in keys):
            out.append("eQSL AG ✓")
        return " · ".join(out)


# --- relevé des confirmations ---------------------------------------------------------------
def _ts(date, time_on):
    try:
        return datetime.datetime.strptime((date or "") + ((time_on or "") + "0000")[:4], "%Y%m%d%H%M")
    except ValueError:
        return None


class ConfirmSync(QObject):
    progress = Signal(str)
    finished = Signal(str)            # résumé

    def __init__(self, log, settings):
        super().__init__()
        self.log, self.s = log, settings
        self.busy = False

    def configured(self):
        v = lambda k: (self.s.value(k, "") or "").strip()
        return {"eqsl": bool(v("eqsl_user") and v("eqsl_pass")),
                "lotw": bool(v("lotw_user") and v("lotw_pass"))}

    def run(self):
        if self.busy or not any(self.configured().values()):
            return False
        self.busy = True
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def auto(self):
        """Une fois par jour, au démarrage, si l'option est cochée."""
        if self.s.value("qsl_auto", "true") not in (True, "true"):
            return
        if self.s.value("qsl_last_run", "") == datetime.date.today().isoformat():
            return
        self.run()

    def _run(self):
        parts = []
        try:
            cfg = self.configured()
            if cfg["eqsl"]:
                try:
                    parts.append(self._eqsl())
                except Exception as e:
                    parts.append(f"eQSL : {e}")
            if cfg["lotw"]:
                try:
                    parts.append(self._lotw())
                except Exception as e:
                    parts.append(f"LoTW : {e}")
            self.s.setValue("qsl_last_run", datetime.date.today().isoformat())
        finally:
            self.busy = False
            self.log.changed.emit()
            self.finished.emit(" · ".join(parts))

    def _match(self, recs, svc):
        """Marque les QSO du carnet confirmés par ces enregistrements. Renvoie (nouveaux, introuvables)."""
        col, dcol = f"{svc}_qsl_rcvd", f"{svc}_qslrdate"
        new = miss = 0
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        for r in recs:
            if svc == "lotw" and (r.get("qsl_rcvd") or "").upper() != "Y":
                continue
            call = (r.get("call") or "").upper()
            t = _ts(r.get("qso_date"), r.get("time_on"))
            if not call or not t:
                continue
            band = (r.get("band") or "").lower()
            day = lambda dt: dt.strftime("%Y%m%d")
            cands = self.log.query("call = ? AND qso_date IN (?, ?, ?)",
                                   (call, day(t - datetime.timedelta(days=1)), day(t), day(t + datetime.timedelta(days=1))))
            best = None
            for c in cands:
                t2 = _ts(c["qso_date"], c["time_on"])
                if not t2 or abs((t - t2).total_seconds()) > 1800:
                    continue
                if band and c.get("band") and c["band"].lower() != band:
                    continue
                if best is None or abs((t - t2).total_seconds()) < abs((t - _ts(best["qso_date"], best["time_on"])).total_seconds()):
                    best = c
            if not best:
                miss += 1
                continue
            if (best.get(col) or "").upper() == "Y":
                continue
            rdate = (r.get("qslrdate") or r.get("eqsl_qslrdate") or today).replace("-", "")[:8]
            with self.log.lock:
                self.log.db.execute(f"UPDATE qso SET {col} = 'Y', {dcol} = ? WHERE id = ?", (rdate, best["id"]))
                self.log.db.commit()
            new += 1
        return new, miss

    def _eqsl(self):
        self.progress.emit("eQSL : téléchargement de la boîte de réception…")
        params = {"UserName": self.s.value("eqsl_user", "").strip(), "Password": self.s.value("eqsl_pass", "")}
        since = self.s.value("eqsl_rcvd_since", "")
        if since:
            params["RcvdSince"] = since
        nick = (self.s.value("eqsl_nick", "") or "").strip()
        if nick:
            params["QTHNickname"] = nick
        started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        page = _get("https://www.eqsl.cc/qslcard/DownloadInBox.cfm?" + urllib.parse.urlencode(params),
                    timeout=120).decode("utf-8", "replace")
        m = re.search(r'HREF="([^"]+\.adi)"', page, re.I)
        if not m:
            if re.search(r"no (log entries|records)|you have no", page, re.I):
                self.s.setValue("eqsl_rcvd_since", started.strftime("%Y%m%d%H%M"))
                return "eQSL : aucune nouvelle eQSL"
            txt = re.sub(r"<[^>]+>", " ", page)
            txt = re.sub(r"\s+", " ", txt).strip()
            err = re.search(r"(error|erreur)[^.]*", txt, re.I)
            raise RuntimeError((err.group(0) if err else txt[:150]) or "réponse inattendue")
        url = urllib.parse.urljoin("https://www.eqsl.cc/qslcard/DownloadInBox.cfm", m.group(1))
        recs = adif.parse(_get(url, timeout=120).decode("utf-8", "replace"))
        new, miss = self._match(recs, "eqsl")
        self.s.setValue("eqsl_rcvd_since", started.strftime("%Y%m%d%H%M"))
        return f"eQSL : {new} nouvelle{'s' if new > 1 else ''} confirmation{'s' if new > 1 else ''}" + \
               (f" ({miss} sans QSO correspondant)" if miss else "")

    def _lotw(self):
        self.progress.emit("LoTW : téléchargement des QSL (peut prendre une minute)…")
        params = {"login": self.s.value("lotw_user", "").strip(), "password": self.s.value("lotw_pass", ""),
                  "qso_query": "1", "qso_qsl": "yes", "qso_qsldetail": "yes",
                  "qso_qslsince": self.s.value("lotw_qsl_since", "") or "1900-01-01"}
        try:
            txt = _get("https://lotw.arrl.org/lotwuser/lotwreport.adi?" + urllib.parse.urlencode(params),
                       timeout=300).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"refusé (code {e.code})")
        if "<eoh>" not in txt.lower():
            plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt)).strip()
            raise RuntimeError("identifiant ou mot de passe refusé" if re.search(r"password|login", plain, re.I)
                               else (plain[:150] or "réponse inattendue"))
        recs = adif.parse(txt)
        new, miss = self._match(recs, "lotw")
        m = re.search(r"<APP_LoTW_LASTQSL:\d+>([^<]+)", txt, re.I)
        if m:
            self.s.setValue("lotw_qsl_since", m.group(1).strip())
        return f"LoTW : {new} nouvelle{'s' if new > 1 else ''} confirmation{'s' if new > 1 else ''}" + \
               (f" ({miss} sans QSO correspondant)" if miss else "")
