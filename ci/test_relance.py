"""Test Windows : ancienne méthode de relance (0.8 à 0.13.1), pour confirmer la panne."""
import os
import shutil
import subprocess
import sys
import tempfile
import time

LOG = r"C:\relance\log.txt"
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


os.makedirs(os.path.dirname(LOG), exist_ok=True)
n = len(open(LOG).read().splitlines()) if os.path.exists(LOG) else 0
with open(LOG, "a") as f:
    f.write(f"instance {n + 1} pid {os.getpid()}\n")
if n == 0:
    new = os.path.join(tempfile.gettempdir(), "nouvelle.exe")
    shutil.copy(sys.executable, new)
    with open(new, "ab") as f:
        f.write(b"MARQUE")                    # pour savoir si l'exe a été remplacé
    install_and_restart(new)
time.sleep(1)
