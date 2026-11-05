import re, datetime
from .db import FIELDS

_tag = re.compile(r"<(\w+)(?::(\d+)(?::\w)?)?>", re.I)


def parse(text):
    eoh = re.search(r"<eoh>", text, re.I)
    if eoh:
        text = text[eoh.end():]
    out, cur, pos = [], {}, 0
    while True:
        m = _tag.search(text, pos)
        if not m:
            break
        name = m.group(1).lower()
        if name == "eor":
            if cur:
                out.append(cur)
            cur, pos = {}, m.end()
            continue
        n = int(m.group(2) or 0)
        cur[name] = text[m.end():m.end() + n]
        pos = m.end() + n
    for q in out:
        q["call"] = q.get("call", "").upper()
        if "mode" in q:
            q["mode"] = q["mode"].upper()
        if "band" in q:
            q["band"] = q["band"].lower()
        if q.get("time_on") and len(q["time_on"]) == 4:
            q["time_on"] += "00"
    return out


def _f(k, v):
    v = str(v)
    return f"<{k.upper()}:{len(v.encode('utf-8'))}>{v} "


def export(qsos):
    s = ["JCFLog ADIF export\n", _f("adif_ver", "3.1.4"), _f("programid", "JCFLog"),
         _f("created_timestamp", datetime.datetime.utcnow().strftime("%Y%m%d %H%M%S")), "<EOH>\n"]
    for q in qsos:
        s.append("".join(_f(k, q[k]) for k in FIELDS if q.get(k)) + "<EOR>\n")
    return "".join(s)


def record(q):
    return "".join(_f(k, q[k]) for k in FIELDS if q.get(k)) + "<EOR>"
