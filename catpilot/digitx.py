"""Émission des modes numériques : passage en DATA, PTT, lecture sur la sortie audio USB du poste.

Avec le signal de test (sans poste), le signal émis est renvoyé dans la chute d'eau :
on peut tout essayer sans émettre.
"""
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Signal

try:
    import sounddevice as sd
except Exception:
    sd = None

DATA_MODES = ("PKTUSB", "PKTLSB", "PKTFM")
TX_RATE = 48000


class DigiTx(QObject):
    started = Signal(str)          # libellé de l'émission
    finished = Signal(str)         # message de fin (vide si normal)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.device = None
        self.gain = 0.5
        self._stop = threading.Event()
        self.busy = False

    @property
    def loopback(self):
        """Signal de test et pas de vrai poste : on se renvoie le signal."""
        wf = self.win.wf
        ctrl = self.win.ctrl
        sim = not ctrl.connected or getattr(ctrl.driver, "name", "") == "Simulateur"
        return bool(wf.test and sim)

    def rate(self):
        return self.win.wf.sr if self.loopback else TX_RATE

    def ensure_data_mode(self):
        ctrl = self.win.ctrl
        if ctrl.connected:
            st = ctrl.snapshot()
            if st.mode not in DATA_MODES:
                ctrl.set_mode("PKTFM" if st.mode in ("FM", "PKTFM") else "PKTUSB")
                return True
        return False

    def play(self, x, sr, start_at=None, label=""):
        """Émet le signal x (échantillons à sr Hz). start_at : instant (time.time()) du début du son."""
        if self.busy:
            return False
        if not self.loopback and sd is None:
            self.finished.emit("module audio indisponible")
            return False
        if not self.loopback and self.device is None:
            self.finished.emit("choisissez la sortie audio du poste (en bas du panneau)")
            return False
        self.busy = True
        self._stop.clear()
        threading.Thread(target=self._run, args=(np.asarray(x, np.float32), sr, start_at, label),
                         daemon=True).start()
        return True

    def stop(self):
        self._stop.set()
        if sd:
            try:
                sd.stop()
            except Exception:
                pass

    def _wait_until(self, t):
        while not self._stop.is_set():
            left = t - time.time()
            if left <= 0:
                return True
            time.sleep(min(left, 0.02))
        return False

    def _run(self, x, sr, start_at, label):
        ctrl = self.win.ctrl
        msg = ""
        keyed = False
        try:
            if start_at is None:
                start_at = time.time() + 0.3
            if self.ensure_data_mode():
                time.sleep(0.3)
            if not self._wait_until(start_at - 0.25):
                msg = "émission annulée"
                return
            if ctrl.connected:
                ctrl.set_ptt(True)
                keyed = True
            if not self._wait_until(start_at):
                msg = "émission annulée"
                return
            self.started.emit(label)
            dur = len(x) / sr
            if self.loopback:
                self.win.wf.inject.append([x * min(1.0, self.gain * 2), 0])
            else:
                sd.play(x * self.gain, sr, device=self.device)
            end = time.time() + dur + 0.05
            while time.time() < end and not self._stop.is_set():
                time.sleep(0.02)
            if self._stop.is_set():
                msg = "émission arrêtée"
        except Exception as e:
            msg = f"échec de l'émission : {e}"
        finally:
            try:
                if sd and not self.loopback:
                    sd.stop()
            except Exception:
                pass
            if keyed:
                ctrl.set_ptt(False)
            self.busy = False
            self.finished.emit(msg)
