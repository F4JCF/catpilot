"""Envoi des QSO vers les carnets en ligne : QRZ.com, eQSL, Club Log et LoTW (par TQSL).

Chaque QSO garde la date d'envoi par service (colonnes up_qrz, up_eqsl, up_clublog,
up_lotw de la base) : on n'envoie que ce qui ne l'a pas encore été.
"""
import datetime
import os
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

from . import __version__, adif

SERVICES = {"qrz": "QRZ.com", "eqsl": "eQSL", "clublog": "Club Log", "lotw": "LoTW"}
TQSL_PATHS = [r"C:\Program Files (x86)\TrustedQSL\tqsl.exe", r"C:\Program Files\TrustedQSL\tqsl.exe"]
UA = {"User-Agent": f"CATPilot/{__version__}"}


def find_tqsl(path=""):
    import shutil
    for p in [path] + TQSL_PATHS + ["/usr/bin/tqsl", "/usr/local/bin/tqsl"]:
        if p and os.path.exists(p):
            return p
    return shutil.which("tqsl") or ""


def _post(url, data, timeout=30):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _one(rec):
    return "".join(adif.field(k, v) for k, v in rec.items()) + "<EOR>"


class Uploader(QObject):
    progress = Signal(str)                 # message d'avancement
    finished = Signal(str, int, int)       # service, envoyés, erreurs

    def __init__(self, log, settings):
        super().__init__()
        self.log, self.s = log, settings
        self.busy = set()

    def configured(self, svc):
        v = lambda k: (self.s.value(k, "") or "").strip()
        return {"qrz": bool(v("qrz_logkey")),
                "eqsl": bool(v("eqsl_user") and v("eqsl_pass")),
                "clublog": bool(v("clublog_email") and v("clublog_pass") and v("clublog_api")),
                "lotw": bool(find_tqsl(v("tqsl_path")) and v("tqsl_location"))}[svc]

    def auto(self, svc):
        return self.s.value(f"auto_{svc}", "false") in (True, "true") and self.configured(svc)

    def send(self, svc, ids=None):
        """Envoie les QSO en attente (ou ceux de la liste ids) dans un fil séparé."""
        if svc in self.busy:
            return
        self.busy.add(svc)
        threading.Thread(target=self._run, args=(svc, ids), daemon=True).start()

    def _run(self, svc, ids):
        ok = err = 0
        try:
            rows = self.log.pending(svc, ids)
            if not rows:
                return
            name = SERVICES[svc]
            if svc == "lotw":
                ok, err = self._lotw(rows)
            else:
                for i, r in enumerate(rows):
                    self.progress.emit(f"{name} : envoi {i + 1}/{len(rows)} ({r['call']})")
                    try:
                        good, msg = getattr(self, "_" + svc)(r)
                    except Exception as e:
                        good, msg = False, str(e)
                    if good:
                        self.log.mark_uploaded(r["id"], svc)
                        ok += 1
                    else:
                        err += 1
                        self.progress.emit(f"{name} : {r['call']} refusé — {msg}")
                        if err >= 3 and ok == 0:
                            break          # identifiants faux, inutile d'insister
        finally:
            self.busy.discard(svc)
            self.finished.emit(svc, ok, err)
            self.log.changed.emit()

    def _rec(self, r):
        from .logbook import QSL_FIELDS
        return {k: r.get(k) for k in self.log.fields if r.get(k) and k not in QSL_FIELDS}

    # --- services ------------------------------------------------------------------------
    def _qrz(self, r):
        code, txt = _post("https://logbook.qrz.com/api",
                          {"KEY": self.s.value("qrz_logkey", "").strip(), "ACTION": "INSERT",
                           "ADIF": _one(self._rec(r))})
        res = dict(urllib.parse.parse_qsl(txt))
        if res.get("RESULT") == "OK" or "duplicate" in res.get("REASON", "").lower():
            return True, ""
        return False, res.get("REASON") or txt[:120]

    def _eqsl(self, r):
        doc = adif.field("ADIF_VER", "3.1.4") + adif.field("PROGRAMID", "CATPilot") + "<EOH>" + _one(self._rec(r))
        code, txt = _post("https://www.eqsl.cc/qslcard/importADIF.cfm",
                          {"ADIFData": doc, "EQSL_USER": self.s.value("eqsl_user", "").strip(),
                           "EQSL_PSWD": self.s.value("eqsl_pass", "")})
        low = txt.lower()
        if "result: 1 out of 1 records added" in low or "duplicate" in low:
            return True, ""
        import re
        m = re.search(r"(error|warning)[^<]*", txt, re.I)
        return False, (m.group(0) if m else txt[:120]).strip()

    def _clublog(self, r):
        code, txt = _post("https://clublog.org/realtime.php",
                          {"email": self.s.value("clublog_email", "").strip(),
                           "password": self.s.value("clublog_pass", ""),
                           "callsign": (r.get("station_callsign") or self.s.value("mycall", "")).upper(),
                           "adif": _one(self._rec(r)), "api": self.s.value("clublog_api", "").strip()})
        if code == 200 or "dupe" in txt.lower():
            return True, ""
        return False, f"{code} {txt[:120]}"

    def _lotw(self, rows):
        """LoTW : TQSL signe et envoie un fichier ADIF (certificat installé par l'utilisateur)."""
        tqsl = find_tqsl(self.s.value("tqsl_path", ""))
        loc = self.s.value("tqsl_location", "").strip()
        self.progress.emit(f"LoTW : signature de {len(rows)} QSO par TQSL…")
        fd, path = tempfile.mkstemp(suffix=".adi", prefix="catpilot_lotw_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(adif.write([self._rec(r) for r in rows], "CAT Pilot", __version__))
        try:
            flags = 0x08000000 if os.name == "nt" else 0          # pas de fenêtre console
            p = subprocess.run([tqsl, "-q", "-d", "-u", "-a", "compliant", "-l", loc, "-x", path],
                               capture_output=True, text=True, timeout=600, creationflags=flags)
            code = p.returncode
        except Exception as e:
            self.progress.emit(f"LoTW : TQSL n'a pas pu être lancé — {e}")
            return 0, len(rows)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        # codes de TQSL : 0 envoyé, 8 rien de nouveau (doublons), 9 en partie doublons
        if code in (0, 8, 9):
            for r in rows:
                self.log.mark_uploaded(r["id"], "lotw")
            return len(rows), 0
        msgs = {1: "annulé", 2: "refusé par LoTW", 3: "réponse inattendue de LoTW", 4: "erreur de TQSL",
                5: "certificat ou lieu de station introuvable", 6: "erreur de fichier",
                7: "LoTW injoignable", 10: "certificat expiré"}
        self.progress.emit(f"LoTW : échec ({msgs.get(code, f'code {code}')})")
        return 0, len(rows)


def today_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
