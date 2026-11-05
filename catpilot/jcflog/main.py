import sys, os, datetime, shutil, webbrowser, glob
from PySide6.QtCore import Qt, QTimer, QAbstractTableModel, QModelIndex, QObject, Signal, QRunnable, QThreadPool, QUrl
from PySide6.QtGui import QAction, QPalette, QColor, QFont, QKeySequence
from PySide6.QtWidgets import *
from .db import DB, appdir
from .dxcc import DXCC
from . import geo, adif, net
from .radio import Rig, Rotator, Cluster, WSJTX, to_adif_mode
from .dialogs import Settings, EditQSO, TableDialog, awards
from . import screen

VERSION = "1.0.0"
COLS = [("qso_date", "Date"), ("time_on", "Heure"), ("call", "Indicatif"), ("rst_sent", "RSTe"), ("rst_rcvd", "RSTr"),
        ("freq", "Fréquence"), ("band", "Bande"), ("mode", "Mode"), ("submode", "Sous-mode"), ("name", "Nom"),
        ("qth", "QTH"), ("gridsquare", "Locator"), ("country", "Pays"), ("cont", "Cont"), ("comment", "Commentaire"),
        ("qsl_sent", "QSL e"), ("qsl_rcvd", "QSL r"), ("lotw_qsl_rcvd", "LoTW"), ("eqsl_qsl_rcvd", "eQSL"),
        ("pota_ref", "POTA"), ("sota_ref", "SOTA"), ("wwff_ref", "WWFF"), ("iota", "IOTA"), ("srx", "SRX"), ("stx", "STX")]


class _Sig(QObject):
    done = Signal(object, object)


class Job(QRunnable):
    def __init__(self, fn, cb):
        super().__init__()
        self.fn, self.s = fn, _Sig()
        self.s.done.connect(cb)

    def run(self):
        try:
            self.s.done.emit(self.fn(), None)
        except Exception as e:
            self.s.done.emit(None, e)


def bg(fn, cb):
    j = Job(fn, cb)
    QThreadPool.globalInstance().start(j)
    bg.jobs = getattr(bg, "jobs", []) + [j]


class LogModel(QAbstractTableModel):
    def __init__(self, db):
        super().__init__()
        self.db, self.rows, self.where, self.args = db, [], "1", ()

    def reload(self):
        self.beginResetModel()
        self.rows = self.db.query(self.where, self.args)
        self.endResetModel()

    def rowCount(self, p=QModelIndex()): return len(self.rows)
    def columnCount(self, p=QModelIndex()): return len(COLS)

    def data(self, i, role=Qt.DisplayRole):
        if role in (Qt.DisplayRole, Qt.EditRole):
            k = COLS[i.column()][0]
            v = self.rows[i.row()].get(k) or ""
            if role == Qt.DisplayRole:
                if k == "qso_date" and len(v) == 8: return f"{v[:4]}-{v[4:6]}-{v[6:]}"
                if k == "time_on" and len(v) >= 4: return f"{v[:2]}:{v[2:4]}"
            return v

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return COLS[s][1]

    def flags(self, i): return super().flags(i) | Qt.ItemIsEditable

    def setData(self, i, v, role=Qt.EditRole):
        k = COLS[i.column()][0]
        r = self.rows[i.row()]
        r[k] = v
        self.db.update(r["id"], {k: v})
        return True

    def sort(self, col, order=Qt.AscendingOrder):
        k = COLS[col][0]
        self.beginResetModel()
        self.rows.sort(key=lambda r: (r.get(k) or "", r.get("time_on") or ""), reverse=order == Qt.DescendingOrder)
        self.endResetModel()


MAP_HTML = """<!DOCTYPE html><html><head><meta charset=utf-8>
<link rel=stylesheet href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/@joergdietrich/leaflet.terminator@1.1.0/L.Terminator.js"></script>
<style>html,body,#m{margin:0;height:100%;background:#222}</style></head><body><div id=m></div><script>
var m=L.map('m',{worldCopyJump:true}).setView([45,5],3);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(m);
var t=L.terminator({fillOpacity:0.3}).addTo(m);setInterval(function(){t.setTime()},60000);
var me=null,dx=null,line=null,spots=L.layerGroup().addTo(m);
function gc(a,b){var p=[],r=Math.PI/180,la1=a[0]*r,lo1=a[1]*r,la2=b[0]*r,lo2=b[1]*r;
var d=2*Math.asin(Math.sqrt(Math.pow(Math.sin((la2-la1)/2),2)+Math.cos(la1)*Math.cos(la2)*Math.pow(Math.sin((lo2-lo1)/2),2)));
if(d==0)return[a,b];for(var i=0;i<=64;i++){var f=i/64,A=Math.sin((1-f)*d)/Math.sin(d),B=Math.sin(f*d)/Math.sin(d);
var x=A*Math.cos(la1)*Math.cos(lo1)+B*Math.cos(la2)*Math.cos(lo2),y=A*Math.cos(la1)*Math.sin(lo1)+B*Math.cos(la2)*Math.sin(lo2),z=A*Math.sin(la1)+B*Math.sin(la2);
p.push([Math.atan2(z,Math.sqrt(x*x+y*y))/r,Math.atan2(y,x)/r]);}return p;}
function setMe(a,b,l){if(me)m.removeLayer(me);me=L.circleMarker([a,b],{radius:6,color:'#0f0'}).addTo(m).bindTooltip(l);}
function setDX(a,b,l){if(dx)m.removeLayer(dx);if(line)m.removeLayer(line);dx=L.marker([a,b]).addTo(m).bindTooltip(l,{permanent:true});
if(me){line=L.polyline(gc([me.getLatLng().lat,me.getLatLng().lng],[a,b]),{color:'#f80'}).addTo(m);}m.setView([a,b],Math.max(m.getZoom(),2));}
function clearDX(){if(dx)m.removeLayer(dx);if(line)m.removeLayer(line);dx=line=null;}
function addSpot(a,b,l){L.circleMarker([a,b],{radius:3,color:'#f33'}).addTo(spots).bindTooltip(l);if(spots.getLayers().length>300)spots.removeLayer(spots.getLayers()[0]);}
</script></body></html>"""


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DB()
        self.dxcc = DXCC()
        self.cb = net.Callbook()
        self.cfg = self.db.get("cfg", {})
        self.rig, self.rot, self.clu, self.wsj = Rig(), Rotator(), Cluster(), WSJTX()
        self.rig_freq, self.contest, self.edit_ent = None, None, None
        self.setWindowTitle(f"JCFLog {VERSION}")
        self.setDockNestingEnabled(True)
        self._central()
        self._docks()
        self._menus()
        self._status()
        self._signals()
        self.reset()
        self.apply_filter()
        st = self.db.get("geometry")
        if st:
            try: self.restoreState(bytes.fromhex(st))
            except Exception: pass
        self._place_window()
        if not st:
            # premier lancement : panneaux du bas proportionnés à la hauteur de l'écran
            bottom = [d for d in self.docks if self.dockWidgetArea(d) == Qt.BottomDockWidgetArea and not d.isHidden()]
            if bottom:
                h = int(screen.available(self).height() * (0.22 if screen.is_small(self) else 0.28))
                QTimer.singleShot(0, lambda: self.resizeDocks(bottom, [h] * len(bottom), Qt.Vertical))
        if not self.db.get("profiles"):
            QTimer.singleShot(300, self.settings)
        QTimer.singleShot(500, self.start_services)

    def _place_window(self):
        """Taille et position de la fenêtre adaptées à l'écran du PC."""
        g = self.db.get("wingeom")
        if g and len(g) == 5:
            r = screen.QRect(*g[:4])
            if screen.on_screen(r) and r.width() <= screen.available(self).width() + 50:
                self.setGeometry(r)
                if g[4]: self._start_max = True
                return
        if screen.is_small(self):
            self._start_max = True          # petit écran : plein écran
        else:
            screen.fit(self, 1400, 860)

    def show(self):
        if getattr(self, "_start_max", False): self.showMaximized()
        else: super().show()

    # ---------- UI ----------
    def _central(self):
        w = QWidget(); v = QVBoxLayout(w)
        fb = QHBoxLayout()
        self.f_search = QLineEdit(placeholderText="🔍 Indicatif"); self.f_search.setMaximumWidth(160)
        self.f_band, self.f_mode, self.f_country = QComboBox(), QComboBox(), QComboBox()
        for c in (self.f_band, self.f_mode, self.f_country):
            c.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.f_count = QLabel()
        for x in (self.f_search, self.f_band, self.f_mode, self.f_country):
            fb.addWidget(x)
        fb.addStretch(); fb.addWidget(self.f_count)
        v.addLayout(fb)
        self.model = LogModel(self.db)
        self.table = QTableView(); self.table.setModel(self.model)
        self.table.setSortingEnabled(True); self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setEditTriggers(QTableView.EditKeyPressed | QTableView.SelectedClicked)
        self.table.verticalHeader().hide(); self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)
        for t, fn in (("Modifier le QSO…", self.edit_qso), ("Supprimer", self.delete_qso), ("Marquer QSL papier envoyée", lambda: self.mark("qsl_sent")),
                      ("Marquer QSL papier reçue", lambda: self.mark("qsl_rcvd")), ("Exporter la sélection (ADIF)…", self.export_sel),
                      ("Recherche Web", lambda: self.web(self.sel_rows()[0]["call"] if self.sel_rows() else ""))):
            a = QAction(t, self.table); a.triggered.connect(fn); self.table.addAction(a)
        self.table.doubleClicked.connect(self.edit_qso)
        split = QSplitter(Qt.Vertical); split.addWidget(self.table)

        e = QWidget(); g = QGridLayout(e); g.setContentsMargins(0, 0, 0, 0)
        big = QFont(); big.setPointSize(screen.big_pt()); big.setBold(True)
        self.e_call = QLineEdit(); self.e_call.setFont(big); self.e_call.setMinimumWidth(int(200 * screen.scale()))
        self.e_rsts, self.e_rstr = QLineEdit(), QLineEdit()
        for x in (self.e_rsts, self.e_rstr):
            x.setFont(big); x.setMaximumWidth(int(80 * screen.scale()) + 10)
        self.e_mode, self.e_submode = QComboBox(), QComboBox()
        self.e_mode.addItems(list(geo.MODES))
        self.e_freq = QDoubleSpinBox(); self.e_freq.setDecimals(5); self.e_freq.setRange(0, 300000); self.e_freq.setSuffix(" MHz"); self.e_freq.setValue(14.074)
        self.e_band = QLabel(); self.e_band.setStyleSheet("font-weight:bold")
        self.e_name, self.e_qth, self.e_loc, self.e_comment = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.e_date = QDateEdit(calendarPopup=True); self.e_date.setDisplayFormat("dd/MM/yyyy")
        self.e_time = QTimeEdit(); self.e_time.setDisplayFormat("HH:mm:ss")
        self.e_dur = QLabel("00:00:00")
        self.btn_start, self.btn_stop = QPushButton("▶"), QPushButton("■")
        self.btn_save, self.btn_reset, self.btn_web = QPushButton("💾 Enregistrer"), QPushButton("↺ Réinit"), QPushButton("🔍 Web")
        self.btn_save.setShortcut(QKeySequence(Qt.Key_Return)); self.btn_reset.setShortcut(QKeySequence(Qt.Key_Escape))
        self.info = QTextBrowser(); self.info.setMaximumWidth(330); self.info.setOpenExternalLinks(True)
        lab = lambda t: QLabel(t)
        g.addWidget(lab("Indicatif"), 0, 0); g.addWidget(lab("RST envoyé"), 0, 1); g.addWidget(lab("RST reçu"), 0, 2)
        g.addWidget(lab("Mode"), 0, 3); g.addWidget(lab("Bande/Fréq"), 0, 4)
        g.addWidget(self.e_call, 1, 0); g.addWidget(self.e_rsts, 1, 1); g.addWidget(self.e_rstr, 1, 2)
        mm = QHBoxLayout(); mm.addWidget(self.e_mode); mm.addWidget(self.e_submode); g.addLayout(mm, 1, 3)
        ff = QHBoxLayout(); ff.addWidget(self.e_freq); ff.addWidget(self.e_band); g.addLayout(ff, 1, 4)
        g.addWidget(lab("Nom"), 2, 0); g.addWidget(lab("QTH"), 2, 1, 1, 2); g.addWidget(lab("Locator"), 2, 3); g.addWidget(lab("Commentaire"), 2, 4)
        g.addWidget(self.e_name, 3, 0); g.addWidget(self.e_qth, 3, 1, 1, 2); g.addWidget(self.e_loc, 3, 3); g.addWidget(self.e_comment, 3, 4)
        g.addWidget(lab("Date (UTC)"), 4, 0); g.addWidget(lab("Heure début"), 4, 1, 1, 2); g.addWidget(lab("Durée"), 4, 3)
        g.addWidget(self.e_date, 5, 0)
        tt = QHBoxLayout(); tt.addWidget(self.e_time); tt.addWidget(self.btn_start); g.addLayout(tt, 5, 1, 1, 2)
        dd = QHBoxLayout(); dd.addWidget(self.e_dur); dd.addWidget(self.btn_stop); g.addLayout(dd, 5, 3)
        bb = QHBoxLayout(); bb.addWidget(self.btn_save); bb.addWidget(self.btn_reset); bb.addWidget(self.btn_web); g.addLayout(bb, 5, 4)
        self.contest_box = QWidget(); cl = QHBoxLayout(self.contest_box); cl.setContentsMargins(0, 0, 0, 0)
        self.e_stx, self.e_srx = QLineEdit(), QLineEdit()
        self.contest_lbl = QLabel()
        cl.addWidget(self.contest_lbl); cl.addWidget(QLabel("Envoyé (STX)")); cl.addWidget(self.e_stx); cl.addWidget(QLabel("Reçu (SRX)")); cl.addWidget(self.e_srx)
        self.contest_box.hide(); g.addWidget(self.contest_box, 6, 0, 1, 5)
        g.addWidget(lab("Infos"), 0, 5); g.addWidget(self.info, 1, 5, 6, 1)

        self.tabs = QTabWidget()
        det = QWidget(); dg = QGridLayout(det); self.d = {}
        det_fields = [("cont", "Continent"), ("ituz", "ITU"), ("cqz", "CQZ"), ("state", "État"), ("cnty", "Comté/Dépt"),
                      ("age", "Âge"), ("vucc_grids", "VUCC"), ("dok", "DOK"), ("iota", "IOTA"), ("pota_ref", "POTA"),
                      ("sota_ref", "SOTA"), ("wwff_ref", "WWFF"), ("sig", "SIG"), ("sig_info", "Infos SIG"),
                      ("qsl_via", "QSL via"), ("email", "Email"), ("web", "Web"), ("prop_mode", "Propagation")]
        for i, (k, l) in enumerate(det_fields):
            dg.addWidget(QLabel(l), i % 6, (i // 6) * 2)
            self.d[k] = QLineEdit(); dg.addWidget(self.d[k], i % 6, (i // 6) * 2 + 1)
        self.d["prop_mode"] = QComboBox(); self.d["prop_mode"].addItems(["", "AS", "AUE", "AUR", "BS", "ECH", "EME", "ES", "F2", "FAI", "GWAVE", "INTERNET", "ION", "IRL", "LOS", "MS", "RPT", "RS", "SAT", "TEP", "TR"])
        dg.addWidget(self.d["prop_mode"], 5, 5)
        self.qsl = {}
        for i, (k, l) in enumerate((("qsl_sent", "QSL papier envoyée"), ("lotw_qsl_sent", "LoTW envoi"), ("eqsl_qsl_sent", "eQSL envoi"))):
            c = QComboBox(); c.addItems(["Q - En file", "N - Non", "Y - Oui", "R - Demandée", "I - Ignorer"]); self.qsl[k] = c
            dg.addWidget(QLabel(l), i, 6); dg.addWidget(c, i, 7)
        self.tabs.addTab(det, "Détails")
        self.dxstats = QTableWidget(); self.tabs.addTab(self.dxstats, "Stats DX")
        my = QWidget(); mf = QFormLayout(my)
        self.e_profile = QComboBox(); self.e_rig, self.e_ant, self.e_pwr = QLineEdit(), QLineEdit(), QLineEdit()
        mf.addRow("Profil", self.e_profile); mf.addRow("Équipement", self.e_rig); mf.addRow("Antenne", self.e_ant); mf.addRow("Puissance (W)", self.e_pwr)
        self.tabs.addTab(my, "Ma Station")
        self.notes = QPlainTextEdit(self.db.get("notes", "")); self.notes.textChanged.connect(lambda: self.db.set("notes", self.notes.toPlainText()))
        self.tabs.addTab(self.notes, "Mes Notes")
        box = QWidget(); bl = QVBoxLayout(box); bl.addWidget(e); bl.addWidget(self.tabs)
        # zone de saisie défilante : la fenêtre peut rétrécir sur un petit écran
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setWidget(box)
        sa.setMinimumHeight(120)
        split.addWidget(sa); split.setSizes([int(300 * screen.scale()), int(500 * screen.scale())])
        v.addWidget(split)
        self.setCentralWidget(w)

    def _dock(self, title, widget, area=Qt.RightDockWidgetArea, show=True):
        d = QDockWidget(title, self); d.setObjectName(title); d.setWidget(widget)
        if area == Qt.RightDockWidgetArea: widget.setMinimumWidth(int(280 * screen.scale()))
        self.addDockWidget(area, d)
        if not show: d.hide()
        self.docks.append(d)
        return d

    def _docks(self):
        self.docks = []
        c = QWidget(); cv = QVBoxLayout(c)
        self.clock = QLabel(); self.clock.setAlignment(Qt.AlignCenter); self.clock.setStyleSheet("font-size:28px;font-weight:bold")
        self.clock2 = QLabel(); self.clock2.setAlignment(Qt.AlignCenter)
        cv.addWidget(self.clock); cv.addWidget(self.clock2)
        self._dock("Horloge", c)
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.map = QWebEngineView(); self.map.setHtml(MAP_HTML, QUrl("https://localhost/"))
            self.map.loadFinished.connect(lambda ok: self.map_me())
            self._dock("Carte en ligne", self.map)
        except Exception:
            self.map = None
        r = QWidget(); rf = QGridLayout(r)
        self.r_freq = QLabel("---.-----"); self.r_freq.setStyleSheet("font-size:26px;font-family:Consolas,monospace;color:#5f5")
        self.r_mode, self.r_pwr, self.r_state = QLabel(), QLabel(), QLabel("Déconnecté")
        self.r_qsy = QLineEdit(placeholderText="QSY (MHz)"); self.r_qsy.returnPressed.connect(lambda: self.rig.set_freq(float(self.r_qsy.text().replace(",", "."))))
        self.r_btn = QPushButton("Connecter"); self.r_btn.setCheckable(True); self.r_btn.toggled.connect(self.rig_toggle)
        self.r_ptt = QPushButton("PTT"); self.r_ptt.setCheckable(True); self.r_ptt.toggled.connect(self.rig.ptt)
        rf.addWidget(self.r_freq, 0, 0, 1, 3); rf.addWidget(self.r_mode, 1, 0); rf.addWidget(self.r_pwr, 1, 1); rf.addWidget(self.r_state, 1, 2)
        rf.addWidget(self.r_qsy, 2, 0); rf.addWidget(self.r_btn, 2, 1); rf.addWidget(self.r_ptt, 2, 2)
        bands = QHBoxLayout()
        for b, f in (("160", 1.840), ("80", 3.573), ("40", 7.074), ("30", 10.136), ("20", 14.074), ("17", 18.100), ("15", 21.074), ("12", 24.915), ("10", 28.074), ("6", 50.313), ("2", 144.300)):
            pb = QPushButton(b); pb.setMaximumWidth(34); pb.clicked.connect(lambda _, f=f: self.rig.set_freq(f)); bands.addWidget(pb)
        rf.addLayout(bands, 3, 0, 1, 3)
        self._dock("Transceiver", r, show=False)
        ro = QWidget(); rl = QGridLayout(ro)
        self.ro_az = QLabel("---°"); self.ro_az.setStyleSheet("font-size:26px")
        self.ro_goto = QSpinBox(); self.ro_goto.setRange(0, 360)
        b1, b2, b3 = QPushButton("Connecter"), QPushButton("Aller"), QPushButton("→ DX")
        b1.clicked.connect(lambda: self.rot.start(self.cfg.get("rot_host", "127.0.0.1"), self.cfg.get("rot_port", 4533)))
        b2.clicked.connect(lambda: self.rot.goto(self.ro_goto.value()))
        b3.clicked.connect(self.rot_to_dx)
        rl.addWidget(self.ro_az, 0, 0, 1, 3); rl.addWidget(self.ro_goto, 1, 0); rl.addWidget(b2, 1, 1); rl.addWidget(b3, 1, 2); rl.addWidget(b1, 2, 0, 1, 3)
        self._dock("Rotor", ro, show=False)
        cw = QWidget(); cvl = QVBoxLayout(cw)
        top = QHBoxLayout(); self.c_btn = QPushButton("Connecter"); self.c_btn.clicked.connect(self.cluster_toggle)
        self.c_band = QCheckBox("Bande courante"); self.c_band.toggled.connect(self.refresh_spots)
        top.addWidget(self.c_btn); top.addWidget(self.c_band); cvl.addLayout(top)
        ct = QTabWidget()
        self.spots = QTableWidget(0, 6); self.spots.setHorizontalHeaderLabels(["UTC", "Indicatif", "Fréq", "Pays", "Spotteur", "Commentaire"])
        self.spots.verticalHeader().hide(); self.spots.setEditTriggers(QTableWidget.NoEditTriggers); self.spots.setSelectionBehavior(QTableWidget.SelectRows)
        self.spots.horizontalHeader().setStretchLastSection(True); self.spots.cellDoubleClicked.connect(self.spot_clicked)
        self.c_console = QPlainTextEdit(readOnly=True); self.c_cmd = QLineEdit(placeholderText="Commande cluster (ex: sh/dx 30)")
        self.c_cmd.returnPressed.connect(lambda: (self.clu.send(self.c_cmd.text()), self.c_cmd.clear()))
        con = QWidget(); col = QVBoxLayout(con); col.addWidget(self.c_console); col.addWidget(self.c_cmd)
        ct.addTab(self.spots, "Spots"); ct.addTab(con, "Console"); cvl.addWidget(ct)
        self._dock("DX Cluster", cw, Qt.BottomDockWidgetArea)
        self.spot_list = []
        self.wj = QTableWidget(0, 6); self.wj.setHorizontalHeaderLabels(["UTC", "dB", "DF", "Message", "Pays", "Statut"])
        self.wj.verticalHeader().hide(); self.wj.setEditTriggers(QTableWidget.NoEditTriggers); self.wj.horizontalHeader().setStretchLastSection(True)
        self.wj.cellDoubleClicked.connect(self.wsjtx_reply); self.wj_data = []
        self._dock("WSJT-X", self.wj, Qt.BottomDockWidgetArea, show=False)
        self.alerts = QListWidget(); self._dock("Alertes", self.alerts, Qt.BottomDockWidgetArea, show=False)

    def _menus(self):
        mb = self.menuBar()
        def add(menu, text, fn, sc=None):
            a = QAction(text, self); a.triggered.connect(fn)
            if sc: a.setShortcut(sc)
            menu.addAction(a); return a
        m = mb.addMenu("&Fichier")
        add(m, "Importer ADIF…", self.import_adif); add(m, "Exporter ADIF (tout / filtre)…", self.export_all)
        add(m, "Exporter CSV…", self.export_csv); add(m, "Sauvegarder la base…", self.backup_to)
        m.addSeparator(); add(m, "Paramètres…", self.settings, "Ctrl+,"); m.addSeparator(); add(m, "Quitter", self.close, "Ctrl+Q")
        m = mb.addMenu("&Carnet de trafic")
        add(m, "Nouveau QSO (réinitialiser)", self.reset, "Ctrl+N"); add(m, "Modifier QSO sélectionné", self.edit_qso, "Ctrl+E")
        add(m, "Supprimer QSO sélectionné(s)", self.delete_qso, "Del"); m.addSeparator()
        st = m.addMenu("Statistiques")
        for k in ("Par bande", "Par mode", "Par continent", "Par année", "Par pays (top)", "Par mois"):
            add(st, k, lambda _, k=k: self.stats(k))
        aw = m.addMenu("Diplômes")
        for k in ("DXCC", "WAZ (zones CQ)", "ITU", "WAC (continents)", "IOTA", "POTA", "SOTA", "WWFF", "Locators (4)", "Départements/Comtés"):
            add(aw, k, lambda _, k=k: TableDialog(f"Diplôme {k}", *awards(self.db, k)[:2], self, awards(self.db, k)[2]).exec())
        m = mb.addMenu("C&oncours")
        add(m, "Démarrer un concours…", self.contest_start); add(m, "Arrêter le concours", self.contest_stop)
        m = mb.addMenu("&Services")
        add(m, "Envoyer vers LoTW (via TQSL)", lambda: self.upload("lotw")); add(m, "Télécharger confirmations LoTW", lambda: self.download("lotw"))
        m.addSeparator(); add(m, "Envoyer vers eQSL", lambda: self.upload("eqsl")); add(m, "Télécharger confirmations eQSL", lambda: self.download("eqsl"))
        m.addSeparator(); add(m, "Envoyer vers QRZ.com Logbook", lambda: self.upload("qrz")); add(m, "Envoyer vers Club Log", lambda: self.upload("clublog"))
        m.addSeparator(); add(m, "Mettre à jour la base DXCC (cty.csv)", self.update_dxcc)
        m = mb.addMenu("Fe&nêtre")
        for d in self.docks:
            m.addAction(d.toggleViewAction())
        m = mb.addMenu("&Aide")
        add(m, "À propos", lambda: QMessageBox.about(self, "JCFLog", f"<b>JCFLog {VERSION}</b><br>Carnet de trafic radioamateur inspiré de QLog.<br>Logiciel libre sous licence GNU GPL v3.<br>Aucune donnée personnelle intégrée."))

    def _status(self):
        self.s_profile, self.s_solar, self.s_rig = QLabel(), QLabel(), QLabel()
        for w in (self.s_profile, self.s_rig):
            self.statusBar().addWidget(w)
        self.statusBar().addPermanentWidget(self.s_solar)
        self.load_profiles()

    def _signals(self):
        self.f_search.textChanged.connect(self.apply_filter)
        for c in (self.f_band, self.f_mode, self.f_country):
            c.currentIndexChanged.connect(self.apply_filter)
        self.e_call.textEdited.connect(self.call_edited)
        self.e_mode.currentTextChanged.connect(self.mode_changed)
        self.e_freq.valueChanged.connect(lambda v: self.e_band.setText(geo.band_of(v)))
        self.e_loc.textChanged.connect(lambda: self.update_info(self.e_call.text()))
        self.btn_save.clicked.connect(self.save)
        self.btn_reset.clicked.connect(self.reset)
        self.btn_web.clicked.connect(lambda: self.web(self.e_call.text()))
        self.btn_start.clicked.connect(lambda: self.set_now(True))
        self.btn_stop.clicked.connect(self.stop_timer)
        self.e_profile.currentIndexChanged.connect(self.profile_changed)
        self.lookup_timer = QTimer(singleShot=True, interval=600, timeout=self.do_lookup)
        self.tick = QTimer(interval=1000, timeout=self.on_tick); self.tick.start()
        self.solar_t = QTimer(interval=3600_000, timeout=self.get_solar); self.solar_t.start()
        self.rig.status.connect(self.rig_status); self.rig.state.connect(lambda ok, m: self.r_state.setText(m))
        self.rot.position.connect(lambda a, e: self.ro_az.setText(f"{a:.0f}°"))
        self.rot.state.connect(lambda ok, m: self.statusBar().showMessage("Rotor : " + m, 4000))
        self.clu.spot.connect(self.on_spot); self.clu.line.connect(self.c_console.appendPlainText)
        self.clu.state.connect(self.cluster_state)
        self.wsj.status.connect(self.wsjtx_status); self.wsj.decode.connect(self.wsjtx_decode); self.wsj.logged.connect(self.wsjtx_logged)

    # ---------- profiles / services ----------
    def load_profiles(self):
        self.profiles = self.db.get("profiles", [])
        self.e_profile.blockSignals(True); self.e_profile.clear()
        self.e_profile.addItems([p["name"] for p in self.profiles])
        cur = self.db.get("cur_profile", 0)
        if cur < len(self.profiles): self.e_profile.setCurrentIndex(cur)
        self.e_profile.blockSignals(False)
        self.profile_changed(self.e_profile.currentIndex())

    def profile(self):
        i = self.e_profile.currentIndex()
        return self.profiles[i] if 0 <= i < len(self.profiles) else {}

    def profile_changed(self, i):
        p = self.profile()
        self.db.set("cur_profile", max(i, 0))
        self.e_rig.setText(p.get("my_rig", "")); self.e_ant.setText(p.get("my_antenna", "")); self.e_pwr.setText(p.get("tx_pwr", ""))
        self.s_profile.setText(f"<b>{p.get('name', 'Aucun profil')}</b> : {p.get('station_callsign', '')} {p.get('my_gridsquare', '')}")
        self.map_me()

    def my_ll(self):
        return geo.loc2ll(self.profile().get("my_gridsquare", ""))

    def map_me(self):
        ll = self.my_ll()
        if self.map and ll:
            self.map.page().runJavaScript(f"setMe({ll[0]},{ll[1]},'{self.profile().get('station_callsign', '')}')")

    def start_services(self):
        self.get_solar()
        if self.cfg.get("rig_auto"): self.r_btn.setChecked(True)
        if self.cfg.get("cluster_auto"): self.cluster_toggle()
        if self.cfg.get("wsjtx_on"):
            try:
                self.wsj.start(int(self.cfg.get("wsjtx_port") or 2237), self.cfg.get("wsjtx_mcast", ""))
                self.statusBar().showMessage("Écoute WSJT-X active", 4000)
            except Exception as e:
                self.statusBar().showMessage(f"WSJT-X : {e}", 6000)
        if not self.dxcc.prefix:
            self.update_dxcc()

    def get_solar(self):
        def cb(r, e):
            if r: self.s_solar.setText(f"SFI <b>{r['solarflux']}</b>  A <b>{r['aindex']}</b>  K <b>{r['kindex']}</b>")
        bg(net.solar, cb)

    def update_dxcc(self):
        self.statusBar().showMessage("Mise à jour DXCC…")
        bg(self.dxcc.update, lambda r, e: self.statusBar().showMessage(f"DXCC : {e}" if e else f"DXCC à jour ({len(self.dxcc.entities)} entités)", 5000))

    def settings(self):
        if Settings(self.db, self).exec():
            self.cfg = self.db.get("cfg", {})
            self.load_profiles(); apply_theme(self.cfg.get("theme", "Sombre")); screen.apply_text_size(self.cfg.get("text_size", "Auto"))
            if self.cfg.get("wsjtx_on"):
                try: self.wsj.start(int(self.cfg.get("wsjtx_port") or 2237), self.cfg.get("wsjtx_mcast", ""))
                except Exception: pass
            else:
                self.wsj.stop()

    # ---------- filter ----------
    def apply_filter(self):
        w, a = [], []
        if self.f_search.text():
            w.append("call LIKE ?"); a.append(f"%{self.f_search.text().upper()}%")
        for c, col in ((self.f_band, "band"), (self.f_mode, "mode"), (self.f_country, "country")):
            if c.currentIndex() > 0:
                w.append(f"{col}=?"); a.append(c.currentText())
        self.model.where, self.model.args = " AND ".join(w) or "1", a
        self.model.reload()
        self.f_count.setText(f"Nombre : {len(self.model.rows)}")
        self.table.resizeColumnsToContents()

    def refresh_filters(self):
        for c, col, lab in ((self.f_band, "band", "Toutes les bandes"), (self.f_mode, "mode", "Tous les modes"), (self.f_country, "country", "Tous les pays")):
            cur = c.currentText(); c.blockSignals(True); c.clear(); c.addItems([lab] + self.db.distinct(col))
            c.setCurrentText(cur); c.blockSignals(False)

    # ---------- entry ----------
    def utc(self):
        return datetime.datetime.now(datetime.timezone.utc)

    def set_now(self, start=False):
        n = self.utc()
        self.e_date.setDate(n.date()); self.e_time.setTime(n.time().replace(microsecond=0))
        self.timer_on = True; self.start_dt = n

    def stop_timer(self):
        self.timer_on = False

    def reset(self):
        for x in (self.e_call, self.e_name, self.e_qth, self.e_loc, self.e_comment, self.e_srx):
            x.clear()
        for x in self.d.values():
            x.setCurrentIndex(0) if isinstance(x, QComboBox) else x.clear()
        for c in self.qsl.values(): c.setCurrentIndex(0)
        self.mode_changed(self.e_mode.currentText())
        self.e_dur.setText("00:00:00"); self.timer_on = False; self.started = False
        self.set_now(); self.timer_on = False
        self.info.clear(); self.dxstats.clear(); self.dxstats.setRowCount(0)
        self.cur_ent = None
        if self.map: self.map.page().runJavaScript("clearDX()")
        self.refresh_filters()
        self.e_call.setFocus()

    def mode_changed(self, m):
        self.e_submode.clear(); self.e_submode.addItems([""] + geo.MODES.get(m, []))
        if m == "SSB":
            self.e_submode.setCurrentText("LSB" if self.e_freq.value() < 10 else "USB")
        r = geo.DEFAULT_RST.get(m, "59")
        self.e_rsts.setText(r); self.e_rstr.setText(r)

    def call_edited(self, t):
        p = self.e_call.cursorPosition(); self.e_call.setText(t.upper()); self.e_call.setCursorPosition(p)
        if t and not self.started:
            self.set_now(); self.started = True
        self.update_info(t.upper())
        self.lookup_timer.start()

    def update_info(self, call):
        e = self.dxcc.lookup(call) if len(call) >= 2 else None
        self.cur_ent = e
        if not e:
            self.info.setHtml(""); return
        my = self.my_ll()
        dx = geo.loc2ll(self.e_loc.text()) or (e["lat"], e["lon"])
        dist, brg = geo.dist_bearing(my, dx)
        prev = self.db.query("call=?", (call,))
        band = geo.band_of(self.e_freq.value()); mode = self.e_mode.currentText()
        ent = self.db.query("dxcc=?", (e["dxcc"],))
        if not ent: status = "<span style='color:#f44;font-weight:bold'>NOUVEAU DXCC !</span>"
        elif not [q for q in ent if q["band"] == band]: status = "<span style='color:#fa0;font-weight:bold'>Nouvelle bande</span>"
        elif not [q for q in ent if q["band"] == band and q["mode"] == mode]: status = "<span style='color:#fd0'>Nouveau mode/bande</span>"
        else: status = "<span style='color:#8c8'>Déjà contacté</span>"
        conf = any(q.get("qsl_rcvd") == "Y" or q.get("lotw_qsl_rcvd") == "Y" or q.get("eqsl_qsl_rcvd") == "Y" for q in ent)
        units = self.cfg.get("units", "km")
        d = f"{dist if units == 'km' else round(dist * .621)} {units}" if dist is not None else ""
        html = (f"<h3>{e['name']}</h3>DXCC {e['dxcc']} · {e['pfx']} · {e['cont']}<br>CQ {e['cqz']} · ITU {e['ituz']}<br>" +
                (f"Distance : <b>{d}</b><br>Azimut : <b>{brg}°</b> (long chemin {(brg + 180) % 360}°)<br>" if brg is not None else "") + f"{status}"
                f"{' · confirmé' if conf else ''}<br>")
        if prev:
            html += f"<hr>{len(prev)} QSO avec {call} :<br>" + "<br>".join(
                f"{q['qso_date']} {q['band']} {q['mode']} {q.get('name') or ''}" for q in prev[:6])
            if not self.e_name.text(): self.e_name.setText(prev[0].get("name") or "")
            if not self.e_qth.text(): self.e_qth.setText(prev[0].get("qth") or "")
            if not self.e_loc.text(): self.e_loc.setText(prev[0].get("gridsquare") or "")
        self.info.setHtml(html)
        for k in ("cont", "cqz", "ituz"):
            if not self.d[k].text(): self.d[k].setText(e[k])
        self.fill_dxstats(e["dxcc"])
        if self.map:
            self.map.page().runJavaScript(f"setDX({dx[0]},{dx[1]},'{call}')")

    def fill_dxstats(self, dxcc):
        bands = [b for b, *_ in geo.BANDS if b in ("160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m", "2m", "70cm")]
        modes = ["CW", "SSB", "DIGI"]
        self.dxstats.setRowCount(len(modes)); self.dxstats.setColumnCount(len(bands))
        self.dxstats.setHorizontalHeaderLabels(bands); self.dxstats.setVerticalHeaderLabels(modes)
        rows = self.db.query("dxcc=?", (dxcc,))
        for i, m in enumerate(modes):
            for j, b in enumerate(bands):
                qs = [q for q in rows if q["band"] == b and (q["mode"] == m or (m == "DIGI" and q["mode"] not in ("CW", "SSB", "AM", "FM")))]
                c = any(q.get("qsl_rcvd") == "Y" or q.get("lotw_qsl_rcvd") == "Y" or q.get("eqsl_qsl_rcvd") == "Y" for q in qs)
                it = QTableWidgetItem("C" if c else "W" if qs else "")
                it.setBackground(QColor("#2a6") if c else QColor("#a82") if qs else QColor(0, 0, 0, 0))
                self.dxstats.setItem(i, j, it)
        self.dxstats.resizeColumnsToContents()

    def do_lookup(self):
        call = self.e_call.text().strip()
        if len(call) < 3 or self.cfg.get("cb_primary") == "Aucun":
            return
        def cb(r, e):
            if not r or self.e_call.text().strip() != call:
                return
            for k, w in (("name", self.e_name), ("qth", self.e_qth), ("gridsquare", self.e_loc)):
                if r.get(k) and not w.text(): w.setText(r[k])
            for k in ("email", "web", "qsl_via", "iota", "state", "cnty", "age", "ituz", "cqz"):
                if r.get(k) and not self.d[k].text(): self.d[k].setText(r[k])
            self.statusBar().showMessage(f"Callbook : {r['src']}", 3000)
        bg(lambda: self.cb.lookup(call, self.cfg), cb)

    def collect(self):
        call = self.e_call.text().strip().upper()
        p = self.profile()
        e = self.cur_ent or {}
        d = self.e_date.date().toString("yyyyMMdd"); t = self.e_time.time().toString("HHmmss")
        dur = self.e_dur.text().split(":")
        st = datetime.datetime.strptime(d + t, "%Y%m%d%H%M%S") + datetime.timedelta(hours=int(dur[0]), minutes=int(dur[1]), seconds=int(dur[2]))
        q = dict(call=call, qso_date=d, time_on=t, time_off=st.strftime("%H%M%S"), freq="%.6f" % self.e_freq.value(),
                 band=geo.band_of(self.e_freq.value()), mode=self.e_mode.currentText(), submode=self.e_submode.currentText(),
                 rst_sent=self.e_rsts.text(), rst_rcvd=self.e_rstr.text(), name=self.e_name.text(), qth=self.e_qth.text(),
                 gridsquare=self.e_loc.text().upper(), comment=self.e_comment.text(), country=e.get("name", ""), dxcc=e.get("dxcc", ""),
                 station_callsign=p.get("station_callsign", ""), operator=p.get("operator", ""), my_gridsquare=p.get("my_gridsquare", ""),
                 my_rig=self.e_rig.text(), my_antenna=self.e_ant.text(), tx_pwr=self.e_pwr.text())
        for k, w in self.d.items():
            q[k] = w.currentText() if isinstance(w, QComboBox) else w.text()
        for k, c in self.qsl.items():
            q[k] = c.currentText()[0]
        q["qsl_rcvd"] = q["lotw_qsl_rcvd"] = q["eqsl_qsl_rcvd"] = "N"
        dist, _ = geo.dist_bearing(self.my_ll(), geo.loc2ll(q["gridsquare"]) or ((e["lat"], e["lon"]) if e else None))
        if dist is not None: q["distance"] = str(dist)
        if self.contest:
            q.update(contest_id=self.contest, stx=self.e_stx.text(), srx=self.e_srx.text())
        return q

    def save(self):
        if not self.e_call.text().strip():
            return
        if not self.profiles:
            QMessageBox.warning(self, "JCFLog", "Définissez d'abord un profil de station (Fichier > Paramètres)."); return
        q = self.collect()
        if self.contest and self.db.query("contest_id=? AND call=? AND band=? AND mode=?", (self.contest, q["call"], q["band"], q["mode"])):
            if QMessageBox.question(self, "Doublon", f"{q['call']} déjà contacté dans ce concours. Enregistrer quand même ?") != QMessageBox.Yes:
                return
        q["id"] = self.db.add(q)
        self.after_log(q)
        if self.contest:
            try: self.e_stx.setText(str(int(self.e_stx.text()) + 1).zfill(3))
            except ValueError: pass
        self.reset(); self.apply_filter()

    def after_log(self, q):
        if self.cfg.get("qrz_auto") and self.cfg.get("qrz_api_key"):
            bg(lambda: net.qrz_upload(q, self.cfg), lambda r, e: r and r[0] and self.db.update(q["id"], {"qrzcom_qso_upload_status": "Y"}))
        if self.cfg.get("clublog_auto") and self.cfg.get("clublog_api"):
            bg(lambda: net.clublog_upload(q, self.cfg), lambda r, e: r and r[0] and self.db.update(q["id"], {"clublog_qso_upload_status": "Y"}))

    def on_tick(self):
        n = self.utc()
        self.clock.setText(n.strftime("%H:%M:%S UTC"))
        ll = self.my_ll()
        sr = geo.sun_times(*ll) if ll else (None, None)
        self.clock2.setText(f"{n.strftime('%d/%m/%Y')} · local {datetime.datetime.now().strftime('%H:%M')}" + (f"<br>☀ {sr[0]} – {sr[1]} UTC" if sr[0] else ""))
        if not self.started:
            self.e_date.setDate(n.date()); self.e_time.setTime(n.time().replace(microsecond=0))
        elif getattr(self, "timer_on", False):
            s = int((n - self.start_dt).total_seconds())
            self.e_dur.setText("%02d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60))

    def web(self, call):
        if call:
            webbrowser.open((self.cfg.get("web_lookup") or "https://www.qrz.com/db/{call}").replace("{call}", call))

    # ---------- log actions ----------
    def sel_rows(self):
        return [self.model.rows[i.row()] for i in self.table.selectionModel().selectedRows()]

    def edit_qso(self, *_):
        s = self.sel_rows()
        if not s: return
        dlg = EditQSO(s[0], self)
        if dlg.exec():
            self.db.update(s[0]["id"], dlg.values()); self.apply_filter()

    def delete_qso(self):
        s = self.sel_rows()
        if s and QMessageBox.question(self, "Supprimer", f"Supprimer {len(s)} QSO ?") == QMessageBox.Yes:
            self.db.delete([r["id"] for r in s]); self.apply_filter()

    def mark(self, field):
        for r in self.sel_rows():
            self.db.update(r["id"], {field: "Y"})
        self.apply_filter()

    def import_adif(self):
        p, _ = QFileDialog.getOpenFileName(self, "Importer ADIF", "", "ADIF (*.adi *.adif);;Tous (*)")
        if not p: return
        qs = adif.parse(open(p, encoding="utf-8", errors="replace").read())
        for q in qs:
            if not q.get("country") or not q.get("dxcc"):
                e = self.dxcc.lookup(q.get("call"))
                if e:
                    q.setdefault("country", e["name"]); q.setdefault("dxcc", e["dxcc"]); q.setdefault("cont", e["cont"])
            if not q.get("band") and q.get("freq"): q["band"] = geo.band_of(q["freq"])
        n = self.db.add_many(qs)
        QMessageBox.information(self, "Import", f"{n} QSO importés ({len(qs) - n} doublons ignorés).")
        self.refresh_filters(); self.apply_filter()

    def _save_adif(self, rows, title):
        p, _ = QFileDialog.getSaveFileName(self, title, "jcflog.adi", "ADIF (*.adi)")
        if p:
            open(p, "w", encoding="utf-8").write(adif.export(rows))
            self.statusBar().showMessage(f"{len(rows)} QSO exportés", 5000)

    def export_all(self): self._save_adif(self.model.rows, "Exporter ADIF")
    def export_sel(self): self._save_adif(self.sel_rows(), "Exporter la sélection")

    def export_csv(self):
        import csv
        p, _ = QFileDialog.getSaveFileName(self, "Exporter CSV", "jcflog.csv", "CSV (*.csv)")
        if p:
            from .db import FIELDS
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, FIELDS, extrasaction="ignore", delimiter=";"); w.writeheader(); w.writerows(self.model.rows)

    def backup_to(self):
        p, _ = QFileDialog.getSaveFileName(self, "Sauvegarde", f"jcflog_{datetime.date.today():%Y%m%d}.db", "SQLite (*.db)")
        if p: shutil.copy(self.db.path, p)

    def stats(self, kind):
        col = {"Par bande": "band", "Par mode": "mode", "Par continent": "cont", "Par année": "substr(qso_date,1,4)",
               "Par pays (top)": "country", "Par mois": "substr(qso_date,1,6)"}[kind]
        rows = [list(r) for r in self.db.c.execute(
            f"SELECT {col}, COUNT(*), SUM(CASE WHEN qsl_rcvd='Y' OR lotw_qsl_rcvd='Y' OR eqsl_qsl_rcvd='Y' THEN 1 ELSE 0 END), "
            f"COUNT(DISTINCT call) FROM qso GROUP BY 1 ORDER BY 2 DESC")]
        tot = sum(r[1] for r in rows)
        TableDialog(f"Statistiques – {kind}", [kind[4:].capitalize(), "QSO", "Confirmés", "Indicatifs uniques"], rows, self,
                    f"Total : {tot} QSO").exec()

    # ---------- contest ----------
    def contest_start(self):
        name, ok = QInputDialog.getText(self, "Concours", "Identifiant du concours (ex : REF-CW, CQ-WW-SSB) :")
        if ok and name:
            self.contest = name.upper(); self.e_stx.setText("001"); self.contest_lbl.setText(f"<b>{self.contest}</b>")
            self.contest_box.show()

    def contest_stop(self):
        self.contest = None; self.contest_box.hide()

    # ---------- services ----------
    def upload(self, svc):
        field = {"lotw": "lotw_qsl_sent", "eqsl": "eqsl_qsl_sent", "qrz": "qrzcom_qso_upload_status", "clublog": "clublog_qso_upload_status"}[svc]
        need = {"lotw": "lotw_user", "eqsl": "eqsl_user", "qrz": "qrz_api_key", "clublog": "clublog_api"}[svc]
        if svc != "lotw" and not self.cfg.get(need):
            QMessageBox.warning(self, "Services", "Renseignez vos identifiants dans Paramètres > Sync & QSL."); return
        qs = self.db.query(f"({field} IS NULL OR {field} IN ('','N','Q','R'))")
        if not qs:
            QMessageBox.information(self, "Services", "Aucun QSO à envoyer."); return
        if QMessageBox.question(self, "Services", f"Envoyer {len(qs)} QSO vers {svc.upper()} ?") != QMessageBox.Yes:
            return
        cfg = dict(self.cfg)
        def job():
            if svc == "lotw": ok, msg = net.lotw_upload(qs, cfg); okids = [q["id"] for q in qs] if ok else []
            elif svc == "eqsl": ok, msg = net.eqsl_upload(qs, cfg); okids = [q["id"] for q in qs] if ok else []
            else:
                okids, msg = [], ""
                for q in qs:
                    ok, msg = (net.qrz_upload if svc == "qrz" else net.clublog_upload)(q, cfg)
                    if ok: okids.append(q["id"])
            return okids, msg
        def cb(r, e):
            if e: QMessageBox.critical(self, svc.upper(), str(e)); return
            for i in r[0]: self.db.update(i, {field: "Y"})
            QMessageBox.information(self, svc.upper(), f"{len(r[0])}/{len(qs)} QSO envoyés.\n\n{r[1][:300]}"); self.apply_filter()
        self.statusBar().showMessage(f"Envoi {svc.upper()} en cours…"); bg(job, cb)

    def download(self, svc):
        cfg = dict(self.cfg)
        field = "lotw_qsl_rcvd" if svc == "lotw" else "eqsl_qsl_rcvd"
        def job():
            recs = net.lotw_download(cfg) if svc == "lotw" else net.eqsl_download(cfg)
            return len(recs), recs
        def cb(r, e):
            if e: QMessageBox.critical(self, svc.upper(), str(e)); return
            n = net.match_confirmations(self.db, r[1], field)
            QMessageBox.information(self, svc.upper(), f"{r[0]} confirmations reçues, {n} nouveaux QSO confirmés."); self.apply_filter()
        self.statusBar().showMessage(f"Téléchargement {svc.upper()}…"); bg(job, cb)

    # ---------- rig / rot ----------
    def rig_toggle(self, on):
        if on: self.rig.start(dict(self.cfg)); self.r_btn.setText("Déconnecter")
        else: self.rig.stop(); self.r_btn.setText("Connecter")

    def rig_status(self, f, m, p):
        self.rig_freq = f
        self.r_freq.setText(f"{f:.5f} MHz"); self.r_mode.setText(m); self.r_pwr.setText(f"{p} W" if p else "")
        self.s_rig.setText(f"🔊 {f:.4f} {m}")
        if abs(self.e_freq.value() - f) > 1e-6: self.e_freq.setValue(f)
        am, sm = to_adif_mode(m)
        if am in geo.MODES and am != self.e_mode.currentText() and not m.upper().startswith("PKT"):
            self.e_mode.setCurrentText(am)
        if sm: self.e_submode.setCurrentText(sm)
        if p and not self.e_pwr.text(): self.e_pwr.setText(p)

    def rot_to_dx(self):
        if self.cur_ent:
            _, b = geo.dist_bearing(self.my_ll(), geo.loc2ll(self.e_loc.text()) or (self.cur_ent["lat"], self.cur_ent["lon"]))
            if b is not None: self.rot.goto(b); self.ro_goto.setValue(b)

    # ---------- cluster ----------
    def cluster_toggle(self):
        if self.clu.sock: self.clu.disconnect_()
        else:
            self.clu.connect_(self.cfg.get("cluster_host") or "dxc.f5len.org", self.cfg.get("cluster_port") or 7300,
                              self.profile().get("station_callsign") or "NOCALL")

    def cluster_state(self, ok, m):
        self.c_btn.setText("Déconnecter" if ok else "Connecter"); self.statusBar().showMessage("Cluster : " + m, 4000)

    def spot_status(self, call, band):
        e = self.dxcc.lookup(call)
        if not e: return e, ""
        if not self.db.query("dxcc=?", (e["dxcc"],), limit=1): return e, "new"
        if not self.db.query("dxcc=? AND band=?", (e["dxcc"], band), limit=1): return e, "band"
        if self.db.query("call=? AND band=?", (call, band), limit=1): return e, "worked"
        return e, ""

    def on_spot(self, s):
        s["band"] = geo.band_of(s["freq"])
        s["ent"], s["st"] = self.spot_status(s["call"], s["band"])
        self.spot_list.insert(0, s); del self.spot_list[500:]
        alerts = [c.strip().upper() for c in (self.cfg.get("alert_calls") or "").split(",") if c.strip()]
        if s["call"] in alerts or (self.cfg.get("alert_new_dxcc") and s["st"] == "new"):
            self.alerts.insertItem(0, f"{s['time']}Z {s['call']} {s['freq']:.4f} {s['ent']['name'] if s['ent'] else ''} {s['comment']}")
            self.statusBar().showMessage(f"🔔 ALERTE : {s['call']} sur {s['freq']:.4f} MHz", 10000); QApplication.beep()
        if self.map and s["ent"]:
            self.map.page().runJavaScript(f"addSpot({s['ent']['lat']},{s['ent']['lon']},'{s['call']} {s['freq']:.3f}')")
        self.refresh_spots()

    def refresh_spots(self):
        cur = geo.band_of(self.rig_freq or self.e_freq.value())
        rows = [s for s in self.spot_list if not self.c_band.isChecked() or s["band"] == cur]
        if self.c_band.isChecked(): rows.sort(key=lambda s: s["freq"])
        rows = rows[:200]
        self.spots.setRowCount(len(rows)); self.spot_rows = rows
        col = {"new": QColor("#e33"), "band": QColor("#e90"), "worked": QColor("#888")}
        for i, s in enumerate(rows):
            for j, v in enumerate((s["time"], s["call"], f"{s['freq']:.4f}", s["ent"]["name"] if s["ent"] else "", s["spotter"], s["comment"])):
                it = QTableWidgetItem(v)
                if s["st"] in col: it.setForeground(col[s["st"]])
                self.spots.setItem(i, j, it)

    def spot_clicked(self, r, c):
        s = self.spot_rows[r]
        self.reset(); self.e_call.setText(s["call"]); self.e_freq.setValue(s["freq"])
        self.rig.set_freq(s["freq"]); self.call_edited(s["call"])

    # ---------- WSJT-X ----------
    def wsjtx_status(self, s):
        self.e_freq.setValue(s["freq"])
        m = s["mode"].upper()
        if m in ("FT4", "Q65", "JS8"): self.e_mode.setCurrentText("MFSK"); self.e_submode.setCurrentText(m)
        elif m in geo.MODES: self.e_mode.setCurrentText(m)
        if s["dxcall"] and s["dxcall"] != self.e_call.text():
            self.e_call.setText(s["dxcall"]); self.call_edited(s["dxcall"])

    def wsjtx_decode(self, d):
        words = d["msg"].split()
        call = ""
        if words and words[0] == "CQ":
            call = words[-2] if len(words) >= 3 and len(words[-1]) == 4 and words[-1][:2].isalpha() else words[-1]
        elif len(words) >= 2:
            call = words[1]
        e, st = self.spot_status(call, geo.band_of(self.e_freq.value())) if call else (None, "")
        self.wj_data.insert(0, d); del self.wj_data[300:]
        self.wj.insertRow(0)
        t = d["t"] // 1000
        vals = ("%02d:%02d:%02d" % (t // 3600, t // 60 % 60, t % 60), str(d["snr"]), str(d["df"]), d["msg"], e["name"] if e else "",
                {"new": "Nouveau DXCC", "band": "Nouv. bande", "worked": "Contacté"}.get(st, ""))
        for j, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if words and words[0] == "CQ": it.setBackground(QColor("#264"))
            if st == "new": it.setForeground(QColor("#f55"))
            self.wj.setItem(0, j, it)
        if self.wj.rowCount() > 300: self.wj.removeRow(300)

    def wsjtx_reply(self, r, c):
        if r < len(self.wj_data): self.wsj.reply(self.wj_data[r])

    def wsjtx_logged(self, text):
        if not self.cfg.get("wsjtx_autolog"):
            return
        for q in adif.parse(text if "<eoh>" in text.lower() else "<EOH>" + text):
            e = self.dxcc.lookup(q.get("call"))
            if e: q.update(country=e["name"], dxcc=e["dxcc"], cont=e["cont"], cqz=e["cqz"], ituz=e["ituz"])
            p = self.profile()
            q.setdefault("station_callsign", p.get("station_callsign", "")); q.setdefault("my_gridsquare", p.get("my_gridsquare", ""))
            q.setdefault("band", geo.band_of(q.get("freq")))
            if self.e_pwr.text(): q.setdefault("tx_pwr", self.e_pwr.text())
            q["id"] = self.db.add(q); self.after_log(q)
            self.statusBar().showMessage(f"QSO WSJT-X enregistré : {q.get('call')}", 6000)
        self.reset(); self.apply_filter()

    def closeEvent(self, ev):
        self.db.set("geometry", bytes(self.saveState()).hex())
        r = self.normalGeometry()
        self.db.set("wingeom", [r.x(), r.y(), r.width(), r.height(), int(self.isMaximized())])
        self.rig.stop(); self.clu.disconnect_(); self.wsj.stop()
        bdir = os.path.join(appdir(), "backup"); os.makedirs(bdir, exist_ok=True)
        try:
            shutil.copy(self.db.path, os.path.join(bdir, f"jcflog_{datetime.datetime.now():%Y%m%d_%H%M}.db"))
            for old in sorted(glob.glob(os.path.join(bdir, "*.db")))[:-10]: os.remove(old)
        except Exception:
            pass
        ev.accept()


def apply_theme(t):
    app = QApplication.instance(); app.setStyle("Fusion")
    if t == "Clair":
        app.setPalette(app.style().standardPalette()); return
    p = QPalette()
    for role, c in ((QPalette.Window, "#353535"), (QPalette.WindowText, "#ddd"), (QPalette.Base, "#262626"), (QPalette.AlternateBase, "#303030"),
                    (QPalette.Text, "#eee"), (QPalette.Button, "#404040"), (QPalette.ButtonText, "#eee"), (QPalette.Highlight, "#8a4fbf"),
                    (QPalette.HighlightedText, "#fff"), (QPalette.ToolTipBase, "#222"), (QPalette.ToolTipText, "#eee"), (QPalette.Link, "#7af"),
                    (QPalette.PlaceholderText, "#888")):
        p.setColor(role, QColor(c))
    app.setPalette(p)


def run():
    try:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("JCFLog")
    try:
        cfg0 = DB().get("cfg", {})
    except Exception:
        cfg0 = {}
    screen.apply_text_size(cfg0.get("text_size", "Auto"))
    w = Main()
    apply_theme(w.cfg.get("theme", "Sombre"))
    w.show()
    sys.exit(app.exec())
