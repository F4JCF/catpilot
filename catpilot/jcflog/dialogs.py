import sys
from PySide6.QtWidgets import (QDialog, QTabWidget, QWidget, QFormLayout, QLineEdit, QComboBox, QSpinBox, QCheckBox,
                               QDialogButtonBox, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QTableWidget,
                               QTableWidgetItem, QLabel, QHeaderView, QFileDialog, QScrollArea, QGridLayout)
from PySide6.QtCore import Qt
from . import screen
from .radio import RIG_TYPES
from .db import FIELDS
from .geo import BANDS

PROFILE_FIELDS = [("name", "Nom du profil"), ("station_callsign", "Indicatif de la station"), ("operator_name", "Nom de l'opérateur"),
                  ("operator", "Indicatif de l'opérateur"), ("my_gridsquare", "Locator"), ("my_city", "QTH"),
                  ("my_cq", "Zone CQ"), ("my_itu", "Zone ITU"), ("my_sota", "SOTA"), ("my_pota", "POTA"), ("my_wwff", "WWFF"),
                  ("my_iota", "IOTA"), ("my_rig", "Équipement"), ("my_antenna", "Antenne"), ("tx_pwr", "Puissance (W)")]


class Settings(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.w = db, {}
        self.setWindowTitle("Paramètres")
        screen.fit(self, 720, 560)
        cfg = db.get("cfg", {})
        self.profiles = db.get("profiles", [])
        tabs = QTabWidget()

        # Station
        st = QWidget(); h = QHBoxLayout(st)
        self.plist = QListWidget(); self.plist.addItems([p["name"] for p in self.profiles])
        self.plist.currentRowChanged.connect(self._show_profile)
        h.addWidget(self.plist, 1)
        right = QVBoxLayout(); f = QFormLayout()
        self.pw = {}
        for k, lab in PROFILE_FIELDS:
            self.pw[k] = QLineEdit(); f.addRow(lab, self.pw[k])
        right.addLayout(f)
        b = QHBoxLayout()
        for t, fn in (("Ajouter / Mettre à jour", self._add_profile), ("Supprimer", self._del_profile)):
            pb = QPushButton(t); pb.clicked.connect(fn); b.addWidget(pb)
        right.addLayout(b); h.addLayout(right, 2)
        tabs.addTab(st, "Station")

        def form(title, rows):
            w = QWidget(); fl = QFormLayout(w)
            for key, lab, kind in rows:
                if isinstance(kind, list):
                    e = QComboBox(); e.addItems(kind); e.setEditable(False)
                    if cfg.get(key) in kind: e.setCurrentText(cfg[key])
                elif kind == "bool":
                    e = QCheckBox(); e.setChecked(bool(cfg.get(key)))
                else:
                    e = QLineEdit(str(cfg.get(key, kind or "")));
                    if "pass" in key or "key" in key or "api" in key: e.setEchoMode(QLineEdit.Password)
                fl.addRow(lab, e); self.w[key] = e
            tabs.addTab(w, title)

        ports = []
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            pass
        form("Équipement", [("rig_type", "Type de liaison", RIG_TYPES), ("rig_host", "Hôte (rigctld/FLRig)", "127.0.0.1"),
                            ("rig_port", "Port TCP", "4532"), ("rig_com", "Port série " + (", ".join(ports) or ""), "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"),
                            ("rig_baud", "Vitesse", "38400"), ("civ_addr", "Adresse CI-V (hex)", "94"),
                            ("rig_poll", "Intervalle (s)", "0.5"), ("rig_auto", "Connexion auto au démarrage", "bool"),
                            ("rot_host", "Rotor rotctld hôte", "127.0.0.1"), ("rot_port", "Rotor port", "4533")])
        form("Nomenclature (Callbook)", [("cb_primary", "Primaire", ["HamQTH", "QRZ.com", "Aucun"]),
                                         ("cb_secondary", "Secondaire", ["", "HamQTH", "QRZ.com"]),
                                         ("hamqth_user", "HamQTH utilisateur", ""), ("hamqth_pass", "HamQTH mot de passe", ""),
                                         ("qrz_user", "QRZ.com utilisateur", ""), ("qrz_pass", "QRZ.com mot de passe", ""),
                                         ("web_lookup", "URL recherche Web", "https://www.qrz.com/db/{call}")])
        form("Sync & QSL", [("lotw_user", "LoTW utilisateur", ""), ("lotw_pass", "LoTW mot de passe", ""),
                            ("tqsl_path", "Chemin tqsl.exe", r"C:\Program Files (x86)\TrustedQSL\tqsl.exe"),
                            ("tqsl_location", "Station Location TQSL", ""),
                            ("eqsl_user", "eQSL utilisateur", ""), ("eqsl_pass", "eQSL mot de passe", ""),
                            ("qrz_api_key", "Clé API Logbook QRZ", ""), ("qrz_auto", "Envoi auto QRZ", "bool"),
                            ("clublog_email", "Club Log e-mail", ""), ("clublog_pass", "Club Log mot de passe (app)", ""),
                            ("clublog_call", "Club Log indicatif", ""), ("clublog_api", "Club Log clé API", ""),
                            ("clublog_auto", "Envoi auto Club Log (temps réel)", "bool")])
        form("Cluster & Réseau", [("cluster_host", "Serveur DX Cluster", "dxc.f5len.org"), ("cluster_port", "Port", "7300"),
                                  ("cluster_auto", "Connexion auto", "bool"), ("wsjtx_port", "Port UDP WSJT-X", "2237"),
                                  ("wsjtx_mcast", "Adresse multicast (option)", ""), ("wsjtx_on", "Écouter WSJT-X / JTDX", "bool"),
                                  ("wsjtx_autolog", "Enregistrer auto les QSO WSJT-X", "bool")])
        form("Interface", [("theme", "Thème", ["Sombre", "Clair"]), ("text_size", "Taille du texte", screen.TEXT_SIZES), ("units", "Unités", ["km", "miles"]),
                           ("alert_calls", "Alertes indicatifs (séparés par ,)", ""),
                           ("alert_new_dxcc", "Alerte nouveau DXCC sur cluster", "bool")])
        lay = QVBoxLayout(self); lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Enregistrer"); bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self._save); bb.rejected.connect(self.reject); lay.addWidget(bb)
        if self.profiles:
            self.plist.setCurrentRow(0)

    def _show_profile(self, i):
        if 0 <= i < len(self.profiles):
            for k, e in self.pw.items():
                e.setText(self.profiles[i].get(k, ""))

    def _add_profile(self):
        p = {k: e.text().strip() for k, e in self.pw.items()}
        p["station_callsign"] = p["station_callsign"].upper(); p["my_gridsquare"] = p["my_gridsquare"].upper()
        if not p["name"]:
            p["name"] = p["station_callsign"] or "Station"
        for i, q in enumerate(self.profiles):
            if q["name"] == p["name"]:
                self.profiles[i] = p; break
        else:
            self.profiles.append(p); self.plist.addItem(p["name"])

    def _del_profile(self):
        i = self.plist.currentRow()
        if i >= 0:
            self.profiles.pop(i); self.plist.takeItem(i)

    def _save(self):
        if not self.profiles:
            if self.pw["station_callsign"].text():
                self._add_profile()
            else:
                QLabel()
        cfg = self.db.get("cfg", {})
        for k, e in self.w.items():
            cfg[k] = e.currentText() if isinstance(e, QComboBox) else e.isChecked() if isinstance(e, QCheckBox) else e.text().strip()
        self.db.set("cfg", cfg); self.db.set("profiles", self.profiles)
        self.accept()


class EditQSO(QDialog):
    def __init__(self, q, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"QSO {q.get('call', '')}")
        self.e = {}
        w = QWidget(); g = QGridLayout(w)
        for i, k in enumerate(FIELDS):
            g.addWidget(QLabel(k.upper()), i // 2, (i % 2) * 2)
            self.e[k] = QLineEdit(q.get(k) or ""); g.addWidget(self.e[k], i // 2, (i % 2) * 2 + 1)
        sa = QScrollArea(); sa.setWidget(w); sa.setWidgetResizable(True)
        lay = QVBoxLayout(self); lay.addWidget(sa)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); lay.addWidget(bb)
        screen.fit(self, 760, 600)

    def values(self):
        return {k: e.text().strip() for k, e in self.e.items()}


class TableDialog(QDialog):
    def __init__(self, title, headers, rows, parent=None, extra=None):
        super().__init__(parent)
        self.setWindowTitle(title); screen.fit(self, 900, 600)
        lay = QVBoxLayout(self)
        if extra:
            lay.addWidget(QLabel(extra))
        t = QTableWidget(len(rows), len(headers)); t.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(str(v)); it.setTextAlignment(Qt.AlignCenter)
                if v == "C": it.setBackground(Qt.darkGreen)
                elif v == "W": it.setBackground(Qt.darkYellow)
                t.setItem(r, c, it)
        t.setSortingEnabled(True); t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        lay.addWidget(t)


def awards(db, kind="DXCC"):
    col = {"DXCC": "country", "WAZ (zones CQ)": "cqz", "ITU": "ituz", "WAC (continents)": "cont", "IOTA": "iota",
           "POTA": "pota_ref", "SOTA": "sota_ref", "WWFF": "wwff_ref", "Locators (4)": "substr(gridsquare,1,4)",
           "Départements/Comtés": "cnty"}[kind]
    bands = [b for b, *_ in BANDS if b in db.distinct("band")]
    data = {}
    for r in db.c.execute(f"SELECT {col}, band, MAX(CASE WHEN qsl_rcvd='Y' OR lotw_qsl_rcvd='Y' OR eqsl_qsl_rcvd='Y' THEN 1 ELSE 0 END) "
                          f"FROM qso WHERE {col} IS NOT NULL AND {col}<>'' GROUP BY 1,2"):
        data.setdefault(r[0], {})[r[1]] = "C" if r[2] else "W"
    rows = []
    for ent in sorted(data):
        d = data[ent]
        rows.append([ent] + [d.get(b, "") for b in bands] + ["C" if "C" in d.values() else "W"])
    conf = sum(1 for r in rows if r[-1] == "C")
    return ["Entité"] + bands + ["Total"], rows, f"{kind} : {len(rows)} contactés, {conf} confirmés"
