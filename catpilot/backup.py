"""Sauvegarde automatique sur Nextcloud (ou tout serveur WebDAV : kDrive, ownCloud…).

Envoie dans un dossier du serveur : le carnet (base SQLite et fichier ADIF), la main courante,
et les réglages du logiciel (sans les mots de passe). Une copie ADIF datée est gardée dans
le sous-dossier « historique ». Une fois par jour au démarrage, ou à la demande.
"""
import base64
import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from . import __version__, adif
from .logbook import data_dir

SECRET = ("pass", "pswd", "logkey", "api", "password")


def dav_base(url, user, folder):
    """Adresse WebDAV du dossier. Accepte l'adresse du Nextcloud (https://cloud.exemple.fr)
    ou directement une adresse WebDAV complète."""
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    if "/remote.php/" not in url and "/dav" not in url and "webdav" not in url.lower():
        url = f"{url}/remote.php/dav/files/{urllib.parse.quote(user)}"
    for part in [p for p in folder.strip("/").split("/") if p]:
        url += "/" + urllib.parse.quote(part)
    return url


class Backup(QObject):
    status = Signal(str)

    def __init__(self, win):
        super().__init__()
        self.win, self.s = win, win.settings
        self.busy = False
        QTimer.singleShot(20000, self.auto)

    def configured(self):
        return all((self.s.value(k, "") or "").strip() for k in ("nc_url", "nc_user", "nc_pass"))

    def auto(self):
        if not self.configured() or self.s.value("nc_daily", "true") not in (True, "true"):
            return
        last = self.s.value("nc_last", "")
        if last == datetime.date.today().isoformat():
            return
        self.run()

    def run(self):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _req(self, method, url, data=None):
        tok = base64.b64encode(f"{self.s.value('nc_user', '')}:{self.s.value('nc_pass', '')}".encode()).decode()
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": f"Basic {tok}", "User-Agent": f"CATPilot/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def _mkcol(self, url):
        code = self._req("MKCOL", url)
        if code not in (201, 405, 301):           # 405 : le dossier existe déjà
            raise RuntimeError(f"création du dossier refusée (code {code})")

    def _files(self, tmp):
        """Prépare les fichiers à envoyer (copies cohérentes des bases)."""
        out = []
        log = self.win.log
        p = os.path.join(tmp, "carnet.sqlite")
        with log.lock:
            dst = sqlite3.connect(p)
            log.db.backup(dst)
            dst.close()
        out.append(("carnet.sqlite", p))
        p = os.path.join(tmp, "carnet.adi")
        with open(p, "w", encoding="utf-8") as f:
            f.write(adif.write(log.export_records(log.query()), "CAT Pilot", __version__))
        out.append(("carnet.adi", p))
        mc = getattr(self.win, "mc", None)
        if mc:
            p = os.path.join(tmp, "main_courante.sqlite")
            with mc.journal.lock:
                dst = sqlite3.connect(p)
                mc.journal.db.backup(dst)
                dst.close()
            out.append(("main_courante.sqlite", p))
        cfg = {}
        for k in self.s.allKeys():
            if any(x in k.lower() for x in SECRET):
                continue
            v = self.s.value(k)
            if isinstance(v, (str, int, float, bool)) or v is None:
                cfg[k] = v
        p = os.path.join(tmp, "reglages.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        out.append(("reglages.json", p))
        return out

    def _run(self):
        tmp = tempfile.mkdtemp(prefix="catpilot_bk_")
        try:
            root = dav_base(self.s.value("nc_url", ""), self.s.value("nc_user", ""), "")
            self.status.emit("Sauvegarde Nextcloud en cours…")
            base = root
            for part in [p for p in (self.s.value("nc_folder", "CATPilot") or "CATPilot").strip("/").split("/") if p]:
                base += "/" + urllib.parse.quote(part)
                self._mkcol(base)
            self._mkcol(base + "/historique")
            files = self._files(tmp)
            for name, path in files:
                with open(path, "rb") as f:
                    code = self._req("PUT", f"{base}/{name}", f.read())
                if code not in (200, 201, 204):
                    raise RuntimeError(f"envoi de {name} refusé (code {code})")
            today = datetime.date.today().isoformat()
            with open(dict(files)["carnet.adi"], "rb") as f:
                self._req("PUT", f"{base}/historique/carnet_{today}.adi", f.read())
            self.s.setValue("nc_last", today)
            self.status.emit(f"Sauvegarde Nextcloud faite : {len(files)} fichiers dans « {self.s.value('nc_folder', 'CATPilot')} »")
        except Exception as e:
            self.status.emit(f"Sauvegarde Nextcloud impossible : {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.busy = False


class BackupDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.s = win, win.settings
        self.setWindowTitle("Sauvegarde Nextcloud")
        self.resize(560, 0)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.ed = {}
        for key, label, ph, pwd in (("nc_url", "Adresse du Nextcloud", "https://cloud.exemple.fr", False),
                                    ("nc_user", "Utilisateur", "", False),
                                    ("nc_pass", "Mot de passe d'application", "", True),
                                    ("nc_folder", "Dossier", "CATPilot", False)):
            e = QLineEdit(self.s.value(key, "") or ("CATPilot" if key == "nc_folder" else ""))
            e.setPlaceholderText(ph)
            if pwd:
                e.setEchoMode(QLineEdit.Password)
            f.addRow(label, e)
            self.ed[key] = e
        self.ck = QCheckBox("Sauvegarder automatiquement une fois par jour")
        self.ck.setChecked(self.s.value("nc_daily", "true") in (True, "true"))
        f.addRow(self.ck)
        v.addLayout(f)
        t = QLabel("Créez un « mot de passe d'application » dans Nextcloud (Paramètres > Sécurité) plutôt que "
                   "d'utiliser votre mot de passe. Sont envoyés : le carnet (SQLite et ADIF), la main courante et "
                   "les réglages (sans aucun mot de passe), plus une copie datée du carnet dans « historique ». "
                   "Une adresse WebDAV complète (kDrive, ownCloud…) est aussi acceptée.")
        t.setWordWrap(True)
        t.setObjectName("hint")
        v.addWidget(t)
        last = self.s.value("nc_last", "")
        self.lb = QLabel(f"Dernière sauvegarde : {last}" if last else "Aucune sauvegarde pour l'instant")
        self.lb.setObjectName("value")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        b = QPushButton("Sauvegarder maintenant")
        b.clicked.connect(self.now)
        v.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.accept)
        v.addWidget(bb)
        win.backup.status.connect(self.lb.setText)

    def store(self):
        for k, e in self.ed.items():
            self.s.setValue(k, e.text() if k == "nc_pass" else e.text().strip())
        self.s.setValue("nc_daily", "true" if self.ck.isChecked() else "false")

    def now(self):
        self.store()
        if not self.win.backup.configured():
            self.lb.setText("Renseignez l'adresse, l'utilisateur et le mot de passe d'application")
            return
        self.win.backup.run()

    def done(self, r):
        self.store()
        try:
            self.win.backup.status.disconnect(self.lb.setText)
        except (RuntimeError, TypeError):
            pass
        super().done(r)
