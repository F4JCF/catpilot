"""Test Windows : remplacement de l'exécutable puis relance, puis simple relance."""
import os
import shutil
import sys
import tempfile
import time

from catpilot.updater import install_and_restart, restart

LOG = r"C:\relance\log.txt"
os.makedirs(os.path.dirname(LOG), exist_ok=True)
n = len(open(LOG).read().splitlines()) if os.path.exists(LOG) else 0
with open(LOG, "a") as f:
    f.write(f"instance {n + 1} pid {os.getpid()} parent {os.getppid()} exe {sys.executable}\n")
if n == 0:
    new = os.path.join(tempfile.gettempdir(), "nouvelle.exe")
    shutil.copy(sys.executable, new)
    install_and_restart(new)
elif n == 1:
    restart()
time.sleep(1)
