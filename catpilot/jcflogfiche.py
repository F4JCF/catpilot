"""Fiche du correspondant dans JCFLog intégré : moteur de recherche et drapeaux de CAT Pilot.

- Recherche d'indicatif : celle de CAT Pilot (QRZ.com, HamQTH, QRZCQ avec les comptes de
  Carnet > Réglages, callook.info, page publique QRZCQ, centre de la commune), lancée pendant
  la frappe ; nom, QTH, locator, QSL via et zones remplissent la fiche de JCFLog.
- Drapeau du pays à côté de l'indicatif, dans le cadre « Infos » et dans la colonne Pays.
- Pays/zones : si la base cty.csv de JCFLog manque, celle de CAT Pilot (cty.dat) prend le relais.
"""
import html
import re

from PySide6.QtCore import QIdentityProxyModel, Qt, QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QHBoxLayout, QLabel

CALL_OK = re.compile(r"^([A-Z0-9]{1,4}/)?[A-Z0-9]{1,3}\d[A-Z]{1,4}(/[A-Z0-9]{1,4})?$")


def _flag(call):
    """(pixmap du drapeau ou None, nom français du pays)."""
    try:
        from .qsl import country_of, flag_pixmap
        iso, name = country_of(call)
        return (flag_pixmap(iso) if iso else None), name
    except Exception:
        return None, ""


class FlagProxy(QIdentityProxyModel):
    """Table des QSO de JCFLog : drapeau devant le pays (mêmes lignes, même tri)."""

    def __init__(self, src, col):
        super().__init__()
        self.col, self._cache = col, {}
        self.setSourceModel(src)

    on_edit = None          # fonction (ligne, clé, valeur) de jcflogtools : modification de plusieurs QSO

    def setData(self, i, v, role=Qt.EditRole):
        if role == Qt.EditRole and self.on_edit is not None:
            try:
                from .jcflog.main import COLS
                row, key = self.sourceModel().rows[i.row()], COLS[i.column()][0]
            except (AttributeError, IndexError):
                return super().setData(i, v, role)
            return bool(self.on_edit(row, key, "" if v is None else str(v)))
        return super().setData(i, v, role)

    def data(self, i, role=Qt.DisplayRole):
        if role in (Qt.DisplayRole, Qt.EditRole):
            try:
                from .jcflog.main import COLS
                from .jcflogtools import display
                key = COLS[i.column()][0]
                txt = display(self.sourceModel().rows[i.row()], key)
                if txt is not None:
                    return txt
                if role == Qt.EditRole and key in ("qso_date", "time_on"):
                    return self.sourceModel().data(self.mapToSource(i), Qt.DisplayRole)
            except (AttributeError, IndexError):
                pass
        if role == Qt.DecorationRole and i.column() == self.col:
            try:
                call = self.sourceModel().rows[i.row()].get("call") or ""
            except (AttributeError, IndexError):
                return None
            if call not in self._cache:
                pm, _ = _flag(call)
                self._cache[call] = pm.scaled(22, 15, Qt.KeepAspectRatio, Qt.SmoothTransformation) if pm else None
            return self._cache[call]
        return super().data(i, role)


class Fiche:
    def __init__(self, dock, jcf):
        self.dock, self.win, self.j = dock, dock.win, jcf
        self.hq = getattr(self.win.logdock, "hamqth", None)     # moteur de recherche de CAT Pilot
        self._auto = {}
        self._extra = ""
        self._flags()
        self._dxcc_fallback()
        if self.hq is not None:
            # la recherche de JCFLog (sans compte) est remplacée par celle de CAT Pilot
            try:
                jcf.lookup_timer.timeout.disconnect()
            except (RuntimeError, TypeError):
                pass
            jcf.lookup_timer.timeout.connect(self.lookup)
            jcf.do_lookup = self.lookup                       # menu Services > Rechercher
            self.hq.result.connect(self.on_result)
            jcf.e_call.returnPressed.connect(self.lookup)
        jcf.e_call.textChanged.connect(self.on_call)
        if self.backfill():
            jcf.apply_filter()
        # le cadre Infos est réécrit par JCFLog à chaque frappe : on y remet la fiche
        orig = jcf.update_info

        def update_info(call):
            orig(call)
            self._base = j.info.toHtml() if j.info.toPlainText().strip() else ""
            self._paint()
        j = jcf
        self._base = ""
        jcf.update_info = update_info

    # --- drapeaux ----------------------------------------------------------------------------
    def _flags(self):
        j = self.j
        self.lb_flag = QLabel()
        self.lb_flag.setFixedWidth(44)
        self.lb_flag.setAlignment(Qt.AlignCenter)
        g = j.e_call.parentWidget().layout()
        idx = g.indexOf(j.e_call)
        if idx >= 0:
            r, c, rs, cs = g.getItemPosition(idx)
            g.removeWidget(j.e_call)
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(self.lb_flag)
            h.addWidget(j.e_call, 1)
            g.addLayout(h, r, c, rs, cs)
        try:
            from .jcflog.main import COLS
            col = [k for k, _ in COLS].index("country")
            self.proxy = FlagProxy(j.model, col)
            sel = j.table.selectionModel()
            j.table.setModel(self.proxy)
            if sel is not None:
                sel.deleteLater()
        except Exception:
            self.proxy = None

    def on_call(self, txt):
        call = (txt or "").strip().upper()
        pm, name = _flag(call) if len(call) >= 1 else (None, "")
        if pm:
            self.lb_flag.setPixmap(pm.scaled(40, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lb_flag.clear()
        self.lb_flag.setToolTip(name)
        # l'indicatif change : on retire ce que l'ancienne fiche avait rempli
        for ed, val in list(self._auto.items()):
            if ed.text() == val:
                ed.clear()
        self._auto.clear()
        self._extra = ""

    def _dxcc_fallback(self):
        """Sans cty.csv, JCFLog ne trouvait plus ni pays ni zones : on prend cty.dat de CAT Pilot."""
        dx = self.j.dxcc
        orig = dx.lookup

        def lookup(call):
            e = orig(call)
            if e or not call:
                return e
            try:
                from . import cty
                i = cty.lookup(call)
            except Exception:
                i = None
            if not i:
                return None
            return dict(name=i["name"], dxcc=i["prefix"], cont=i["cont"], cqz=str(i["cq"]), ituz=str(i["itu"]),
                        lat=i["lat"], lon=i["lon"], pfx=i["prefix"])
        dx.lookup = lookup

    def backfill(self):
        """QSO faits par CAT Pilot (ancien carnet, FT8, WSJT-X, imports) : pays, DXCC, continent et zones
        complétés pour que JCFLog reconnaisse les pays déjà contactés (sinon « NOUVEAU DXCC ! » à tort)."""
        j = self.j
        c = j.db.c
        try:
            rows = c.execute("SELECT id, call, freq, band, country, cont, cqz, ituz FROM qso "
                             "WHERE dxcc IS NULL OR dxcc = '' OR ((band IS NULL OR band = '') AND freq <> '')").fetchall()
        except Exception:
            return 0
        from .logbook import band_of_mhz
        n = 0
        for r in rows:
            r = dict(r)
            upd = {}
            e = j.dxcc.lookup(r["call"] or "")
            if e:
                upd["dxcc"] = e["dxcc"]
                for col, k in (("country", "name"), ("cont", "cont"), ("cqz", "cqz"), ("ituz", "ituz")):
                    if not r.get(col):
                        upd[col] = str(e[k])
            if not r.get("band") and r.get("freq"):
                b = band_of_mhz(r["freq"])
                if b:
                    upd["band"] = b
            if upd:
                c.execute(f"UPDATE qso SET {', '.join(k + ' = ?' for k in upd)} WHERE id = ?", list(upd.values()) + [r["id"]])
                n += 1
        if n:
            c.commit()
        return n

    # --- recherche ---------------------------------------------------------------------------
    def lookup(self):
        call = self.j.e_call.text().strip().upper()
        if self.hq is not None and CALL_OK.match(call):
            self.hq.lookup(call)

    def on_result(self, call, info):
        j = self.j
        if call != j.e_call.text().strip().upper():
            return
        if isinstance(info, str):
            self._extra = f"<p style='color:#e96'>{html.escape(info)}</p>"
            self._paint()
            return
        fill = ((j.e_name, "name"), (j.e_qth, "qth"), (j.e_loc, "grid"))
        if "qsl_via" in j.d:
            fill += ((j.d["qsl_via"], "qsl_via"),)
        for k_ed, k in (("cqz", "cq"), ("ituz", "itu")):
            if k_ed in j.d:
                fill += ((j.d[k_ed], k),)
        for ed, key in fill:
            v = str(info.get(key) or "").strip()
            if v and (not ed.text() or ed.text() == self._auto.get(ed)):
                ed.setText(v.upper() if key in ("grid", "qsl_via") else v)
                self._auto[ed] = ed.text()
        lines = []
        name = " ".join(x for x in (info.get("name"), info.get("qth")) if x)
        if name:
            lines.append(f"<b>{html.escape(name)}</b>")
        if info.get("grid"):
            lines.append(f"Locator {html.escape(str(info['grid']).upper())}")
        qsl = []
        if info.get("qsl_via"):
            qsl.append(f"QSL via {html.escape(str(info['qsl_via']).upper())}")
        if info.get("lotw"):
            qsl.append("LoTW ✓")
        if info.get("eqsl"):
            qsl.append("eQSL ✓")
        if qsl:
            lines.append(" · ".join(qsl))
        if info.get("grid_note"):
            lines.append(html.escape(info["grid_note"]))
        if info.get("sources"):
            lines.append(f"<span style='color:#888'>[{html.escape(info['sources'])}]</span>")
        if info.get("hint"):
            lines.append(f"<span style='color:#e96'>{html.escape(info['hint'])}</span>")
        self._extra = "<br>".join(lines)
        # distance et cap recalculés avec le locator trouvé
        j.update_info(call)
        if info.get("grid"):
            try:
                self.win.point_rotor_to_grid(str(info["grid"])[:6])
            except Exception:
                pass

    def _paint(self):
        """Drapeau + fiche de la recherche en tête du cadre Infos de JCFLog."""
        j = self.j
        call = j.e_call.text().strip().upper()
        if not call:
            return
        pm, country = _flag(call)
        head = ""
        if pm:
            url = QUrl(f"flag://{call}")
            j.info.document().addResource(QTextDocument.ImageResource, url,
                                          pm.scaled(48, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            head = f"<img src='flag://{call}'> "
        if country:
            head += f"<b>{html.escape(country)}</b>"
        top = (head + ("<br>" if head and self._extra else "") + self._extra) if (head or self._extra) else ""
        if top:
            m = re.search(r"<body[^>]*>(.*)</body>", self._base, re.S)
            body = m.group(1) if m else ""
            j.info.setHtml(f"<div>{top}</div>" + ("<hr>" + body if body else ""))
