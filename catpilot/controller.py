"""Contrôleur : un seul fil d'exécution possède le port série.

L'interface et le serveur TCP déposent leurs ordres ; le fil les envoie au
poste puis l'interroge en boucle et publie l'état. Les ordres répétés (molette,
curseurs) sont fusionnés : seule la dernière valeur de chaque réglage part.
Après un ordre, la valeur lue sur le poste est ignorée un court instant pour
éviter que le bouton ne « saute » en arrière.
"""
import queue
import threading
import time

from PySide6.QtCore import QObject, Signal

from .drivers.base import RigState

POLL_INTERVAL = 0.10
MAX_ERRORS = 5
HOLD = 1.2           # s pendant lesquelles une valeur réglée prime sur la lecture
CORE = ("freq", "mode", "ptt")
METERS = ("smeter", "s_text", "s_db", "po", "swr", "swr_val", "alc")


class RigController(QObject):
    state_changed = Signal(object)      # RigState
    status_changed = Signal(bool, str)  # connecté ?, message
    memories_loaded = Signal(list)
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = RigState()
        self.lock = threading.Lock()
        self.driver = None
        self.connected = False
        self._pending = {}
        self._touched = {}
        self._actions = queue.Queue()
        self._thread = None
        self._running = False
        self._power_on = False

    # --- connexion -------------------------------------------------------
    def connect_rig(self, driver, power_on=False):
        self.disconnect_rig()
        self._power_on = power_on
        driver.open()
        self.driver = driver
        self.state = RigState()
        self._pending, self._touched = {}, {}
        self._actions = queue.Queue()
        self._running = True
        self.connected = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.status_changed.emit(True, f"Connecté : {driver.name} sur {driver.port}")

    def disconnect_rig(self, power_off=False):
        was = self.connected
        self._running = False
        if self._thread:
            self._thread.join(3)
            self._thread = None
        if self.driver:
            if self.state.ptt:           # sécurité : ne jamais laisser le poste en émission
                try:
                    self.driver.set_ptt(False)
                except Exception:
                    pass
            if power_off and was:
                try:
                    self.driver.power_off()
                except Exception:
                    pass
            self.driver.close()
            self.driver = None
        self.connected = False
        if was:
            self.status_changed.emit(False, "Déconnecté")

    # --- ordres ----------------------------------------------------------
    def _set(self, key, value):
        if not self.connected:
            return False
        with self.lock:
            self._pending[key] = value
            self._touched[key] = time.monotonic()
            if key in CORE:
                setattr(self.state, key, value)
            else:
                self.state.p[key[2:]] = value
            snap = self.state.copy()
        self.state_changed.emit(snap)
        return True

    def set_freq(self, hz):
        return self._set("freq", int(hz))

    def set_mode(self, mode):
        return self._set("mode", mode)

    def set_ptt(self, on):
        return self._set("ptt", bool(on))

    def set_param(self, key, value):
        return self._set("p:" + key, value)

    def set_power(self, watts):
        return self.set_param("pwr", max(5, min(100, int(watts))))

    def action(self, name, *args):
        if self.connected:
            self._actions.put((name, args))

    def read_memories(self):
        self.action("__read_memories")

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    # --- boucle ----------------------------------------------------------
    def _send_pending(self):
        with self.lock:
            pending, self._pending = self._pending, {}
        for k, v in pending.items():
            if k == "freq":
                self.driver.set_freq(v)
            elif k == "mode":
                self.driver.set_mode(v)
            elif k == "ptt":
                self.driver.set_ptt(v)
            else:
                self.driver.set_param(k[2:], v)

    def _run_actions(self):
        while True:
            try:
                name, args = self._actions.get_nowait()
            except queue.Empty:
                return
            if name == "__read_memories":
                self.message.emit("Lecture des mémoires du poste…")
                self.memories_loaded.emit(self.driver.read_memories())
            else:
                self.driver.action(name, *args)

    def _merge(self, tmp):
        now = time.monotonic()
        with self.lock:
            fresh = lambda k: now - self._touched.get(k, 0) > HOLD and k not in self._pending
            s = self.state
            for k in CORE:
                if fresh(k):
                    setattr(s, k, getattr(tmp, k))
            for k in METERS:
                setattr(s, k, getattr(tmp, k))
            for k, v in tmp.p.items():
                if fresh("p:" + k):
                    s.p[k] = v
            s.unsupported = set(tmp.unsupported)
            return s.copy()

    def _run(self):
        errors = 0
        if self._power_on:
            self.message.emit("Allumage du poste…")
            try:
                done = self.driver.power_on()
                self.message.emit(("Poste allumé" if done else "Poste déjà allumé")
                                  + f" : {self.driver.name} sur {self.driver.port}")
            except Exception as e:
                self.message.emit(f"Allumage impossible : {e}")
        while self._running:
            try:
                self._send_pending()
                self._run_actions()
                tmp = self.snapshot()
                self.driver.poll(tmp)
                errors = 0
                self.state_changed.emit(self._merge(tmp))
            except Exception as e:
                errors += 1
                if errors >= MAX_ERRORS:
                    self._running = False
                    self.connected = False
                    self.status_changed.emit(False, f"Liaison perdue avec le poste : {e}")
                    break
            time.sleep(POLL_INTERVAL)
