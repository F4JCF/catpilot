"""Lecture et écriture ADIF, et correspondances de modes."""
import re

TAG = re.compile(r"<([A-Za-z0-9_]+):(\d+)(?::[A-Za-z])?>", re.S)

# Mode du carnet -> (MODE, SUBMODE) ADIF
ADIF_MODES = {
    "SSB": ("SSB", ""), "CW": ("CW", ""), "FM": ("FM", ""), "AM": ("AM", ""),
    "FT8": ("FT8", ""), "FT4": ("MFSK", "FT4"), "JS8": ("MFSK", "JS8"), "RTTY": ("RTTY", ""),
    "PSK31": ("PSK", "PSK31"), "SSTV": ("SSTV", ""), "OLIVIA": ("OLIVIA", ""),
    "C4FM": ("DIGITALVOICE", "C4FM"), "DSTAR": ("DSTAR", ""), "Q65": ("MFSK", "Q65"),
    "JT65": ("JT65", ""), "MSK144": ("MSK144", ""), "FST4": ("MFSK", "FST4"),
}
LOG_MODES = list(ADIF_MODES)


def from_adif_mode(mode, submode=""):
    mode, submode = (mode or "").upper(), (submode or "").upper()
    for k, (m, sm) in ADIF_MODES.items():
        if m == mode and (sm == submode or (not sm and not submode)):
            return k
    return submode or mode or "SSB"


def default_rst(log_mode):
    if log_mode in ("SSB", "FM", "AM", "C4FM", "DSTAR"):
        return "59"
    if log_mode in ("CW", "RTTY", "PSK31", "OLIVIA"):
        return "599"
    return "-10"


EOR = re.compile(r"<eor>", re.I)


def parse(text):
    """Renvoie la liste des enregistrements (dict, clés en minuscules) d'un texte ADIF."""
    eoh = re.search(r"<eoh>", text, re.I)
    pos = eoh.end() if eoh else 0
    records, cur = [], {}
    while True:
        m = TAG.search(text, pos)
        e = EOR.search(text, pos)
        if e and (not m or e.start() < m.start()):
            if cur:
                records.append(cur)
            cur, pos = {}, e.end()
            continue
        if not m:
            break
        n = int(m.group(2))
        cur[m.group(1).lower()] = text[m.end():m.end() + n]
        pos = m.end() + n
    if cur:
        records.append(cur)
    return records


def field(name, value):
    value = "" if value is None else str(value)
    if not value:
        return ""
    return f"<{name.upper()}:{len(value)}>{value} "


def write(records, program="CAT Pilot", version=""):
    out = [f"Export ADIF par {program} {version}\n", field("ADIF_VER", "3.1.4"),
           field("PROGRAMID", program), field("PROGRAMVERSION", version), "<EOH>\n"]
    for r in records:
        out.append("".join(field(k, v) for k, v in r.items()) + "<EOR>\n")
    return "".join(out)
