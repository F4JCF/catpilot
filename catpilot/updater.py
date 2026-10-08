"""Vérification et installation des mises à jour depuis les « Releases » GitHub.

Chaque version publiée par l'action GitHub (étiquette vX.Y.Z) porte le fichier
CATPilot.exe. Le logiciel compare son numéro de version à la dernière
publication, télécharge le nouvel exécutable, vérifie son empreinte SHA-256,
puis un petit script remplace l'ancien fichier une fois le logiciel fermé et
le relance.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal

from . import __version__

REPO = "F4JCF/catpilot"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET = "CATPilot.exe"
HEADERS = {"User-Agent": f"CATPilot/{__version__}", "Accept": "application/vnd.github+json"}


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def can_self_update():
    """Remplacement automatique possible seulement pour l'exécutable Windows."""
    return getattr(sys, "frozen", False) and sys.platform == "win32"


class Updater(QObject):
    checked = Signal(object, bool)        # infos de la dernière version (ou exception), vérification manuelle ?
    progress = Signal(int, int)           # octets reçus, total
    downloaded = Signal(object)           # chemin du fichier téléchargé (ou exception)

    def __init__(self):
        super().__init__()
        self._cancel = False

    # --- vérification -------------------------------------------------------------------
    def check(self, manual=False):
        threading.Thread(target=self._check, args=(manual,), daemon=True).start()

    def _check(self, manual):
        try:
            req = urllib.request.Request(API, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                rel = json.loads(r.read().decode("utf-8"))
            asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET), None)
            info = {"version": rel.get("tag_name", "").lstrip("v"), "title": rel.get("name") or "",
                    "notes": rel.get("body") or "", "page": rel.get("html_url") or PAGE,
                    "url": asset and asset.get("browser_download_url"),
                    "size": asset and asset.get("size"),
                    "sha256": (asset.get("digest") or "").replace("sha256:", "") if asset else ""}
            self.checked.emit(info, manual)
        except urllib.error.HTTPError as e:
            msg = ("aucune version publiée n'est accessible (dépôt privé, ou pas encore de version publiée)"
                   if e.code == 404 else f"erreur HTTP {e.code}")
            self.checked.emit(RuntimeError(msg), manual)
        except Exception as e:
            self.checked.emit(e, manual)

    # --- téléchargement -----------------------------------------------------------------
    def download(self, info):
        self._cancel = False
        threading.Thread(target=self._download, args=(info,), daemon=True).start()

    def cancel(self):
        self._cancel = True

    def _download(self, info):
        try:
            dest = os.path.join(tempfile.gettempdir(), f"CATPilot_{info['version']}.exe")
            req = urllib.request.Request(info["url"], headers={"User-Agent": HEADERS["User-Agent"]})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or info.get("size") or 0)
                done = 0
                while True:
                    if self._cancel:
                        raise RuntimeError("téléchargement annulé")
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    self.progress.emit(done, total)
            if total and done != total:
                raise RuntimeError("fichier incomplet")
            if info.get("sha256") and h.hexdigest().lower() != info["sha256"].lower():
                raise RuntimeError("l'empreinte du fichier ne correspond pas : téléchargement corrompu")
            self.downloaded.emit(dest)
        except Exception as e:
            self.downloaded.emit(e)


def install_and_restart(new_exe):
    """Lance le script qui attend la fermeture, remplace l'exécutable et le relance."""
    exe = sys.executable
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), "catpilot_maj.bat")
    with open(bat, "w", encoding="mbcs" if sys.platform == "win32" else "utf-8") as f:
        f.write(f"""@echo off
:attente
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto attente)
set essai=0
:copie
move /y "{new_exe}" "{exe}" >nul 2>&1 && goto relance
set /a essai+=1
if %essai% lss 10 (timeout /t 1 /nobreak >nul & goto copie)
start "" "{exe}"
goto fin
:relance
start "" "{exe}"
:fin
del "%~f0"
""")
    flags = 0x08000000 | 0x00000008          # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", bat], creationflags=flags, close_fds=True)
