"""Linux : raccourcis « CAT Pilot » dans le menu des applications et sur le Bureau.

Au premier lancement de la version Linux (AppImage ou dossier tar.gz), on crée :
- ~/.local/share/applications/catpilot.desktop (menu des applications) ;
- catpilot.desktop sur le Bureau (dossier donné par xdg-user-dir : ~/Bureau en français),
  marqué exécutable et « de confiance » pour qu'il se lance d'un double-clic (Mint, Ubuntu…).
Les lancements suivants remettent le chemin à jour si le fichier a été déplacé.
Si l'utilisateur supprime l'icône du Bureau, elle n'est pas recréée.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "catpilot"
TITLE = "CAT Pilot"
COMMENT = "Pilotage CAT des postes Yaesu et Icom, carnet, modes numériques"


def _executable():
    p = os.environ.get("APPIMAGE", "")
    if p and os.path.isfile(p):
        return p
    return sys.executable if getattr(sys, "frozen", False) else ""


def _data_dir():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def desktop_dir():
    """Dossier du Bureau (~/Bureau, ~/Desktop…), ou None."""
    home = Path.home()
    d = ""
    try:
        d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True,
                           timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if not d:
        try:
            cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    d = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home))
        except OSError:
            pass
    if not d:
        for name in ("Bureau", "Desktop"):
            if (home / name).is_dir():
                d = str(home / name)
                break
    if not d or Path(d).resolve() == home.resolve() or not Path(d).is_dir():
        return None
    return Path(d)


def _entry(exe, icon):
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={TITLE}\nComment={COMMENT}\n"
            f"Exec=\"{exe}\"\nIcon={icon}\nTerminal=false\n"
            "Categories=HamRadio;Network;\n")


def _write(path, content):
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    if shutil.which("gio"):              # Nautilus / Nemo : lanceur « de confiance »
        try:
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                           capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def _make_icon(icon_path):
    """Icône 256 px : celle de l'AppImage, sinon tirée de catpilot.ico."""
    appdir = os.environ.get("APPDIR", "")
    src = os.path.join(appdir, "catpilot.png") if appdir else ""
    if src and os.path.isfile(src):
        shutil.copyfile(src, icon_path)
        return
    from PySide6.QtGui import QIcon
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
    ico = os.path.join(base, "assets", "catpilot.ico")
    pm = QIcon(ico).pixmap(256, 256)
    if not pm.isNull():
        pm.save(str(icon_path), "PNG")


def install():
    """À appeler une fois l'application Qt créée. Ne fait rien hors Linux / hors version compilée."""
    if not sys.platform.startswith("linux"):
        return
    exe = _executable()
    if not exe:
        return
    try:
        data = _data_dir()
        icon_dir = data / "icons/hicolor/256x256/apps"
        icon_dir.mkdir(parents=True, exist_ok=True)
        icon = icon_dir / f"{NAME}.png"
        if not icon.exists():
            _make_icon(icon)
        content = _entry(exe, icon)

        apps = data / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        _write(apps / f"{NAME}.desktop", content)

        marker = data / "CATPilot" / "icone-bureau-creee"
        desk = desktop_dir()
        if desk:
            target = desk / f"{NAME}.desktop"
            if target.exists():
                _write(target, content)          # chemin remis à jour si le fichier a bougé
            elif not marker.exists():
                _write(target, content)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("1", encoding="utf-8")
    except Exception:
        pass
