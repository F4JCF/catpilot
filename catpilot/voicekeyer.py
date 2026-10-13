"""Enregistreur de messages vocaux (« voice keyer »).

On enregistre des messages au micro du PC (« CQ CQ de F4JCF… »), puis on les
émet d'un clic : CAT Pilot passe le poste en émission et joue le fichier sur
la sortie audio USB du poste. Pour que le poste prenne sa modulation sur
l'USB, le mode bascule par défaut en DATA pendant le message (DATA-U pour
USB, etc.), puis revient au mode d'origine.
"""
import json
import os
import threading
import time
import wave

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

try:
    import sounddevice as sd
except Exception:
    sd = None

SLOTS = 6
RATE = 48000
DATA_OF = {"USB": "PKTUSB", "LSB": "PKTLSB", "FM": "PKTFM"}


def messages_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot", "messages")
    os.makedirs(d, exist_ok=True)
    return d


def list_devices(kind):
    """kind = 'input' ou 'output' : [(index, libellé)]."""
    if not sd:
        return []
    out = []
    try:
        apis = sd.query_hostapis()
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        for i, d in enumerate(sd.query_devices()):
            if d[key] > 0:
                out.append((i, f'{d["name"]} ({apis[d["hostapi"]]["name"]})'))
    except Exception:
        pass
    return out


def guess_radio_output(devs):
    best = None
    for i, label in devs:
        low = label.lower()
        if "codec" in low:
            if "mme" in low:
                return i
            best = i if best is None else best
    return best


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2" if sw == 2 else np.uint8)
    x = data.astype(np.float32) / (32768.0 if sw == 2 else 128.0)
    if sw != 2:
        x -= 1.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


class Player(QObject):
    """Émission d'un message dans un fil séparé : PTT, lecture, fin de PTT."""
    finished = Signal(str)

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self._stop = threading.Event()
        self.busy = False

    def play(self, path, device, gain, to_data):
        self._stop.clear()
        self.busy = True
        threading.Thread(target=self._run, args=(path, device, gain, to_data), daemon=True).start()

    def stop(self):
        self._stop.set()
        if sd:
            try:
                sd.stop()
            except Exception:
                pass

    def _run(self, path, device, gain, to_data):
        msg = "Message émis"
        st = self.ctrl.snapshot()
        mode0 = st.mode
        switched = False
        try:
            x, sr = read_wav(path)
            if to_data and mode0 in DATA_OF:
                self.ctrl.set_mode(DATA_OF[mode0])
                switched = True
                time.sleep(0.35)
            self.ctrl.set_ptt(True)
            time.sleep(0.3)                       # laisser le relais d'émission basculer
            if sd is None:
                raise RuntimeError("module audio indisponible")
            sd.play(x * gain, sr, device=device)
            end = time.monotonic() + len(x) / sr + 0.2
            while time.monotonic() < end and not self._stop.is_set():
                time.sleep(0.05)
            if self._stop.is_set():
                msg = "Message interrompu"
        except Exception as e:
            msg = f"Échec de l'émission du message : {e}"
        finally:
            try:
                if sd:
                    sd.stop()
            except Exception:
                pass
            self.ctrl.set_ptt(False)
            if switched:
                time.sleep(0.2)
                self.ctrl.set_mode(mode0)
            self.busy = False
            self.finished.emit(msg)


class VoiceDock(QDockWidget):
    def __init__(self, win):
        super().__init__("Messages vocaux", win)
        self.win, self.ctrl = win, win.ctrl
        self.setObjectName("voicedock")
        s = win.settings
        self.names = json.loads(s.value("dvk_names", "null") or "null") or \
            ["CQ", "Indicatif", "Report 59", "Merci 73", "QRZ ?", "Message 6"]
        self.player = Player(self.ctrl)
        self.player.finished.connect(self._done)
        self.rec_slot = None
        self.rec_buf = []
        self.rec_stream = None
        self.repeat_slot = None
        self.repeat_timer = QTimer(self)
        self.repeat_timer.setSingleShot(True)
        self.repeat_timer.timeout.connect(self._repeat)

        w = QWidget()
        v = QVBoxLayout(w)
        g = QGridLayout()
        g.addWidget(QLabel("Micro du PC"), 0, 0)
        self.cb_in = QComboBox()
        for i, label in list_devices("input"):
            self.cb_in.addItem(label, i)
        g.addWidget(self.cb_in, 0, 1)
        g.addWidget(QLabel("Sortie vers le poste"), 1, 0)
        self.cb_out = QComboBox()
        outs = list_devices("output")
        for i, label in outs:
            self.cb_out.addItem(label, i)
        j = self.cb_out.findData(guess_radio_output(outs))
        if j >= 0:
            self.cb_out.setCurrentIndex(j)
        g.addWidget(self.cb_out, 1, 1)
        for cb, key in ((self.cb_in, "dvk_in"), (self.cb_out, "dvk_out")):
            k = cb.findText(s.value(key, ""))
            if k >= 0:
                cb.setCurrentIndex(k)
        g.addWidget(QLabel("Niveau d'émission"), 2, 0)
        self.sl_gain = QSlider(Qt.Horizontal)
        self.sl_gain.setRange(5, 100)
        self.sl_gain.setValue(int(s.value("dvk_gain", 50)))
        self.sl_gain.setToolTip("Réglez pour que l'ALC bouge à peine pendant le message")
        g.addWidget(self.sl_gain, 2, 1)
        v.addLayout(g)
        if not sd:
            t = QLabel("Module audio indisponible sur cet ordinateur.")
            t.setObjectName("hint")
            v.addWidget(t)

        self.ck_data = QCheckBox("Passer en DATA pendant le message (modulation par l'USB)")
        self.ck_data.setChecked(s.value("dvk_data", "true") == "true")
        self.ck_data.setToolTip("Le poste prend sa modulation sur l'USB en mode DATA. Sans cette option, "
                                "réglez la source de modulation de la BLU sur USB dans les menus du poste.")
        v.addWidget(self.ck_data)
        h = QHBoxLayout()
        h.addWidget(QLabel("Répéter toutes les"))
        self.sp_rep = QSpinBox()
        self.sp_rep.setRange(0, 300)
        self.sp_rep.setSuffix(" s")
        self.sp_rep.setSpecialValueText("non")
        self.sp_rep.setValue(int(s.value("dvk_repeat", 0)))
        self.sp_rep.setToolTip("Appel en boucle : le message repart après ce délai d'écoute. "
                               "Toute action sur MOX ou Échap arrête la boucle.")
        h.addWidget(self.sp_rep)
        h.addStretch()
        v.addLayout(h)

        mg = QGridLayout()
        self.lb_names, self.b_rec, self.b_send = [], [], []
        for i in range(SLOTS):
            name = QPushButton(self.names[i] if i < len(self.names) else f"Message {i + 1}")
            name.setToolTip("Clic : renommer")
            name.clicked.connect(lambda _c=False, n=i: self.rename(n))
            rec = QPushButton("● Enr.")
            rec.setCheckable(True)
            rec.setToolTip("Enregistrer au micro du PC ; recliquer pour arrêter")
            rec.toggled.connect(lambda on, n=i: self.record(n, on))
            listen = QPushButton("Écouter")
            listen.clicked.connect(lambda _c=False, n=i: self.listen(n))
            send = QPushButton(f"Émettre F{i + 1}" if i < 4 else "Émettre")
            send.setToolTip("Émettre ce message (Ctrl+F1 à Ctrl+F4 pour les quatre premiers)")
            send.clicked.connect(lambda _c=False, n=i: self.send(n))
            for c, wdg in enumerate((name, rec, listen, send)):
                mg.addWidget(wdg, i, c)
            self.lb_names.append(name)
            self.b_rec.append(rec)
            self.b_send.append(send)
        v.addLayout(mg)
        b = QPushButton("Stop")
        b.clicked.connect(self.stop)
        v.addWidget(b)
        self.lb = QLabel("")
        self.lb.setObjectName("value")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        v.addStretch()
        self.setWidget(w)
        self._refresh()

    def path(self, n):
        return os.path.join(messages_dir(), f"message{n + 1}.wav")

    def _refresh(self):
        for i in range(SLOTS):
            ok = os.path.exists(self.path(i))
            self.b_send[i].setEnabled(ok)

    def save_settings(self, s):
        s.setValue("dvk_names", json.dumps([b.text() for b in self.lb_names]))
        s.setValue("dvk_in", self.cb_in.currentText())
        s.setValue("dvk_out", self.cb_out.currentText())
        s.setValue("dvk_gain", self.sl_gain.value())
        s.setValue("dvk_data", "true" if self.ck_data.isChecked() else "false")
        s.setValue("dvk_repeat", self.sp_rep.value())
        self.stop()

    def rename(self, n):
        name, ok = QInputDialog.getText(self, "Nom du message", "Nom :", text=self.lb_names[n].text())
        if ok and name.strip():
            self.lb_names[n].setText(name.strip()[:20])

    # --- enregistrement ---------------------------------------------------------------
    def record(self, n, on):
        if on:
            if not sd or self.cb_in.currentData() is None:
                self.lb.setText("Aucun micro disponible")
                self._uncheck(self.b_rec[n])
                return
            for i, b in enumerate(self.b_rec):
                if i != n and b.isChecked():
                    self._uncheck(b)
            self.rec_slot, self.rec_buf = n, []
            try:
                self.rec_stream = sd.InputStream(device=self.cb_in.currentData(), channels=1,
                                                 samplerate=RATE, dtype="float32",
                                                 callback=lambda d, *_a: self.rec_buf.append(d[:, 0].copy()))
                self.rec_stream.start()
            except Exception as e:
                self.lb.setText(f"Micro impossible à ouvrir : {e}")
                self._uncheck(self.b_rec[n])
                return
            self.lb.setText(f"Enregistrement de « {self.lb_names[n].text()} »… recliquez pour arrêter")
        elif self.rec_slot == n and self.rec_stream:
            self.rec_stream.stop()
            self.rec_stream.close()
            self.rec_stream = None
            x = np.concatenate(self.rec_buf) if self.rec_buf else np.zeros(0, np.float32)
            if len(x) < RATE // 4:
                self.lb.setText("Enregistrement trop court, rien n'a été gardé")
                return
            peak = float(np.max(np.abs(x))) or 1.0
            write_wav(self.path(n), x * (0.9 / peak), RATE)      # normalisation
            self.lb.setText(f"« {self.lb_names[n].text()} » enregistré ({len(x) / RATE:.1f} s)")
            self._refresh()

    def listen(self, n):
        if not sd or not os.path.exists(self.path(n)):
            return
        x, sr = read_wav(self.path(n))
        sd.play(x * 0.8, sr)            # sortie audio par défaut du PC, sans émettre

    # --- émission ---------------------------------------------------------------------
    def send(self, n):
        if not os.path.exists(self.path(n)):
            self.lb.setText("Ce message n'est pas encore enregistré")
            return
        if not self.ctrl.connected:
            self.lb.setText("Pas de poste connecté")
            return
        if self.player.busy or self.ctrl.snapshot().ptt:
            self.lb.setText("Émission déjà en cours")
            return
        if self.cb_out.currentData() is None:
            QMessageBox.warning(self, "Messages vocaux", "Choisissez la sortie audio reliée au poste.")
            return
        self.repeat_slot = n if self.sp_rep.value() else None
        self.lb.setText(f"Émission de « {self.lb_names[n].text()} »")
        self.player.play(self.path(n), self.cb_out.currentData(), self.sl_gain.value() / 100,
                         self.ck_data.isChecked())

    def _done(self, msg):
        self.lb.setText(msg)
        if self.repeat_slot is not None and msg == "Message émis":
            self.lb.setText(f"{msg} — reprise dans {self.sp_rep.value()} s (Échap pour arrêter)")
            self.repeat_timer.start(self.sp_rep.value() * 1000)

    def _repeat(self):
        st = self.ctrl.snapshot()
        if self.repeat_slot is None or not self.ctrl.connected or st.ptt:
            self.repeat_slot = None
            return
        self.send(self.repeat_slot)

    def stop(self):
        self.repeat_slot = None
        self.repeat_timer.stop()
        if self.player.busy:
            self.player.stop()

    @staticmethod
    def _uncheck(b):
        b.blockSignals(True)
        b.setChecked(False)
        b.blockSignals(False)
