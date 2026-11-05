import urllib.request, urllib.parse, xml.etree.ElementTree as ET, re, os, subprocess, tempfile, datetime
from . import adif

UA = {"User-Agent": "JCFLog/1.0"}


def get(url, data=None, timeout=20):
    if data is not None and not isinstance(data, bytes):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def _strip_ns(xml):
    return re.sub(r'\sxmlns="[^"]+"', "", xml, count=1)


class Callbook:
    def __init__(self):
        self.sess = {}

    def lookup(self, call, cfg):
        for svc in (cfg.get("cb_primary", "HamQTH"), cfg.get("cb_secondary", "")):
            try:
                r = self.hamqth(call, cfg) if svc == "HamQTH" else self.qrz(call, cfg) if svc == "QRZ.com" else None
                if r:
                    return r
            except Exception:
                self.sess.pop(svc, None)
        return None

    def hamqth(self, call, cfg):
        u, p = cfg.get("hamqth_user"), cfg.get("hamqth_pass")
        if not u:
            return None
        if "HamQTH" not in self.sess:
            x = ET.fromstring(_strip_ns(get("https://www.hamqth.com/xml.php?" + urllib.parse.urlencode({"u": u, "p": p}))))
            self.sess["HamQTH"] = x.findtext(".//session_id")
        x = ET.fromstring(_strip_ns(get("https://www.hamqth.com/xml.php?" + urllib.parse.urlencode(
            {"id": self.sess["HamQTH"], "callsign": call, "prg": "JCFLog"}))))
        s = x.find(".//search")
        if s is None:
            if x.findtext(".//error", "").lower().startswith("session"):
                self.sess.pop("HamQTH", None)
            return None
        t = lambda k: s.findtext(k) or ""
        return dict(name=t("nick") or t("adr_name"), qth=t("qth") or t("adr_city"), gridsquare=t("grid").upper(),
                    email=t("email"), web=t("web"), qsl_via=t("qsl_via"), iota=t("iota"), state=t("us_state"),
                    cnty=t("us_county"), ituz=t("itu"), cqz=t("cq"), src="HamQTH",
                    age=str(datetime.date.today().year - int(t("birth_year"))) if t("birth_year").isdigit() else "")

    def qrz(self, call, cfg):
        u, p = cfg.get("qrz_user"), cfg.get("qrz_pass")
        if not u:
            return None
        base = "https://xmldata.qrz.com/xml/current/?"
        if "QRZ.com" not in self.sess:
            x = ET.fromstring(_strip_ns(get(base + urllib.parse.urlencode({"username": u, "password": p, "agent": "JCFLog"}))))
            self.sess["QRZ.com"] = x.findtext(".//Key")
        x = ET.fromstring(_strip_ns(get(base + urllib.parse.urlencode({"s": self.sess["QRZ.com"], "callsign": call}))))
        s = x.find(".//Callsign")
        if s is None:
            if "Session" in (x.findtext(".//Error") or ""):
                self.sess.pop("QRZ.com", None)
            return None
        t = lambda k: s.findtext(k) or ""
        return dict(name=(t("fname") + " " + t("name")).strip(), qth=t("addr2"), gridsquare=t("grid").upper(),
                    email=t("email"), web=t("url"), qsl_via=t("qslmgr"), iota=t("iota"), state=t("state"),
                    cnty=t("county"), ituz=t("ituzone"), cqz=t("cqzone"), src="QRZ.com",
                    age=str(datetime.date.today().year - int(t("born"))) if t("born").isdigit() else "")


def solar():
    x = ET.fromstring(get("https://www.hamqsl.com/solarxml.php"))
    return {k: (x.findtext(".//" + k) or "").strip() for k in ("solarflux", "aindex", "kindex")}


# ---------- QSL services ----------
def eqsl_upload(qsos, cfg):
    hdr = adif._f("eqsl_user", cfg["eqsl_user"]) + adif._f("eqsl_pswd", cfg["eqsl_pass"]) + "<EOH>\n"
    body = hdr + "\n".join(adif.record(q) for q in qsos)
    r = get("https://www.eqsl.cc/qslcard/ImportADIF.cfm", {"ADIFData": body}, 120)
    return "Result:" in r or "added" in r.lower(), re.sub(r"<[^>]+>", " ", r)[:400]


def eqsl_download(cfg, since="19000101"):
    r = get("https://www.eqsl.cc/qslcard/DownloadInBox.cfm?" + urllib.parse.urlencode(
        {"UserName": cfg["eqsl_user"], "Password": cfg["eqsl_pass"], "RcvdSince": since}), timeout=120)
    m = re.search(r'href="\.\./(downloadedfiles/[^"]+\.adi)"', r, re.I)
    if not m:
        raise RuntimeError(re.sub(r"<[^>]+>", " ", r)[:300])
    return adif.parse(get("https://www.eqsl.cc/" + m.group(1), timeout=120))


def lotw_download(cfg, since="1900-01-01"):
    r = get("https://lotw.arrl.org/lotwuser/lotwreport.adi?" + urllib.parse.urlencode(
        {"login": cfg["lotw_user"], "password": cfg["lotw_pass"], "qso_query": 1, "qso_qsl": "yes",
         "qso_qslsince": since, "qso_qsldetail": "yes"}), timeout=180)
    if "<eoh>" not in r.lower():
        raise RuntimeError("Identifiants LoTW refusés")
    return adif.parse(r)


def lotw_upload(qsos, cfg):
    tqsl = cfg.get("tqsl_path") or r"C:\Program Files (x86)\TrustedQSL\tqsl.exe"
    fd, path = tempfile.mkstemp(suffix=".adi")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(adif.export(qsos))
    args = [tqsl, "-q", "-d", "-u", "-a", "compliant", "-x"]
    if cfg.get("tqsl_location"):
        args += ["-l", cfg["tqsl_location"]]
    p = subprocess.run(args + [path], capture_output=True, text=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.returncode in (0, 9), (p.stdout + p.stderr)[-400:]


def qrz_upload(q, cfg):
    r = get("https://logbook.qrz.com/api", {"KEY": cfg["qrz_api_key"], "ACTION": "INSERT", "ADIF": adif.record(q)})
    return "RESULT=OK" in r or "REPLACE" in r, r


def clublog_upload(q, cfg):
    r = get("https://clublog.org/realtime.php", {"email": cfg["clublog_email"], "password": cfg["clublog_pass"],
                                                 "callsign": cfg.get("clublog_call") or q.get("station_callsign", ""),
                                                 "api": cfg["clublog_api"], "adif": adif.record(q)})
    return "OK" in r or "Dupe" in r, r


def match_confirmations(db, recs, field):
    n = 0
    for r in recs:
        rows = db.query("call=? AND qso_date=? AND band=?", (r.get("call"), r.get("qso_date"), r.get("band", "").lower()))
        for q in rows:
            if q.get(field) != "Y":
                db.update(q["id"], {field: "Y"})
                n += 1
    return n
