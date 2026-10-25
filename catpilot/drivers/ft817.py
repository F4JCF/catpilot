"""Pilote Yaesu FT-817 / FT-818 / FT-857 / FT-897 : protocole CAT binaire.

Ces postes ne parlent pas le CAT texte du FT-991A (« FA…; ») mais un protocole
de 5 octets : 4 paramètres puis le code de commande. Exemple : régler
14,250 00 MHz = 01 42 50 00 01 (fréquence en BCD, unité 10 Hz, puis 0x01).

Ce que le CAT de ces postes permet (et donc ce que fait le logiciel) :
fréquence, mode, PTT, S-mètre, mesures d'émission, split, bascule VFO A/B,
clarifier, décalage relais, CTCSS/DCS, verrouillage, marche/arrêt.

Ce qu'il ne permet pas : volume, gain HF, squelch, puissance, filtres, AGC,
ATT/IPO, keyer, menus, mémoires du poste… Ces réglages se font sur le poste ;
le logiciel n'affiche pas leurs boutons. La lecture de l'EEPROM (commande 0xBB,
non documentée) sert seulement sur FT-817/818 à connaître l'état du split,
en lecture seule : le logiciel n'écrit JAMAIS dans l'EEPROM (risque de perdre
les réglages d'usine du poste).

Les mémoires du poste ne sont pas accessibles par le CAT : le panneau
« Mémoires » gère une banque de canaux enregistrée sur le PC (rappel = le
logiciel règle fréquence, mode, relais et tonalité).

Références : manuels Yaesu (chapitre CAT) et pilotes Hamlib ft817.c, ft857.c, ft897.c.
"""
import collections
import json
import os
import time

import serial

from .base import RigDriver, RigError, RigTimeout, interp, s_text_from_db

# --- codes de mode ------------------------------------------------------------------
# Lecture (commande 0x03, 5e octet ; le bit 7 = filtre étroit : CW-N, FM-N…)
READ_MODE = {0x00: "LSB", 0x01: "USB", 0x02: "CW", 0x03: "CWR", 0x04: "AM",
             0x06: "WFM", 0x08: "FM", 0x0A: "PKTUSB", 0x0C: "PKTFM"}
# Écriture (commande 0x07). DIG suit le menu « DIG MODE » du poste (USER-U pour FT8).
SET_MODE = {"LSB": 0x00, "USB": 0x01, "CW": 0x02, "CWR": 0x03, "AM": 0x04, "FM": 0x08,
            "PKTUSB": 0x0A, "PKTLSB": 0x0A, "RTTY": 0x0A, "RTTYR": 0x0A, "PKTFM": 0x0C}
MODES = ["USB", "LSB", "CW", "CWR", "AM", "FM", "PKTUSB", "PKTFM"]

CMD_LOCK_ON, CMD_LOCK_OFF = 0x00, 0x80
CMD_PTT_ON, CMD_PTT_OFF = 0x08, 0x88
CMD_SET_FREQ, CMD_GET_FREQ_MODE, CMD_SET_MODE = 0x01, 0x03, 0x07
CMD_CLAR_ON, CMD_CLAR_OFF, CMD_CLAR_FREQ = 0x05, 0x85, 0xF5
CMD_VFO_TOGGLE = 0x81
CMD_SPLIT_ON, CMD_SPLIT_OFF = 0x02, 0x82
CMD_RPT_SHIFT, CMD_RPT_OFFSET = 0x09, 0xF9
CMD_TONE_MODE, CMD_CTCSS, CMD_DCS = 0x0A, 0x0B, 0x0C
CMD_RX_STATUS, CMD_TX_STATUS, CMD_TX_METER = 0xE7, 0xF7, 0xBD
CMD_POWER_ON, CMD_POWER_OFF = 0x0F, 0x8F
CMD_EEPROM_READ = 0xBB

RPT_SHIFT = {0: 0x89, 1: 0x49, 2: 0x09}           # simplex, +, −
TONE_MODE = {0: 0x8A, 1: 0x2A, 2: 0x4A, 3: 0x0A}  # aucune, TSQ, tonalité TX, DCS

CTCSS = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0,
         103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
         151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5,
         186.2, 189.9, 192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1,
         233.6, 241.8, 250.3, 254.1]

# Échelles de l'interface (reprises du FT-991A : valeurs brutes 0-255)
SM_CAL_991 = [(0, -54), (12, -48), (27, -42), (40, -36), (55, -30), (65, -24), (80, -18),
              (95, -12), (112, -6), (130, 0), (150, 10), (172, 20), (190, 30), (220, 40),
              (240, 50), (255, 60)]
SWR_CAL_991 = [(0, 1.0), (26, 1.2), (52, 1.5), (89, 2.0), (150, 3.0), (255, 5.0)]
# Mesures de ces postes (Hamlib, d'après Christian WA4YA / DL4YA et Olivier Schmitt)
SWR_CAL = [(0, 1.0), (1, 1.4), (2, 1.8), (3, 2.13), (4, 2.25), (5, 3.7), (6, 6.0), (7, 7.0),
           (8, 8.0), (9, 9.0), (10, 10.0), (15, 10.0)]
PWR_CAL_817 = [(0, 0.0), (1, 0.5), (2, 0.75), (3, 1.0), (4, 1.7), (5, 2.5), (6, 3.3), (7, 4.1), (8, 5.0)]

# Réglages pilotables : uniquement en écriture (le poste ne sait pas les relire),
# sauf « split » relu dans l'EEPROM sur FT-817/818.
CAT_PARAMS = {"split", "vfob", "rpt_shift", "tone_mode", "tone", "lock", "info"}


def to_bcd(value, digits):
    """Entier -> octets BCD, poids fort en tête (8 chiffres = 4 octets)."""
    s = f"{int(value):0{digits}d}"[-digits:]
    return bytes(int(s[i]) << 4 | int(s[i + 1]) for i in range(0, digits, 2))


def from_bcd(data):
    out = 0
    for b in data:
        hi, lo = b >> 4, b & 0x0F
        if hi > 9 or lo > 9:
            raise ValueError(f"BCD invalide : {data.hex()}")
        out = out * 100 + hi * 10 + lo
    return out


def inverse(table, y):
    """Valeur brute correspondant à y dans une table [(brut, valeur), ...] croissante."""
    if y <= table[0][1]:
        return table[0][0]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if y <= y1:
            return x0 + (x1 - x0) * (y - y0) / ((y1 - y0) or 1)
    return table[-1][0]


def bank_path():
    d = os.path.join(os.path.expanduser("~"), "Documents", "CATPilot")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "memoires_pc.json")


def load_bank():
    try:
        with open(bank_path(), encoding="utf-8") as f:
            return [m for m in json.load(f) if "ch" in m and "freq" in m]
    except (OSError, ValueError, TypeError):
        return []


def save_bank(mems):
    path = bank_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(mems, key=lambda m: int(m["ch"])), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class FT817(RigDriver):
    name = "Yaesu FT-817"
    modes = MODES
    default_baud = 4800              # menu CAT RATE du poste (4800 par défaut)
    default_stopbits = 2             # protocole 8N2
    min_freq = 0
    max_freq = 470_000_000           # HF, 6 m, 2 m, 70 cm
    max_power = 5
    has_c4fm = False
    has_qmb = False
    has_usb_audio = False            # interface audio externe (Digirig, SCU-17, Signalink…)
    has_menus = False                # pas de commande de menus : réglages sur le poste
    has_cw_memory = False            # pas de keyer par CAT : CW par la ligne DTR/RTS
    has_vm = False                   # pas de bascule VFO/mémoire par CAT
    has_tx_clar = False
    has_lock = True
    mem_on_pc = True                 # banque de mémoires gérée sur le PC
    mem_range = (1, 199)
    mem_tag_len = 12
    menu_skip = set()
    cat_params = CAT_PARAMS
    tx_meter_cmd = True              # 0xBD : puissance, ROS, ALC en émission
    pwr_cal = PWR_CAL_817            # barres -> watts
    eeprom_split = True              # FT-817/818 : état du split dans l'EEPROM (0x7A, bit 7)

    def __init__(self, *a):
        super().__init__(*a)
        self.history = collections.deque(maxlen=150)
        self.local = {}              # réglages écrits (le poste ne les renvoie pas)
        self.clar, self.clar_on = 0, False
        self.vfob = None
        self.acks = None             # le poste renvoie-t-il un octet après chaque ordre ?
        self._no_ack = 0
        self._meter_fail = 0
        self._last_split_read = 0.0
        self._learned_b = False
        self.bank = {}
        self.mode = "USB"
        self.freq = 0

    # --- liaison série ----------------------------------------------------------------
    def open(self):
        # Lignes RTS et DTR au repos AVANT l'ouverture : beaucoup d'interfaces
        # (Digirig, CT-62 avec PTT…) font passer le poste en émission sur RTS ou DTR.
        s = serial.Serial()
        s.port = self.port
        s.baudrate = self.baud
        s.bytesize, s.parity = 8, "N"
        s.stopbits = serial.STOPBITS_TWO if self.stopbits == 2 else serial.STOPBITS_ONE
        s.timeout, s.write_timeout = 0.3, 0.5
        s.rtscts = s.dsrdtr = False
        s.rts = s.dtr = False
        s.open()
        self.ser = s

    def _trace(self, way, data):
        self.history.append(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} "
                            f"{way} {data.hex(' ') if data else '(rien)'}")

    def diagnostics(self):
        lines = list(self.history)
        try:
            s = self.ser
            lines.append(f"lignes : RTS={int(s.rts)} DTR={int(s.dtr)} CTS={int(s.cts)} DSR={int(s.dsr)} "
                         f"en attente={s.in_waiting} octets")
        except Exception as e:
            lines.append(f"lignes : illisibles ({e})")
        return lines

    def _send(self, cmd, p=b"\x00\x00\x00\x00"):
        frame = bytes(p[:4]).ljust(4, b"\x00") + bytes([cmd])
        self.ser.write(frame)
        self._trace(">", frame)

    def _query(self, cmd, n, p=b"\x00\x00\x00\x00", min_len=None):
        """Envoie une demande et lit n octets de réponse."""
        self.ser.reset_input_buffer()
        self._send(cmd, p)
        data = self.ser.read(n)
        self._trace("<", data)
        if len(data) < (n if min_len is None else min_len):
            raise RigTimeout(f"pas de réponse à la commande {cmd:02X}")
        return data

    def _cmd(self, cmd, p=b"\x00\x00\x00\x00"):
        """Envoie un ordre. Le poste répond en général par un octet, qu'il faut lire
        pour qu'il ne se mélange pas à la réponse de la demande suivante."""
        self.ser.reset_input_buffer()
        self._send(cmd, p)
        if self.acks is False:
            time.sleep(0.04)
            return
        old = self.ser.timeout
        self.ser.timeout = 0.15
        try:
            data = self.ser.read(1)
        finally:
            self.ser.timeout = old
        self._trace("<", data)
        if data:
            self.acks, self._no_ack = True, 0
        elif self.acks is None:
            self._no_ack += 1
            if self._no_ack >= 3:     # ce poste n'accuse pas réception : on n'attend plus
                self.acks = False

    def resync(self):
        """Vide les tampons et vérifie que le poste répond (sans toucher RTS/DTR)."""
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.3)
            self.read_freq_mode()
            return True
        except Exception:
            return False

    # --- lectures de base ---------------------------------------------------------------
    def read_freq_mode(self):
        d = self._query(CMD_GET_FREQ_MODE, 5)
        freq = from_bcd(d[:4]) * 10
        code = d[4] & 0x7F
        if code not in READ_MODE or not 100_000 <= freq <= 500_000_000:
            raise RigError(f"réponse inattendue {d.hex(' ')}")
        return freq, READ_MODE[code], bool(d[4] & 0x80)

    def read_eeprom(self, addr):
        return self._query(CMD_EEPROM_READ, 2, bytes([addr >> 8, addr & 0xFF, 0, 0]))

    # --- marche / arrêt -----------------------------------------------------------------
    def is_on(self):
        try:
            self.read_freq_mode()
            return True
        except (RigError, ValueError):
            return False

    def power_on(self, wait=12.0):
        if self.is_on():
            return False
        self.ser.write(b"\xff" * 5)          # réveil du processeur CAT
        self._trace(">", b"\xff" * 5)
        time.sleep(0.2)
        self._send(CMD_POWER_ON)
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            time.sleep(0.6)
            if self.is_on():
                time.sleep(1.0)
                return True
        raise RigError("le poste ne s'est pas allumé (alimentation coupée, ou vitesse CAT différente ?)")

    def power_off(self):
        self._send(CMD_POWER_OFF)
        time.sleep(0.3)

    # --- interrogation ------------------------------------------------------------------
    def poll(self, st):
        freq, mode, narrow = self.read_freq_mode()
        self.freq, self.mode = freq, mode
        st.freq, st.mode = freq, mode
        tx = self._query(CMD_TX_STATUS, 1)[0]
        st.ptt = (tx & 0x80) == 0               # bit 7 à 0 = émission
        try:
            if st.ptt:
                self._poll_tx(st, tx)
            else:
                rx = self._query(CMD_RX_STATUS, 1)[0]
                n = rx & 0x0F                   # S-mètre : 0-15 (S0…S9, puis +10…+60 dB)
                st.s_db = 6 * n - 54 if n < 10 else 10 * (n - 9)
                st.s_text = s_text_from_db(st.s_db)
                st.smeter = inverse(SM_CAL_991, st.s_db) / 255
                st.p["busy"] = not (rx & 0x80)  # squelch ouvert
                st.po = st.swr = st.alc = st.swr_val = 0.0
        except (RigError, ValueError):
            pass
        if not st.ptt and not self._learned_b:
            self._learned_b = True
            self._learn_vfob()
        if self.eeprom_split and not st.ptt and time.monotonic() - self._last_split_read > 2.0:
            self._last_split_read = time.monotonic()
            try:
                self.local["split"] = bool(self.read_eeprom(0x7A)[0] & 0x80)
            except (RigError, ValueError):
                pass
        st.p.update(self.local)
        if self.vfob:
            st.p["vfob"] = self.vfob
        st.p["info"] = {"ch": 0, "freq": freq, "clar": self.clar, "rx_clar": self.clar_on,
                        "tx_clar": False, "mode": mode, "vm": 0,
                        "ctcss": self.local.get("tone_mode", 0), "shift": self.local.get("rpt_shift", 0)}
        st.unsupported = set()

    def _poll_tx(self, st, tx):
        st.smeter = 0.0
        if self.tx_meter_cmd and self._meter_fail < 3:
            try:
                d = self._query(CMD_TX_METER, 2)
                pwr, alc, swr = d[0] >> 4, d[0] & 0x0F, d[1] >> 4
                self._meter_fail = 0
                watts = interp(self.pwr_cal, pwr) if self.pwr_cal else pwr / 15 * self.max_power
                st.po = min(1.0, watts / self.max_power)
                st.swr_val = interp(SWR_CAL, swr)
                st.swr = min(1.0, inverse(SWR_CAL_991, min(st.swr_val, 5.0)) / 255)
                st.alc = min(1.0, alc / 5)
                return
            except (RigError, ValueError):
                self._meter_fail += 1
        st.po = (tx & 0x0F) / 15                # barres de puissance du poste
        high = bool(tx & 0x40)                  # alarme ROS élevé
        st.swr_val = 3.0 if high else 0.0
        st.swr = inverse(SWR_CAL_991, 3.0) / 255 if high else 0.0
        st.alc = 0.0

    def _learn_vfob(self):
        """Lit la fréquence de l'autre VFO (bascule A/B, lecture, retour)."""
        try:
            self._cmd(CMD_VFO_TOGGLE)
            time.sleep(0.12)
            self.vfob = self.read_freq_mode()[0]
        except (RigError, ValueError):
            pass
        finally:
            try:
                self._cmd(CMD_VFO_TOGGLE)
                time.sleep(0.12)
            except Exception:
                pass

    # --- commandes ----------------------------------------------------------------------
    def set_freq(self, hz):
        self._cmd(CMD_SET_FREQ, to_bcd(int(hz) // 10, 8))
        time.sleep(0.05)                 # le FT-817 demande un petit temps après un QSY

    def set_mode(self, mode):
        code = SET_MODE.get(mode)
        if code is not None:
            self._cmd(CMD_SET_MODE, bytes([code, 0, 0, 0]))

    def set_ptt(self, on):
        self._cmd(CMD_PTT_ON if on else CMD_PTT_OFF)

    def set_param(self, key, value):
        if key == "split":
            self._cmd(CMD_SPLIT_ON if value else CMD_SPLIT_OFF)
        elif key == "lock":
            self._cmd(CMD_LOCK_ON if value else CMD_LOCK_OFF)
        elif key == "vfob":
            self._on_other_vfo(lambda: self.set_freq(value))
            self.vfob = int(value)
        elif key == "rpt_shift":
            value = int(value) if int(value) in RPT_SHIFT else 0
            self._cmd(CMD_RPT_SHIFT, bytes([RPT_SHIFT[value], 0, 0, 0]))
        elif key == "tone_mode":
            value = int(value) if int(value) in TONE_MODE else 0
            if value in (1, 2):              # la fréquence d'abord, puis la mise en service
                self._send_tone(self.local.get("tone", 8))
            self._cmd(CMD_TONE_MODE, bytes([TONE_MODE[value], 0, 0, 0]))
        elif key == "tone":
            self._send_tone(int(value))
        elif key == "rpt_offset":
            self._cmd(CMD_RPT_OFFSET, to_bcd(int(value) // 10, 8))
        else:
            return                            # réglage que ce poste ne pilote pas en CAT
        self.local[key] = value

    def _send_tone(self, idx):
        idx = max(0, min(len(CTCSS) - 1, int(idx)))
        bcd = to_bcd(round(CTCSS[idx] * 10), 4)
        self._cmd(CMD_CTCSS, bcd + bcd)          # même tonalité à l'émission et à la réception

    def _send_clar(self):
        sign = 0xFF if self.clar < 0 else 0x00
        self._cmd(CMD_CLAR_FREQ, bytes([sign, 0]) + to_bcd(abs(self.clar) // 10, 4))

    def _on_other_vfo(self, fn):
        self._cmd(CMD_VFO_TOGGLE)
        time.sleep(0.12)
        try:
            return fn()
        finally:
            self._cmd(CMD_VFO_TOGGLE)
            time.sleep(0.12)

    def action(self, name, *args):
        if name == "swap":
            before = self.freq
            self._cmd(CMD_VFO_TOGGLE)
            time.sleep(0.12)
            if before:
                self.vfob = before
        elif name == "a_to_b":
            f, m = self.freq, self.mode
            if f:
                self._on_other_vfo(lambda: (self.set_freq(f), self.set_mode(m)))
                self.vfob = f
        elif name == "b_to_a":
            other = self._on_other_vfo(self.read_freq_mode)
            if other:
                self.vfob = self.freq or self.vfob
                self.set_freq(other[0])
                self.set_mode(other[1])
        elif name in ("up", "down"):
            if self.freq:
                self.set_freq(self.freq + (10_000 if name == "up" else -10_000))
        elif name == "clar_step":
            self.clar = max(-9990, min(9990, self.clar + int(args[0])))
            self._send_clar()
            if not self.clar_on:
                self._cmd(CMD_CLAR_ON)
                self.clar_on = True
        elif name == "clar_clear":
            self.clar = 0
            self._send_clar()
        elif name == "rx_clar":
            self.clar_on = bool(args[0])
            self._cmd(CMD_CLAR_ON if self.clar_on else CMD_CLAR_OFF)
        elif name == "mem_recall":
            self._recall(int(args[0]))

    # --- banque de mémoires sur le PC ---------------------------------------------------------
    def read_memories(self, progress=None):
        mems = load_bank()
        self.bank = {int(m["ch"]): m for m in mems}
        return [dict(m) for m in mems]

    def write_memories(self, mems, template, progress=None):
        from .ft991a import CODE_TO_MODE
        bank = {int(m["ch"]): m for m in load_bank()}
        for m in mems:
            m = {k: v for k, v in m.items() if k != "raw"}
            m["mode"] = CODE_TO_MODE.get(m.get("code"), m.get("mode", "FM"))
            m["mode_label"] = {"B": "FM-N", "D": "AM-N"}.get(m.get("code"))
            bank[int(m["ch"])] = m
        save_bank(list(bank.values()))
        self.bank = bank
        return [(int(m["ch"]), True) for m in mems]

    def _recall(self, ch):
        m = self.bank.get(ch) or {int(x["ch"]): x for x in load_bank()}.get(ch)
        if not m:
            return
        self.set_freq(int(m["freq"]))
        self.set_mode(m.get("mode") or "FM")
        if m.get("mode") in ("FM", "PKTFM"):
            self.set_param("rpt_shift", int(m.get("shift", 0)))
            self.set_param("tone_mode", int(m.get("ctcss", 0)))

    # --- pas de menus ni de keyer par CAT sur ces postes -------------------------------------
    def read_menus(self, progress=None):
        raise RigError("les menus de ce poste ne sont pas accessibles par le CAT")

    def write_menus(self, menus, progress=None):
        raise RigError("les menus de ce poste ne sont pas accessibles par le CAT")


class FT818(FT817):
    name = "Yaesu FT-818"
    max_power = 6


class FT857(FT817):
    """FT-857 / FT-857D : 100 W HF, 50 W en 2 m, 20 W en 70 cm. Pas de 0xBD documenté :
    essayé, puis repli sur les barres de puissance du statut d'émission."""
    name = "Yaesu FT-857"
    max_power = 100
    pwr_cal = None
    eeprom_split = False             # carte de l'EEPROM différente : split suivi par le logiciel


class FT897(FT857):
    name = "Yaesu FT-897"
