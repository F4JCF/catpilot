import sqlite3, os, json

FIELDS = ["call", "qso_date", "time_on", "time_off", "freq", "band", "mode", "submode",
          "rst_sent", "rst_rcvd", "name", "qth", "gridsquare", "comment", "country", "dxcc",
          "cont", "cqz", "ituz", "state", "cnty", "iota", "pota_ref", "sota_ref", "wwff_ref",
          "sig", "sig_info", "dok", "vucc_grids", "age", "email", "web", "qsl_via",
          "qsl_sent", "qsl_rcvd", "lotw_qsl_sent", "lotw_qsl_rcvd", "eqsl_qsl_sent",
          "eqsl_qsl_rcvd", "clublog_qso_upload_status", "qrzcom_qso_upload_status",
          "prop_mode", "tx_pwr", "station_callsign", "operator", "my_gridsquare",
          "distance", "notes", "contest_id", "srx", "stx", "my_rig", "my_antenna"]


def appdir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(base, "JCFLog")
    os.makedirs(d, exist_ok=True)
    return d


class DB:
    def __init__(self, path=None):
        self.path = path or os.path.join(appdir(), "jcflog.db")
        self.c = sqlite3.connect(self.path)
        self.c.row_factory = sqlite3.Row
        cols = ",".join(f"{f} TEXT" for f in FIELDS)
        self.c.execute(f"CREATE TABLE IF NOT EXISTS qso (id INTEGER PRIMARY KEY AUTOINCREMENT,{cols})")
        existing = {r[1] for r in self.c.execute("PRAGMA table_info(qso)")}
        for f in FIELDS:
            if f not in existing:
                self.c.execute(f"ALTER TABLE qso ADD COLUMN {f} TEXT")
        self.c.execute("CREATE INDEX IF NOT EXISTS i_call ON qso(call)")
        self.c.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
        self.c.commit()

    def get(self, k, default=None):
        r = self.c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, k, v):
        self.c.execute("REPLACE INTO settings VALUES (?,?)", (k, json.dumps(v)))
        self.c.commit()

    def add(self, q):
        q = {k: v for k, v in q.items() if k in FIELDS and v not in (None, "")}
        if not q:
            return None
        cur = self.c.execute(f"INSERT INTO qso ({','.join(q)}) VALUES ({','.join('?' * len(q))})",
                             [str(v) for v in q.values()])
        self.c.commit()
        return cur.lastrowid

    def add_many(self, qsos, skip_dupes=True):
        n = 0
        for q in qsos:
            if skip_dupes and self.c.execute(
                    "SELECT 1 FROM qso WHERE call=? AND qso_date=? AND substr(time_on,1,4)=? AND band=? AND mode=?",
                    (q.get("call"), q.get("qso_date"), (q.get("time_on") or "")[:4], q.get("band"), q.get("mode"))).fetchone():
                continue
            q = {k: v for k, v in q.items() if k in FIELDS and v not in (None, "")}
            if q:
                self.c.execute(f"INSERT INTO qso ({','.join(q)}) VALUES ({','.join('?' * len(q))})", list(q.values()))
                n += 1
        self.c.commit()
        return n

    def update(self, qid, q):
        q = {k: v for k, v in q.items() if k in FIELDS}
        if q:
            self.c.execute(f"UPDATE qso SET {','.join(k + '=?' for k in q)} WHERE id=?", list(q.values()) + [qid])
            self.c.commit()

    def delete(self, ids):
        self.c.executemany("DELETE FROM qso WHERE id=?", [(i,) for i in ids])
        self.c.commit()

    def query(self, where="1", args=(), order="qso_date DESC, time_on DESC", limit=None):
        sql = f"SELECT * FROM qso WHERE {where} ORDER BY {order}" + (f" LIMIT {int(limit)}" if limit else "")
        return [dict(r) for r in self.c.execute(sql, args)]

    def one(self, qid):
        r = self.c.execute("SELECT * FROM qso WHERE id=?", (qid,)).fetchone()
        return dict(r) if r else None

    def distinct(self, col):
        return [r[0] for r in self.c.execute(f"SELECT DISTINCT {col} FROM qso WHERE {col} IS NOT NULL AND {col}<>'' ORDER BY 1")]

    def worked(self, call=None, dxcc=None, band=None, mode=None):
        w, a = [], []
        for col, val in (("call", call), ("dxcc", dxcc), ("band", band), ("mode", mode)):
            if val:
                w.append(f"{col}=?")
                a.append(val)
        return self.query(" AND ".join(w) or "1", a)
