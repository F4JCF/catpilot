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
ASSET = "CATPilot.exe" if sys.platform == "win32" else "CATPilot-x86_64.AppImage"
HEADERS = {"User-Agent": f"CATPilot/{__version__}", "Accept": "application/vnd.github+json"}


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def appimage_path():
    """Chemin du fichier AppImage en cours d'exécution (Linux), ou ""."""
    p = os.environ.get("APPIMAGE", "")
    return p if p and os.path.isfile(p) else ""


def can_self_update():
    """Remplacement automatique : CATPilot.exe sous Windows, ou l'AppImage sous Linux (si modifiable)."""
    if not getattr(sys, "frozen", False):
        return False
    if sys.platform == "win32":
        return True
    p = appimage_path()
    return bool(p) and os.access(os.path.dirname(p), os.W_OK)


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
            ext = ".exe" if sys.platform == "win32" else ".AppImage"
            d = os.path.dirname(appimage_path()) if appimage_path() else tempfile.gettempdir()
            dest = os.path.join(d, f".CATPilot_{info['version']}{ext}.part" if appimage_path()
                                else f"CATPilot_{info['version']}{ext}")
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


def clean_env():
    """Environnement pour lancer une NOUVELLE instance du logiciel.

    Sans cela, l'exécutable PyInstaller relancé croit être la suite de l'instance
    qui se ferme, réutilise son dossier temporaire (supprimé à la fermeture) et
    s'arrête sans rien afficher.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def spawn_detached(cmd):
    """Lance un processus indépendant, qui survit à la fermeture du logiciel."""
    if sys.platform != "win32":
        subprocess.Popen(cmd, env=clean_env(), start_new_session=True, close_fds=True)
        return
    base = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:                                    # hors du « job » de l'application si Windows l'autorise
        subprocess.Popen(cmd, env=clean_env(), creationflags=base | 0x01000000, close_fds=True)
    except OSError:
        subprocess.Popen(cmd, env=clean_env(), creationflags=base, close_fds=True)


def _sh_wait():
    return f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done\n"


def restart():
    """Relance le logiciel (après un changement de langue, par exemple)."""
    if sys.platform != "win32":
        target = appimage_path() or (sys.executable if getattr(sys, "frozen", False) else "")
        cmd = f'"{target}"' if target else f'"{sys.executable}" ' + " ".join(f'"{a}"' for a in sys.argv)
        spawn_detached(["sh", "-c", _sh_wait() + f"exec {cmd}"])
        return
    if getattr(sys, "frozen", False):
        exe = sys.executable
        bat = os.path.join(tempfile.gettempdir(), "catpilot_relance.bat")
        with open(bat, "w", encoding="mbcs" if sys.platform == "win32" else "utf-8") as f:
            f.write(_wait_lines() + f'start "" "{exe}"\ndel "%~f0"\n')
        spawn_detached(["cmd", "/c", bat])
    else:
        spawn_detached([sys.executable] + sys.argv)


def _wait_lines():
    """Attend la fin de ce processus et de son lanceur PyInstaller (qui verrouille l'exe)."""
    image = os.path.basename(sys.executable)
    out = "@echo off\n"
    for pid in sorted({os.getpid(), os.getppid()}):
        out += (f":attente{pid}\n"
                f'tasklist /FI "PID eq {pid}" /FI "IMAGENAME eq {image}" 2>nul | find " {pid} " >nul && '
                f"(ping -n 2 127.0.0.1 >nul & goto attente{pid})\n")
    return out + "ping -n 2 127.0.0.1 >nul\n"


def install_and_restart(new_exe):
    """Lance le script qui attend la fermeture, remplace l'exécutable et le relance."""
    if sys.platform != "win32":
        target = appimage_path()
        os.chmod(new_exe, 0o755)
        spawn_detached(["sh", "-c", _sh_wait() + f'mv -f "{new_exe}" "{target}" && chmod +x "{target}"\n'
                        f'exec "{target}"'])
        return
    exe = sys.executable
    bat = os.path.join(tempfile.gettempdir(), "catpilot_maj.bat")
    with open(bat, "w", encoding="mbcs" if sys.platform == "win32" else "utf-8") as f:
        f.write(_wait_lines() + f"""set essai=0
:copie
move /y "{new_exe}" "{exe}" >nul 2>&1 && goto relance
set /a essai+=1
if %essai% lss 20 (ping -n 2 127.0.0.1 >nul & goto copie)
:relance
start "" "{exe}"
del "%~f0"
""")
    spawn_detached(["cmd", "/c", bat])
