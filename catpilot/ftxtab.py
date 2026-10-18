"""Onglet FT8 / FT4 du panneau « Numérique » : décodage des créneaux, séquence de QSO, émission.

Double-clic sur un CQ : CAT Pilot répond et mène le QSO jusqu'au 73, puis le note dans le carnet.
Avec le signal de test (sans poste), une petite bande simulée répond aux appels.
"""
import collections
import datetime
import math
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import adif, cty, ftx
from .ftxqso import FtxQso


class FtxEngine(QObject):
    """Garde l'audio reçu avec son heure, et décode chaque créneau à la fin."""
    decoded = Signal(object, float, str)       # décodages, début du créneau (epoch), mode

    def __init__(self):
        super().__init__()
        self.sr = 0
        self.chunks = collections.deque()       # (indice du 1er échantillon, tableau)
        self.total = 0
        self.anchor = None                      # heure (epoch) de l'échantillon 0
        self.busy = False

    def feed(self, x, sr):
        now = time.time()
        if sr != self.sr:
            self.sr, self.total, self.anchor = sr, 0, None
            self.chunks.clear()
        self.chunks.append((self.total, np.asarray(x, np.float32)))
        self.total += len(x)
        est = now - self.total / sr
        # le plus petit retard observé est le bon ; on suit lentement la dérive de la carte son
        if self.anchor is None or est < self.anchor or est - self.anchor > 1.0:
            self.anchor = est
        else:
            self.anchor += 2e-5
        while self.chunks and self.total - self.chunks[0][0] > sr * 35:
            self.chunks.popleft()

    def extract(self, t0, t1):
        if self.anchor is None or not self.sr:
            return None
        i0 = int(round((t0 - self.anchor) * self.sr))
        n = int(round((t1 - t0) * self.sr))
        out = np.zeros(n, np.float32)
        got = 0
        for start, arr in self.chunks:
            a, b = max(i0, start), min(i0 + n, start + len(arr))
            if a < b:
                out[a - i0:b - i0] = arr[a - start:b - start]
                got += b - a
        return out if got > n * 0.6 else None

    def decode_slot(self, t_slot, mode):
        slot = ftx.MODES[mode]["slot"]
        x = self.extract(t_slot, t_slot + slot - 0.3)
        if x is None:
            self.decoded.emit([], t_slot, mode)
            return
        self.busy = True
        sr = self.sr

        def run():
            try:
                res = ftx.decode(x, sr, mode)
            except Exception:
                res = []
            self.decoded.emit(res, t_slot, mode)       # busy est remis à zéro par l'onglet
        threading.Thread(target=run, daemon=True).start()


class SimBand:
    """Bande simulée (avec le signal de test) : quelques stations, dont une qui répond."""
    NOISE_2500 = 0.02 ** 2 * 2500 / 6000      # bruit du signal de test dans 2 500 Hz

    def __init__(self, tab):
        self.tab = tab
        self.pending = []                       # messages à émettre au prochain créneau

    def _inject(self, text, f, snr, mode):
        wf = self.tab.win.wf
        try:
            sig = ftx.synth(ftx.tones(text, mode), f, wf.sr, mode, amp=1.0)
        except Exception:
            return
        amp = math.sqrt(2 * self.NOISE_2500 * 10 ** (snr / 10))
        wf.inject.append([sig, 0, amp])

    def slot_start(self, idx, mode):
        me = self.tab.mycall()
        even = idx % 2 == 0
        replies = [p for p in self.pending if p[0] == idx]
        self.pending = [p for p in self.pending if p[0] > idx]
        busy = {r[1] for r in replies}
        for _i, who, text, f, snr in replies:
            self._inject(text, f, snr, mode)
        if even:
            if "DL1ABC" not in busy:
                self._inject("CQ DL1ABC JO50", 1210, -8, mode)
            self._inject("CQ POTA K1ABC FN42", 2110, -15, mode)
        else:
            if "EA8AB" not in busy:
                self._inject("CQ EA8AB IL18", 810, -12, mode)
            self._inject("G4XYZ OK1ABC JO70", 1610, -4, mode)
        if not me:
            return

    def heard(self, text, tx_idx):
        """Notre émission (créneau tx_idx) : la station simulée concernée répond au créneau suivant."""
        me = self.tab.mycall()
        p = ftx.parse(text)
        to = p["to"]
        stations = {"DL1ABC": (1210, -8, "JO50"), "EA8AB": (810, -12, "IL18"), "OK1XYZ": (1430, -7, "JO70")}
        if p["cq"]:
            self.pending.append((tx_idx + 1, "OK1XYZ", f"{me} OK1XYZ JO70", 1430, -7))
            return
        if to not in stations:
            return
        f, snr, grid = stations[to]
        if p["grid"]:
            self.pending.append((tx_idx + 1, to, f"{me} {to} -08", f, snr))
        elif p["report"] and not p["report"].startswith("R"):
            self.pending.append((tx_idx + 1, to, f"{me} {to} R-03", f, snr))
        elif p["report"].startswith("R"):
            self.pending.append((tx_idx + 1, to, f"{me} {to} RR73", f, snr))
        elif p["rr73"] == "RR73":
            self.pending.append((tx_idx + 1, to, f"{me} {to} 73", f, snr))


class FtxTab(QWidget):
    COLS = ["UTC", "dB", "DT", "Hz", "Message", "Pays", "Distance"]

    def __init__(self, dock):
        super().__init__()
        self.dock, self.win = dock, dock.win
        s = self.win.settings
        self.engine = FtxEngine()
        self.engine.decoded.connect(self.on_decoded)
        self.qso = FtxQso()
        self.sim = SimBand(self)
        self.mode = s.value("ftx_mode", "FT8")
        self.rx_hz = float(s.value("ftx_rx", 1500))
        self.tx_hz = float(s.value("ftx_tx", 1500))
        self.tx_on = False
        self.tx_parity = 0
        self.decoded_slots = set()
        self.tx_slots = set()
        self.scheduled = set()
        self.sim_slots = set()
        self.last_slot = None
        self.decodes = []
        self.qso_start = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        h = QHBoxLayout()
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["FT8", "FT4"])
        self.cb_mode.setCurrentText(self.mode)
        self.cb_mode.currentTextChanged.connect(self.set_mode)
        h.addWidget(self.cb_mode)
        self.cb_band = QComboBox()
        self._fill_bands()
        h.addWidget(self.cb_band)
        b = QPushButton("Aller")
        b.setToolTip("Règle le poste sur la fréquence FT8/FT4 de la bande, en DATA-U")
        b.clicked.connect(self.goto_band)
        h.addWidget(b)
        self.lb_clock = QLabel("")
        self.lb_clock.setObjectName("value")
        h.addWidget(self.lb_clock)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(8)
        self.bar.setRange(0, 1000)
        h.addWidget(self.bar, 1)
        v.addLayout(h)

        split = QSplitter(Qt.Vertical)
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        self.tbl.setToolTip("Double-clic sur un CQ (ou un message qui vous est adressé) : CAT Pilot répond "
                            "et mène le QSO.\nVert : CQ · rouge : pour vous · orange : nouveau pays · gris : déjà contacté")
        self.tbl.cellDoubleClicked.connect(self.on_double_click)
        split.addWidget(self.tbl)
        self.ex = QPlainTextEdit()
        self.ex.setReadOnly(True)
        self.ex.setMaximumBlockCount(300)
        self.ex.setPlaceholderText("Vos échanges (émis et reçus) s'affichent ici")
        split.addWidget(self.ex)
        split.setSizes([300, 90])
        v.addWidget(split, 1)

        g = QGridLayout()
        g.addWidget(QLabel("Corresp."), 0, 0)
        self.ed_dx = QLineEdit()
        self.ed_dx.setMaximumWidth(110)
        self.ed_dx.editingFinished.connect(self._dx_edited)
        g.addWidget(self.ed_dx, 0, 1)
        g.addWidget(QLabel("Loc."), 0, 2)
        self.ed_grid = QLineEdit()
        self.ed_grid.setMaximumWidth(70)
        g.addWidget(self.ed_grid, 0, 3)
        g.addWidget(QLabel("Report"), 0, 4)
        self.sp_rpt = QSpinBox()
        self.sp_rpt.setRange(-30, 30)
        self.sp_rpt.setValue(-10)
        self.sp_rpt.valueChanged.connect(self._rpt_edited)
        g.addWidget(self.sp_rpt, 0, 5)
        g.addWidget(QLabel("TX"), 0, 6)
        self.sp_tx = QSpinBox()
        self.sp_tx.setRange(200, 3000)
        self.sp_tx.setSuffix(" Hz")
        self.sp_tx.setValue(int(self.tx_hz))
        self.sp_tx.setToolTip("Fréquence audio d'émission. Maj+clic dans la chute d'eau pour la choisir.")
        self.sp_tx.valueChanged.connect(self._tx_hz_changed)
        g.addWidget(self.sp_tx, 0, 7)
        self.rb_even = QRadioButton("1er créneau")
        self.rb_odd = QRadioButton("2e créneau")
        self.rb_even.setToolTip("Émettre à 00 et 30 s (FT8)")
        self.rb_odd.setToolTip("Émettre à 15 et 45 s (FT8)")
        self.rb_even.setChecked(True)
        self.rb_even.toggled.connect(lambda on: setattr(self, "tx_parity", 0 if on else 1))
        g.addWidget(self.rb_even, 0, 8)
        g.addWidget(self.rb_odd, 0, 9)
        v.addLayout(g)

        h = QHBoxLayout()
        self.cb_next = QComboBox()
        self.cb_next.setMinimumWidth(240)
        self.cb_next.setToolTip("Message émis au prochain créneau (la séquence automatique le fait avancer)")
        self.cb_next.activated.connect(self._next_chosen)
        h.addWidget(self.cb_next, 1)
        self.b_tx = QPushButton("Émission")
        self.b_tx.setCheckable(True)
        self.b_tx.setToolTip("Autorise l'émission du message choisi à chaque créneau")
        self.b_tx.toggled.connect(self.toggle_tx)
        h.addWidget(self.b_tx)
        b = QPushButton("Appeler CQ")
        b.clicked.connect(self.call_cq)
        h.addWidget(b)
        b = QPushButton("Stop")
        b.setToolTip("Arrête l'émission tout de suite (Échap)")
        b.clicked.connect(self.halt)
        h.addWidget(b)
        self.ck_auto = QCheckBox("Séquence auto")
        self.ck_auto.setChecked(s.value("ftx_auto", "true") in (True, "true"))
        h.addWidget(self.ck_auto)
        self.ck_cq = QCheckBox("Relancer CQ")
        self.ck_cq.setToolTip("Après un QSO lancé par votre CQ, rappeler CQ")
        self.ck_cq.setChecked(s.value("ftx_autocq", "false") in (True, "true"))
        h.addWidget(self.ck_cq)
        self.ck_log = QCheckBox("Noter au carnet")
        self.ck_log.setChecked(s.value("ftx_log", "true") in (True, "true"))
        h.addWidget(self.ck_log)
        v.addLayout(h)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        self.lb.setWordWrap(True)
        v.addWidget(self.lb)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.refresh_next()

    # --- réglages ------------------------------------------------------------------------
    def mycall(self):
        return (self.win.settings.value("mycall", "") or "").strip().upper()

    def mygrid(self):
        st = getattr(self.win, "station", None)
        return self.win.b_loc.text().split()[0][:4] if st else ""

    @property
    def slot(self):
        return ftx.MODES[self.mode]["slot"]

    def _fill_bands(self):
        self.cb_band.clear()
        for b, khz in ftx.FREQS[self.mode].items():
            self.cb_band.addItem(f"{b}  {khz:g} kHz", khz)

    def set_mode(self, mode):
        self.mode = mode
        self._fill_bands()
        self.decoded_slots.clear()
        self.halt()

    def goto_band(self):
        ctrl = self.win.ctrl
        if not ctrl.connected:
            self.lb.setText("Pas de poste connecté")
            return
        ctrl.set_freq(int(self.cb_band.currentData() * 1000))
        ctrl.set_mode("PKTUSB")

    def update_markers(self):
        wf = self.win.wf
        if self.isVisible():
            wf.markers["rx"] = (self.rx_hz, "#4caf50", "RX")
            wf.markers["tx"] = (self.tx_hz, "#f44336", "TX")
        else:
            wf.markers.pop("rx", None)
            wf.markers.pop("tx", None)

    def wf_click(self, hz, mods):
        if mods & Qt.ShiftModifier:
            self.sp_tx.setValue(int(hz))
        else:
            self.rx_hz = float(hz)
        self.update_markers()
        return True

    def _tx_hz_changed(self, v):
        self.tx_hz = float(v)
        self.update_markers()

    # --- horloge et créneaux -------------------------------------------------------------
    def tick(self):
        now = time.time()
        slot = self.slot
        idx = int(now // slot)
        t_slot = idx * slot
        pos = now - t_slot
        self.bar.setValue(int(pos / slot * 1000))
        utc = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
        tx = self.dock.tx.busy
        self.lb_clock.setText(f"{utc:%H:%M:%S} UTC · créneau {'1er' if idx % 2 == 0 else '2e'}"
                              + ("  ● ÉMISSION" if tx else ""))
        if not self.dock.listening():
            return
        # bande simulée (signal de test)
        if self.win.wf.test and idx not in self.sim_slots and 0.45 <= pos < 2:
            self.sim_slots.add(idx)
            if pos < 0.7:
                self.sim.slot_start(idx, self.mode)
        # décodage du créneau qui se termine
        if pos >= slot - 0.3 and idx not in self.decoded_slots:
            self.decoded_slots.add(idx)
            if idx not in self.tx_slots:
                self.engine.decode_slot(t_slot, self.mode)
        # émission au créneau suivant
        nxt = idx + 1
        if (self.tx_on and nxt % 2 == self.tx_parity and nxt not in self.scheduled
                and pos >= slot - 0.25 and not self.engine.busy):
            self._start_tx(nxt)
        elif (self.tx_on and idx % 2 == self.tx_parity and idx not in self.scheduled and pos < 1.0
              and not self.engine.busy and self.qso.next_message()):
            self._start_tx(idx)                  # émission demandée en tout début de créneau
        self.decoded_slots = {i for i in self.decoded_slots if i > idx - 4}
        self.tx_slots = {i for i in self.tx_slots if i > idx - 4}
        self.scheduled = {i for i in self.scheduled if i > idx - 4}
        self.sim_slots = {i for i in self.sim_slots if i > idx - 4}

    def _start_tx(self, idx):
        text = self.qso.next_message()
        self.scheduled.add(idx)
        if not text:
            return
        t0 = idx * self.slot
        try:
            sig = ftx.synth(ftx.tones(text, self.mode), self.tx_hz, self.dock.tx.rate(), self.mode, amp=0.9)
        except Exception as e:
            self.lb.setText(str(e))
            self.b_tx.setChecked(False)
            return
        start = max(t0 + 0.5, time.time() + 0.2)
        late = start - (t0 + 0.5)
        if late > 0:
            sig = sig[int(late * self.dock.tx.rate()):]
        if self.dock.tx.play(sig, self.dock.tx.rate(), start_at=start, label=text):
            self.tx_slots.add(idx)
            self._tx_text = text
            if self.qso_start is None and self.qso.dx:
                self.qso_start = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc)
            utc = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc)
            self._exchange(f"{utc:%H%M%S}  Émis   {self.tx_hz:4.0f} Hz  {text}", "#ff7043")
            if self.win.wf.test:
                self.sim.heard(text, idx)

    def tx_finished(self, msg):
        text = getattr(self, "_tx_text", "")
        self._tx_text = ""
        if text:
            self.qso.transmitted(text)
            if self.qso.done_reason:
                self.lb.setText(self.qso.done_reason)
                if not self.qso.step:
                    self.b_tx.setChecked(False)
                self.qso.done_reason = ""
            self.refresh_next()
        if msg:
            self.lb.setText(msg)

    def toggle_tx(self, on):
        if on and not self.mycall():
            self.lb.setText("Indiquez votre indicatif (menu Carnet > Réglages)")
            self.b_tx.setChecked(False)
            return
        if on and not self.dock.listening():
            self.dock.start_listening()
        self.tx_on = on
        if on:
            self.dock.tx.ensure_data_mode()
        self.b_tx.setStyleSheet("QPushButton { background: #b71c1c; color: white; }" if on else "")

    def halt(self):
        self.b_tx.setChecked(False)
        self.dock.tx.stop()

    def call_cq(self):
        self.qso.mycall, self.qso.mygrid = self.mycall(), self.mygrid()
        self.qso.auto_cq = self.ck_cq.isChecked()
        self.qso.call_cq()
        self.qso_start = None
        self._sync_fields()
        self.refresh_next()
        self.b_tx.setChecked(True)

    # --- décodages -----------------------------------------------------------------------
    def on_decoded(self, res, t_slot, mode):
        self.engine.busy = False
        if mode != self.mode:
            return
        me = self.mycall()
        idx = int(round(t_slot / self.slot))
        utc = datetime.datetime.fromtimestamp(t_slot, datetime.timezone.utc)
        for d in res:
            d["utc"], d["slot"] = utc, idx
            p = ftx.parse(d["text"])
            if p["de"]:
                ftx.hash_add(p["de"])
            if me and (p["to"] == me or p["de"] == self.qso.dx and self.qso.dx):
                self._exchange(f"{utc:%H%M%S}  {d['snr']:+3d}  {d['freq']:4.0f} Hz  {d['text']}", "#e53935")
        self.decodes.extend(res)
        del self.decodes[:-400]
        self._append_rows(res)
        n = len(res)
        self.lb.setText(f"{utc:%H:%M:%S} : {n} décodage{'s' if n > 1 else ''}" if not self.lb.text().startswith("QSO")
                        else self.lb.text())
        if self.ck_auto.isChecked() and self.qso.step:
            self.qso.mycall, self.qso.mygrid = me, self.mygrid()
            if self.qso.on_decodes(res):
                self.log_qso()
            self._sync_fields()
            self.refresh_next()

    def _append_rows(self, res):
        if not res:
            return
        t = self.tbl
        me = self.mycall()
        worked = self.win.worked_entities()
        st = getattr(self.win, "station", None)
        sep = t.rowCount()
        t.insertRow(sep)                         # ligne de séparation entre créneaux
        it = QTableWidgetItem(f"— {res[0]['utc']:%H:%M:%S} —")
        it.setForeground(QColor("#777"))
        t.setItem(sep, 0, it)
        t.setSpan(sep, 0, 1, len(self.COLS))
        for d in res:
            p = ftx.parse(d["text"])
            info = cty.lookup(p["de"]) if p["de"] else None
            country = dist = ""
            new = False
            if info:
                from .logbook import french_name
                country = french_name(info)
                ent = cty.dxcc(p["de"])
                new = bool(ent and ent["prefix"] not in worked)
                pos = None
                if p["grid"]:
                    try:
                        from .geo import from_locator
                        pos = from_locator(p["grid"])
                    except ValueError:
                        pos = None
                pos = pos or (info["lat"], info["lon"])
                if st:
                    from .geo import distance_bearing
                    dist = f"{distance_bearing(*st, *pos)[0]:.0f} km"
            row = t.rowCount()
            t.insertRow(row)
            vals = [f"{d['utc']:%H%M%S}", f"{d['snr']:+d}", f"{d['dt']:+.1f}", f"{d['freq']:.0f}", d["text"],
                    country, dist]
            color = None
            if me and p["to"] == me:
                color = "#ef5350"
            elif p["cq"]:
                color = "#66bb6a"
            if new and p["cq"]:
                color = "#ffa726"
            elif p["de"] and self.win.worked_before(p["de"]) and color != "#ef5350":
                color = "#8a8a8a"
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setData(Qt.UserRole, d)
                if c in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if color:
                    item.setForeground(QColor(color))
                    if color in ("#ef5350", "#ffa726"):
                        f = QFont(item.font())
                        f.setBold(True)
                        item.setFont(f)
                if c == 5 and new:
                    item.setToolTip("Pays jamais contacté")
                t.setItem(row, c, item)
        while t.rowCount() > 600:
            t.removeRow(0)
        t.scrollToBottom()

    def on_double_click(self, row, _col):
        it = self.tbl.item(row, 4) or self.tbl.item(row, 0)
        d = it.data(Qt.UserRole) if it else None
        if not d:
            return
        me = self.mycall()
        if not me:
            self.lb.setText("Indiquez votre indicatif (menu Carnet > Réglages)")
            return
        self.qso.mycall, self.qso.mygrid = me, self.mygrid()
        self.qso.auto_cq = self.ck_cq.isChecked()
        if not self.qso.answer(d, d["snr"]):
            return
        self.qso_start = None
        self.rx_hz = d["freq"]
        # on émet sur le créneau opposé à celui du correspondant
        par = (d["slot"] + 1) % 2
        (self.rb_even if par == 0 else self.rb_odd).setChecked(True)
        self.tx_parity = par
        self.update_markers()
        self._sync_fields()
        self.refresh_next()
        self.b_tx.setChecked(True)

    # --- champs du QSO -------------------------------------------------------------------
    def _sync_fields(self):
        self.ed_dx.setText(self.qso.dx)
        self.ed_grid.setText(self.qso.dx_grid)
        if self.qso.sent_rpt:
            self.sp_rpt.blockSignals(True)
            self.sp_rpt.setValue(int(self.qso.sent_rpt))
            self.sp_rpt.blockSignals(False)

    def _dx_edited(self):
        self.qso.dx = self.ed_dx.text().strip().upper()
        self.refresh_next()

    def _rpt_edited(self, v):
        self.qso.sent_rpt = ftx.fmt_report(v)
        self.refresh_next()

    def refresh_next(self):
        self.cb_next.blockSignals(True)
        self.cb_next.clear()
        self.qso.mycall, self.qso.mygrid = self.mycall(), self.mygrid()
        if not self.qso.sent_rpt:
            self.qso.sent_rpt = ftx.fmt_report(self.sp_rpt.value())
        for n in range(1, 7):
            if n != 6 and not self.qso.dx:
                continue
            self.cb_next.addItem(f"Tx{n}  {self.qso.msg(n)}", n)
        i = self.cb_next.findData(self.qso.step)
        self.cb_next.setCurrentIndex(i if i >= 0 else -1)
        self.cb_next.blockSignals(False)

    def _next_chosen(self, i):
        self.qso.step = self.cb_next.itemData(i) or 0
        self.qso.repeat = 0

    def _exchange(self, text, color):
        self.ex.appendHtml(f"<span style='color:{color}'>{text}</span>")

    def log_qso(self):
        q = self.qso
        st = self.win._last
        if not self.ck_log.isChecked() or not q.dx:
            return
        t = self.qso_start or datetime.datetime.now(datetime.timezone.utc)
        mode, sub = adif.ADIF_MODES.get(self.mode, (self.mode, ""))
        freq = ""
        if st and self.win.ctrl.connected and st.freq:
            freq = f"{(st.freq + self.tx_hz) / 1e6:.6f}"
        rec = {"call": q.dx, "qso_date": t.strftime("%Y%m%d"), "time_on": t.strftime("%H%M%S"),
               "freq": freq, "mode": mode, "submode": sub, "rst_sent": q.sent_rpt, "rst_rcvd": q.rcvd_rpt,
               "gridsquare": q.dx_grid, "station_callsign": self.mycall(), "my_gridsquare": self.mygrid(),
               "tx_pwr": str(st.p.get("pwr", "")) if st else ""}
        if self.win.log.is_dupe(rec):
            return
        self.win.log.add(rec)
        self.qso_start = None
        self.lb.setText(f"QSO avec {q.dx} noté au carnet ({q.sent_rpt} / {q.rcvd_rpt})")
        self.win.statusBar().showMessage(f"QSO {self.mode} avec {q.dx} enregistré", 8000)

    def save_settings(self, s):
        s.setValue("ftx_mode", self.mode)
        s.setValue("ftx_rx", self.rx_hz)
        s.setValue("ftx_tx", self.tx_hz)
        s.setValue("ftx_auto", self.ck_auto.isChecked())
        s.setValue("ftx_autocq", self.ck_cq.isChecked())
        s.setValue("ftx_log", self.ck_log.isChecked())
