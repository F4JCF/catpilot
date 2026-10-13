"""Pilotage à distance : un CAT Pilot « station » relié au poste, un CAT Pilot
« distant » ailleurs (autre pièce, autre ville), audio compris.

Liaison TCP (port 4540 par défaut) protégée par mot de passe : défi-réponse
HMAC-SHA256, le mot de passe ne circule jamais. Les échanges ne sont pas
chiffrés : pour un accès par Internet, préférez un VPN (WireGuard, Tailscale…)
à une simple redirection de port.

Trames : 1 octet de type + 4 octets de longueur + données.
  J : message JSON (ordres, état du poste)
  A : audio de réception (station -> distant), µ-law 8 kHz, 20 ms
  T : audio d'émission (distant -> station)
Sécurité : PTT coupé si le distant se déconnecte ou si son audio s'interrompt
plus de 3 s pendant l'émission.
"""
import collections
import hashlib
import hmac
import json
import os
import queue
import socket
import struct
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Signal

from .drivers.base import RigDriver, RigError

try:
    import sounddevice as sd
except Exception:
    sd = None

PORT = 4540
RATE, DEV_RATE, FRAME = 8000, 48000, 160          # 8 kHz, 20 ms


# --- audio µ-law ----------------------------------------------------------------------------
def ulaw_encode(x):
    x = np.clip(x, -1, 1)
    y = np.sign(x) * np.log1p(255 * np.abs(x)) / np.log1p(255)
    return ((y + 1) / 2 * 255).astype(np.uint8).tobytes()


def ulaw_decode(b):
    y = np.frombuffer(b, np.uint8).astype(np.float32) / 255 * 2 - 1
    return np.sign(y) * (np.expm1(np.abs(y) * np.log1p(255)) / 255)


def down6(x):
    """48 kHz -> 8 kHz (moyenne glissante puis décimation)."""
    n = len(x) // 6 * 6
    return x[:n].reshape(-1, 6).mean(axis=1)


def up6(x):
    """8 kHz -> 48 kHz par interpolation linéaire."""
    if not len(x):
        return x
    idx = np.arange(len(x) * 6) / 6
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


# --- trames -------------------------------------------------------------------------------------
def send_frame(sock, kind, payload, lock):
    data = kind + struct.pack(">I", len(payload)) + payload
    with lock:
        sock.sendall(data)


def recv_exact(sock, n):
    b = b""
    while len(b) < n:
        c = sock.recv(n - len(b))
        if not c:
            raise ConnectionError("liaison fermée")
        b += c
    return b


def recv_frame(sock):
    hdr = recv_exact(sock, 5)
    n = struct.unpack(">I", hdr[1:])[0]
    if n > 1_000_000:
        raise ConnectionError("trame invalide")
    return hdr[:1], recv_exact(sock, n)


def state_to_dict(st):
    d = {k: getattr(st, k) for k in ("freq", "mode", "ptt", "smeter", "s_text", "s_db", "po", "swr",
                                      "swr_val", "alc")}
    d["p"] = st.p
    d["unsupported"] = sorted(st.unsupported)
    return d


class AudioPipe:
    """Capture et lecture audio à 48 kHz, échange en trames de 20 ms à 8 kHz."""

    def __init__(self):
        self.inp = self.out = None
        self.play_q = collections.deque(maxlen=50)     # 1 s de tampon au plus
        self.on_frame = None

    def start(self, in_dev, out_dev):
        self.stop()
        if not sd:
            raise RuntimeError("module audio indisponible")
        buf = np.zeros(0, np.float32)

        def cap(data, *_a):
            nonlocal buf
            buf = np.concatenate([buf, down6(data[:, 0])])
            while len(buf) >= FRAME and self.on_frame:
                self.on_frame(ulaw_encode(buf[:FRAME]))
                buf = buf[FRAME:]

        pending = np.zeros(0, np.float32)

        def play(out, frames, *_a):
            nonlocal pending
            while len(pending) < frames and self.play_q:
                pending = np.concatenate([pending, up6(ulaw_decode(self.play_q.popleft()))])
            n = min(frames, len(pending))
            out[:n, 0] = pending[:n]
            out[n:, 0] = 0
            pending = pending[n:]

        if in_dev is not None:
            self.inp = sd.InputStream(device=in_dev, channels=1, samplerate=DEV_RATE, blocksize=960,
                                      dtype="float32", callback=cap)
            self.inp.start()
        if out_dev is not None:
            self.out = sd.OutputStream(device=out_dev, channels=1, samplerate=DEV_RATE, blocksize=960,
                                       dtype="float32", callback=play)
            self.out.start()

    def play(self, ulaw):
        self.play_q.append(ulaw)

    def stop(self):
        for s in (self.inp, self.out):
            if s:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
        self.inp = self.out = None
        self.play_q.clear()


# --- côté station ------------------------------------------------------------------------------
class RemoteServer(QObject):
    clients_changed = Signal(int)
    message = Signal(str)

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.password = ""
        self._srv = None
        self._run = False
        self.clients = []
        self.lock = threading.Lock()
        self.fails = {}
        self.audio = AudioPipe()
        self.audio.on_frame = self._broadcast_audio
        self.tx_owner = None
        self.last_tx_audio = 0.0
        ctrl.state_changed.connect(self._on_state)
        self._last_sent = 0.0

    def start(self, port, password, in_dev=None, out_dev=None):
        if len(password) < 6:
            raise ValueError("mot de passe trop court (6 caractères au moins)")
        self.stop()
        self.password = password
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(4)
        s.settimeout(1.0)
        self._srv, self._run = s, True
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()
        if in_dev is not None or out_dev is not None:
            try:
                self.audio.start(in_dev, out_dev)
            except Exception as e:
                self.message.emit(f"Audio distant indisponible : {e}")

    def stop(self):
        self._run = False
        self.audio.stop()
        if self._srv:
            self._srv.close()
            self._srv = None
        for c in list(self.clients):
            try:
                c[0].close()
            except OSError:
                pass
        self.clients = []
        self.clients_changed.emit(0)

    def _accept(self):
        while self._run:
            try:
                conn, addr = self._srv.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._client, args=(conn, addr), daemon=True).start()

    def _client(self, conn, addr):
        ip = addr[0]
        lock = threading.Lock()
        n_fail, until = self.fails.get(ip, (0, 0))
        if time.time() < until:
            conn.close()
            return
        try:
            conn.settimeout(10)
            nonce = os.urandom(16)
            send_frame(conn, b"J", json.dumps({"op": "challenge", "nonce": nonce.hex()}).encode(), lock)
            kind, data = recv_frame(conn)
            msg = json.loads(data)
            good = hmac.new(self.password.encode(), nonce, hashlib.sha256).hexdigest()
            if kind != b"J" or not hmac.compare_digest(str(msg.get("auth", "")), good):
                n_fail += 1
                self.fails[ip] = (n_fail, time.time() + 600 if n_fail >= 5 else 0)
                send_frame(conn, b"J", json.dumps({"op": "denied"}).encode(), lock)
                self.message.emit(f"Accès distant refusé à {ip} (mot de passe)")
                conn.close()
                return
            self.fails.pop(ip, None)
            drv = self.ctrl.driver
            info = {"op": "info", "rig": drv.name if drv else "?",
                    "modes": list(drv.modes) if drv else [],
                    **{k: getattr(drv, k, None) for k in ("max_freq", "min_freq", "max_power", "has_c4fm",
                                                         "has_qmb", "has_usb_audio")}}
            send_frame(conn, b"J", json.dumps(info).encode(), lock)
            conn.settimeout(None)
        except Exception:
            conn.close()
            return
        entry = (conn, lock, ip)
        with self.lock:
            self.clients.append(entry)
        self.clients_changed.emit(len(self.clients))
        self.message.emit(f"Opérateur distant connecté depuis {ip}")
        try:
            while self._run:
                kind, data = recv_frame(conn)
                if kind == b"J":
                    self._command(json.loads(data), entry)
                elif kind == b"T" and self.tx_owner is entry:
                    self.last_tx_audio = time.monotonic()
                    self.audio.play(data)
        except Exception:
            pass
        finally:
            with self.lock:
                if entry in self.clients:
                    self.clients.remove(entry)
            if self.tx_owner is entry:          # parti en pleine émission : on coupe
                self.ctrl.set_ptt(False)
                self.tx_owner = None
            conn.close()
            self.clients_changed.emit(len(self.clients))
            self.message.emit(f"Opérateur distant {ip} déconnecté")

    def _command(self, m, entry):
        op = m.get("op")
        c = self.ctrl
        if op == "set_freq":
            c.set_freq(int(m["v"]))
        elif op == "set_mode":
            c.set_mode(str(m["v"]))
        elif op == "set_ptt":
            on = bool(m["v"])
            self.tx_owner = entry if on else None
            self.last_tx_audio = time.monotonic()
            c.set_ptt(on)
        elif op == "set_param":
            c.set_param(str(m["k"]), m["v"])
        elif op == "action" and m.get("name") not in ("__job",):
            c.action(str(m["name"]), *m.get("args", []))

    def _watchdog(self):
        while self._run:
            time.sleep(0.5)
            if self.tx_owner and self.audio.out and time.monotonic() - self.last_tx_audio > 3:
                self.ctrl.set_ptt(False)
                self.tx_owner = None
                self.message.emit("Émission distante coupée : plus d'audio reçu")

    def _on_state(self, st):
        now = time.monotonic()
        if not self.clients or now - self._last_sent < 0.2:
            return
        self._last_sent = now
        data = json.dumps({"op": "state", **state_to_dict(st)}).encode()
        for conn, lock, _ip in list(self.clients):
            try:
                send_frame(conn, b"J", data, lock)
            except OSError:
                pass

    def _broadcast_audio(self, ulaw):
        for conn, lock, _ip in list(self.clients):
            try:
                send_frame(conn, b"A", ulaw, lock)
            except OSError:
                pass


# --- côté opérateur distant : un « pilote » comme les autres ------------------------------------
class RemoteDriver(RigDriver):
    name = "Poste distant (CAT Pilot)"
    modes = ["USB", "LSB", "CW", "CWR", "AM", "FM", "RTTY", "RTTYR", "PKTUSB", "PKTLSB", "PKTFM"]
    default_baud = 0
    is_remote = True
    password = ""
    audio_devices = (None, None)            # (micro du PC, haut-parleurs du PC)

    def open(self):
        host, _, port = (self.port or "").rpartition(":")
        if not host:
            host, port = self.port, PORT
        self.sock = socket.create_connection((host, int(port or PORT)), timeout=8)
        self.lock = threading.Lock()
        kind, data = recv_frame(self.sock)
        ch = json.loads(data)
        if ch.get("op") != "challenge":
            raise RigError("ce n'est pas une station CAT Pilot")
        resp = hmac.new(self.password.encode(), bytes.fromhex(ch["nonce"]), hashlib.sha256).hexdigest()
        send_frame(self.sock, b"J", json.dumps({"op": "auth", "auth": resp}).encode(), self.lock)
        kind, data = recv_frame(self.sock)
        info = json.loads(data)
        if info.get("op") != "info":
            self.sock.close()
            raise RigError("mot de passe refusé par la station")
        self.name = f"{info.get('rig', '?')} (à distance)"
        self.modes = info.get("modes") or self.modes
        for k in ("max_freq", "min_freq", "max_power", "has_c4fm", "has_qmb", "has_usb_audio"):
            if info.get(k) is not None:
                setattr(self, k, info[k])
        self.state = None
        self.alive = True
        self.audio = AudioPipe()
        self.audio.on_frame = self._send_audio
        self.ptt = False
        self.sock.settimeout(None)
        threading.Thread(target=self._reader, daemon=True).start()
        if any(d is not None for d in self.audio_devices):
            try:
                self.audio.start(*self.audio_devices)
            except Exception:
                pass

    def _reader(self):
        try:
            while self.alive:
                kind, data = recv_frame(self.sock)
                if kind == b"J":
                    m = json.loads(data)
                    if m.get("op") == "state":
                        self.state = m
                elif kind == b"A":
                    self.audio.play(data)
        except Exception:
            self.alive = False

    def _send(self, **m):
        try:
            send_frame(self.sock, b"J", json.dumps(m).encode(), self.lock)
        except OSError as e:
            self.alive = False
            raise RigError(f"liaison distante perdue : {e}")

    def _send_audio(self, ulaw):
        if self.ptt and self.alive:
            try:
                send_frame(self.sock, b"T", ulaw, self.lock)
            except OSError:
                pass

    def poll(self, st):
        time.sleep(0.05)
        if not self.alive:
            raise RigError("liaison distante perdue")
        m = self.state
        if not m:
            return
        for k in ("freq", "mode", "ptt", "smeter", "s_text", "s_db", "po", "swr", "swr_val", "alc"):
            setattr(st, k, m[k])
        st.p.update(m.get("p", {}))
        st.unsupported = set(m.get("unsupported", []))

    def set_freq(self, hz):
        self._send(op="set_freq", v=int(hz))

    def set_mode(self, mode):
        self._send(op="set_mode", v=mode)

    def set_ptt(self, on):
        self.ptt = bool(on)
        self._send(op="set_ptt", v=bool(on))

    def set_param(self, key, value):
        self._send(op="set_param", k=key, v=value)

    def action(self, name, *args):
        self._send(op="action", name=name, args=list(args))

    def close(self):
        self.alive = False
        try:
            self.audio.stop()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def read_memories(self, progress=None):
        raise RigError("les mémoires se lisent depuis la station elle-même")

    def write_memories(self, mems, template, progress=None):
        raise RigError("les mémoires s'écrivent depuis la station elle-même")

    def read_menus(self, progress=None):
        raise RigError("les menus se sauvegardent depuis la station elle-même")

    def write_menus(self, menus, progress=None):
        raise RigError("les menus se restaurent depuis la station elle-même")


# --- panneau ------------------------------------------------------------------------------------
from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox, QComboBox, QDockWidget, QFormLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from .voicekeyer import guess_radio_output, list_devices  # noqa: E402
from .waterfall import guess_radio_input  # noqa: E402


class RemoteDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Accès à distance", win)
        self.win = win
        self.setObjectName("remotedock")
        s = win.settings
        self.server = RemoteServer(win.ctrl)
        self.server.clients_changed.connect(lambda n: self.lb_srv.setText(
            f"{n} opérateur(s) distant(s) connecté(s)" if n else "En attente de connexion"))
        self.server.message.connect(win.statusBar().showMessage)
        ins, outs = list_devices("input"), list_devices("output")

        def combo(devs, key, guess):
            c = QComboBox()
            c.addItem("Pas d'audio", None)
            for i, label in devs:
                c.addItem(label, i)
            j = c.findText(s.value(key, ""))
            c.setCurrentIndex(j if j >= 0 else max(0, c.findData(guess)))
            return c

        w = QWidget()
        v = QVBoxLayout(w)
        t = QLabel("Ce PC est relié au poste (station)")
        t.setObjectName("ptitle")
        v.addWidget(t)
        f = QFormLayout()
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(int(s.value("remote_port", PORT)))
        self.ed_spass = QLineEdit(s.value("remote_srv_pass", ""))
        self.ed_spass.setEchoMode(QLineEdit.Password)
        self.ed_spass.setPlaceholderText("6 caractères au moins")
        self.cb_rin = combo(ins, "remote_rin", guess_radio_input([(i, l) for i, l in ins]))
        self.cb_rout = combo(outs, "remote_rout", guess_radio_output(outs))
        self.ck_srv = QCheckBox("Autoriser l'accès à distance")
        self.ck_srv.toggled.connect(self.toggle_server)
        f.addRow("Port TCP", self.sp_port)
        f.addRow("Mot de passe", self.ed_spass)
        f.addRow("Audio venant du poste", self.cb_rin)
        f.addRow("Audio vers le poste", self.cb_rout)
        f.addRow(self.ck_srv)
        v.addLayout(f)
        self.lb_srv = QLabel("Arrêté")
        self.lb_srv.setObjectName("value")
        v.addWidget(self.lb_srv)

        t = QLabel("Ce PC pilote une station distante")
        t.setObjectName("ptitle")
        v.addWidget(t)
        f = QFormLayout()
        self.ed_host = QLineEdit(s.value("remote_host", ""))
        self.ed_host.setPlaceholderText("adresse:4540 (IP, nom ou adresse VPN)")
        self.ed_cpass = QLineEdit(s.value("remote_cli_pass", ""))
        self.ed_cpass.setEchoMode(QLineEdit.Password)
        self.cb_mic = combo(ins, "remote_mic", None)
        self.cb_spk = combo(outs, "remote_spk", None)
        f.addRow("Station", self.ed_host)
        f.addRow("Mot de passe", self.ed_cpass)
        f.addRow("Micro de ce PC", self.cb_mic)
        f.addRow("Haut-parleurs de ce PC", self.cb_spk)
        v.addLayout(f)
        hint = QLabel("Puis choisissez « Poste distant (CAT Pilot) » dans la liste des postes et cliquez sur "
                      "Connecter. Pour Internet, passez de préférence par un VPN (WireGuard, Tailscale).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        if not sd:
            t = QLabel("Module audio indisponible : pilotage sans audio.")
            t.setObjectName("hint")
            v.addWidget(t)
        v.addStretch()
        self.setWidget(w)

    def toggle_server(self, on):
        if not on:
            self.server.stop()
            self.lb_srv.setText("Arrêté")
            return
        try:
            self.server.start(self.sp_port.value(), self.ed_spass.text(), self.cb_rin.currentData(),
                              self.cb_rout.currentData())
        except Exception as e:
            self.lb_srv.setText(f"Impossible : {e}")
            self.ck_srv.blockSignals(True)
            self.ck_srv.setChecked(False)
            self.ck_srv.blockSignals(False)
            return
        self.lb_srv.setText(f"En attente de connexion sur le port {self.sp_port.value()}")

    def prepare_client(self):
        """Avant la connexion d'un « Poste distant » : adresse, mot de passe, audio."""
        RemoteDriver.password = self.ed_cpass.text()
        RemoteDriver.audio_devices = (self.cb_mic.currentData(), self.cb_spk.currentData())
        return self.ed_host.text().strip()

    def save_settings(self, s):
        s.setValue("remote_port", self.sp_port.value())
        s.setValue("remote_srv_pass", self.ed_spass.text())
        s.setValue("remote_rin", self.cb_rin.currentText())
        s.setValue("remote_rout", self.cb_rout.currentText())
        s.setValue("remote_host", self.ed_host.text())
        s.setValue("remote_cli_pass", self.ed_cpass.text())
        s.setValue("remote_mic", self.cb_mic.currentText())
        s.setValue("remote_spk", self.cb_spk.currentText())
        self.server.stop()
