"""Pilote Icom IC-705 : protocole CI-V (trames binaires FE FE adr E0 cmd … FD).

Différences avec les Yaesu :
- liaison USB à 115200 bauds (menu CI-V USB Baud Rate : Auto ou 115200) ;
- adresse CI-V par défaut A4h ; le poste peut renvoyer l'écho des commandes
  et diffuser ses changements (CI-V Transceive) : ces trames sont ignorées ;
- puissance de 0,5 à 10 W, codée de 0 à 255 ;
- les réglages sans équivalent CI-V simple sont grisés dans l'interface
  (largeur de filtre Yaesu, contour, APF, keyer…).
Lecture/écriture des mémoires et des menus : pas encore prises en charge.
"""
import time

from .base import RigDriver, RigError, RigRefused, RigTimeout, interp, s_text_from_db
from .ft991a import SM_CAL, SWR_CAL

CIV_ADDR = 0xA4
HAS_SUB = {0x07, 0x14, 0x15, 0x16, 0x1A, 0x1B, 0x1C, 0x21, 0x25}  # commandes à sous-commande
CTRL = 0xE0

ICOM_MODE = {"LSB": 0x00, "USB": 0x01, "AM": 0x02, "CW": 0x03, "RTTY": 0x04, "FM": 0x05,
             "CWR": 0x07, "RTTYR": 0x08, "DV": 0x17}
DATA_BASE = {"PKTUSB": "USB", "PKTLSB": "LSB", "PKTFM": "FM"}
CTCSS = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0,
         103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
         151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5,
         186.2, 189.9, 192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1,
         233.6, 241.8, 250.3, 254.1]
# Repères des échelles Icom (valeur brute -> grandeur)
SWR_ICOM = [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 6.0)]
PO_ICOM = [(0, 0.0), (143, 0.5), (213, 1.0), (255, 1.2)]
# Réglages de l'interface sans équivalent sur l'IC-705
UNSUPPORTED = {"keyer", "width", "shift", "contour", "contour_f", "notch_f", "nar", "apf",
               "mic_eq", "dnf_lvl"}


def bcd(n, nbytes, little=True):
    s = f"{int(n):0{nbytes * 2}d}"[-nbytes * 2:]
    b = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
    return bytes(reversed(b) if little else b)


def unbcd(data, little=True):
    seq = reversed(data) if little else data
    return int("".join(f"{x:02X}" for x in seq) or "0")


def _db_to_yaesu_raw(db):
    return interp([(d, r) for r, d in SM_CAL], db)


def _swr_to_yaesu_raw(v):
    return interp([(s, r) for r, s in SWR_CAL], v)


# Niveaux 14h (0-255 en BCD gros-boutiste) : clé -> (sous-commande, lecture, écriture)
def _lin(lo, hi):
    return (lambda raw: round(lo + raw * (hi - lo) / 255),
            lambda v: max(0, min(255, round((v - lo) * 255 / (hi - lo)))))


LEVELS = {
    "af": (0x01, *_lin(0, 255)), "rf": (0x02, *_lin(0, 255)), "sql": (0x03, *_lin(0, 100)),
    "dnr_lvl": (0x06, *_lin(0, 15)), "mic": (0x0B, *_lin(0, 100)), "wpm": (0x0C, *_lin(6, 48)),
    "proc_lvl": (0x0E, *_lin(0, 100)), "mon_lvl": (0x15, *_lin(0, 100)),
    "vox_gain": (0x16, *_lin(0, 100)),
    "pitch": (0x09, lambda raw: round((300 + raw * 600 / 255 - 300) / 10),
              lambda v: max(0, min(255, round((int(v) * 10) * 255 / 600)))),
}
# Fonctions 16h : clé -> sous-commande (valeur 0/1, sauf mention)
FUNCS = {"nb": 0x22, "dnr": 0x40, "dnf": 0x41, "proc": 0x44, "mon": 0x45, "vox": 0x46,
         "notch": 0x48}


class IC705(RigDriver):
    name = "Icom IC-705"
    modes = ["LSB", "USB", "CW", "CWR", "AM", "FM", "RTTY", "RTTYR", "PKTUSB", "PKTLSB", "PKTFM"]
    default_baud = 115200
    default_stopbits = 1
    max_freq = 470_000_000
    max_power = 10                  # W
    has_c4fm = False
    has_qmb = False
    has_usb_audio = True            # codec USB intégré (« USB Audio CODEC »)
    menu_skip = set()

    def __init__(self, *a):
        super().__init__(*a)
        self.addr = CIV_ADDR
        self._keys = list(LEVELS) + list(FUNCS) + ["pwr", "att", "pre", "agc", "bkin", "atu",
                                                   "split_dup", "vfob", "tone_mode", "tone", "rit"]
        self._slow = 0
        self._fails = {}
        self.unsupported = {}
        self._vm = False
        self._ch = 1
        self._rit = {"clar": 0, "rx_clar": False, "tx_clar": False}
        self._context = None

    # --- trames CI-V -------------------------------------------------------------------
    def _frame(self, payload):
        return bytes([0xFE, 0xFE, self.addr, CTRL]) + bytes(payload) + b"\xFD"

    def _read_frame(self, deadline):
        buf = b""
        while time.monotonic() < deadline:
            c = self.ser.read(1)
            if not c:
                continue
            buf += c
            if c == b"\xFD":
                i = buf.rfind(b"\xFE\xFE")
                if i >= 0:
                    return buf[i + 2:-1]
                buf = b""
        return None

    def _cmd(self, payload, reply=True, timeout=0.4):
        """Envoie une commande ; renvoie les données de la réponse (sans cmd/sous-cmd)."""
        self.ser.reset_input_buffer()
        self.ser.write(self._frame(payload))
        if not reply:
            return b""
        deadline = time.monotonic() + timeout
        while True:
            f = self._read_frame(deadline)
            if f is None:
                raise RigTimeout(f"pas de réponse CI-V à {bytes(payload).hex(' ')}")
            if len(f) < 3 or f[0] != CTRL or f[1] != self.addr:
                continue                   # écho de notre commande ou diffusion
            body = f[2:]
            if body[:1] == b"\xFA":
                raise RigRefused(f"commande refusée : {bytes(payload).hex(' ')}")
            if body[:1] == b"\xFB":
                return b""
            n = 2 if payload[0] in HAS_SUB and len(payload) > 1 else 1
            if body[:n] == bytes(payload[:n]):
                return body[n:]
            # autre réponse : on continue d'attendre

    def _set(self, payload):
        try:
            self._cmd(payload)
        except RigTimeout:
            pass                            # certains réglages ne renvoient rien

    # --- marche / arrêt ----------------------------------------------------------------
    def is_on(self):
        try:
            self._cmd([0x03])
            return True
        except RigError:
            return False

    def power_on(self, wait=15.0):
        if self.is_on():
            return False
        # Préambule de FE pour réveiller le poste (nombre lié à la vitesse), puis 18 01
        self.ser.write(b"\xFE" * 150 + self._frame([0x18, 0x01]))
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            time.sleep(0.5)
            if self.is_on():
                time.sleep(1.0)
                return True
        raise RigError("l'IC-705 ne s'est pas allumé (batterie ou alimentation ?)")

    def power_off(self):
        self._cmd([0x18, 0x00], reply=False)
        time.sleep(0.3)

    # --- lecture -----------------------------------------------------------------------
    def poll(self, st):
        st.freq = unbcd(self._cmd([0x03])[:5])
        m = self._cmd([0x04])
        name = next((k for k, v in ICOM_MODE.items() if v == m[0]), st.mode)
        if name in ("USB", "LSB", "FM"):
            try:
                if self._cmd([0x1A, 0x06])[:1] not in (b"\x00", b""):
                    name = "PKT" + name
            except RigError:
                pass
        st.mode = name
        st.ptt = self._cmd([0x1C, 0x00])[:1] == b"\x01"
        if st.ptt:
            st.po = interp(PO_ICOM, unbcd(self._cmd([0x15, 0x11])[:2], little=False))
            raw = unbcd(self._cmd([0x15, 0x12])[:2], little=False)
            st.swr_val = interp(SWR_ICOM, raw)
            st.swr = _swr_to_yaesu_raw(st.swr_val) / 255
            st.alc = min(1.0, unbcd(self._cmd([0x15, 0x13])[:2], little=False) / 120)
            st.smeter = 0.0
        else:
            raw = unbcd(self._cmd([0x15, 0x02])[:2], little=False)
            db = -54 + raw * 54 / 120 if raw <= 120 else (raw - 120) * 60 / 121
            st.s_db = round(db)
            st.s_text = s_text_from_db(st.s_db)
            st.smeter = _db_to_yaesu_raw(db) / 255
            st.po = st.swr = st.alc = st.swr_val = 0.0
        ctx = (st.mode, 0 if st.freq < 60_000_000 else 1 if st.freq < 300_000_000 else 2)
        if ctx != self._context:
            self._context = ctx
            self.unsupported.clear()
            self._fails.clear()
        for _ in range(3):
            self._poll_one(st)
        st.p["info"] = {"ch": self._ch, "vm": 1 if self._vm else 0, "mode": st.mode, **self._rit}
        st.p.setdefault("mem_tag", "")
        st.unsupported = set(self.unsupported) | UNSUPPORTED

    def _poll_one(self, st):
        key = self._keys[self._slow]
        self._slow = (self._slow + 1) % len(self._keys)
        refused = self.unsupported.get(key)
        if refused is not None and time.monotonic() - refused < 8:
            return
        try:
            p = st.p
            if key in LEVELS:
                sub, rd, _wr = LEVELS[key]
                p[key] = rd(unbcd(self._cmd([0x14, sub])[:2], little=False))
            elif key in FUNCS:
                p[key] = self._cmd([0x16, FUNCS[key]])[:1] not in (b"\x00", b"")
            elif key == "pwr":
                raw = unbcd(self._cmd([0x14, 0x0A])[:2], little=False)
                p["pwr"] = max(1, round(raw * self.max_power / 255))
            elif key == "att":
                p["att"] = self._cmd([0x11])[:1] not in (b"\x00", b"")
            elif key == "pre":
                p["pre"] = min(2, self._cmd([0x16, 0x02])[0])
            elif key == "agc":
                p["agc"] = min(3, max(1, self._cmd([0x16, 0x12])[0]))
            elif key == "bkin":
                p["bkin"] = self._cmd([0x16, 0x47])[:1] not in (b"\x00", b"")
            elif key == "atu":
                p["atu"] = 1 if self._cmd([0x1C, 0x01])[:1] not in (b"\x00", b"") else 0
            elif key == "split_dup":
                v = self._cmd([0x0F])[0]
                p["split"] = v == 0x01
                p["rpt_shift"] = {0x11: 2, 0x12: 1}.get(v, 0)
            elif key == "vfob":
                p["vfob"] = unbcd(self._cmd([0x25, 0x01])[:5])
            elif key == "tone_mode":
                tone = self._cmd([0x16, 0x42])[:1] not in (b"\x00", b"")
                tsql = self._cmd([0x16, 0x43])[:1] not in (b"\x00", b"")
                p["tone_mode"] = 1 if tsql else 2 if tone else 0
            elif key == "tone":
                d = self._cmd([0x1B, 0x00])[-3:]
                hz = unbcd(d, little=False) / 10
                p["tone"] = min(range(len(CTCSS)), key=lambda i: abs(CTCSS[i] - hz))
            elif key == "rit":
                d = self._cmd([0x21, 0x00])
                hz = unbcd(d[:2])
                self._rit["clar"] = -hz if d[2:3] == b"\x01" else hz
                self._rit["rx_clar"] = self._cmd([0x21, 0x01])[:1] == b"\x01"
                try:
                    self._rit["tx_clar"] = self._cmd([0x21, 0x02])[:1] == b"\x01"
                except RigError:
                    pass
            self._fails.pop(key, None)
            self.unsupported.pop(key, None)
        except (RigError, IndexError, ValueError):
            self._fails[key] = self._fails.get(key, 0) + 1
            if self._fails[key] >= 2:
                for k in {"split_dup": ("split", "rpt_shift"), "rit": ()}.get(key, (key,)):
                    self.unsupported[k] = time.monotonic()

    # --- commandes ---------------------------------------------------------------------
    def set_freq(self, hz):
        self._set([0x05, *bcd(int(hz), 5)])

    def set_mode(self, mode):
        base = DATA_BASE.get(mode, mode)
        code = ICOM_MODE.get(base)
        if code is None:
            return
        self._set([0x06, code, 0x01])
        if base in ("USB", "LSB", "FM"):
            self._set([0x1A, 0x06, 0x01 if mode in DATA_BASE else 0x00, 0x01 if mode in DATA_BASE else 0x00])

    def set_ptt(self, on):
        self._set([0x1C, 0x00, 0x01 if on else 0x00])

    def set_param(self, key, value):
        if key in LEVELS:
            sub, _rd, wr = LEVELS[key]
            self._set([0x14, sub, *bcd(wr(value), 2, little=False)])
        elif key in FUNCS:
            self._set([0x16, FUNCS[key], 0x01 if value else 0x00])
        elif key == "pwr":
            w = max(0.5, min(self.max_power, float(value)))
            self._set([0x14, 0x0A, *bcd(round(w * 255 / self.max_power), 2, little=False)])
        elif key == "att":
            self._set([0x11, 0x20 if value else 0x00])
        elif key == "pre":
            self._set([0x16, 0x02, int(value) % 3])
        elif key == "agc":
            self._set([0x16, 0x12, min(3, max(1, int(value) if int(value) in (1, 2, 3) else 2))])
        elif key == "bkin":
            self._set([0x16, 0x47, 0x01 if value else 0x00])
        elif key == "atu":
            self._set([0x1C, 0x01, 0x01 if value else 0x00])
        elif key == "split":
            self._set([0x0F, 0x01 if value else 0x00])
        elif key == "rpt_shift":
            self._set([0x0F, {0: 0x10, 1: 0x12, 2: 0x11}.get(int(value), 0x10)])
        elif key == "vfob":
            self._set([0x25, 0x01, *bcd(int(value), 5)])
        elif key == "tone_mode":
            v = int(value)
            self._set([0x16, 0x42, 0x01 if v == 2 else 0x00])
            self._set([0x16, 0x43, 0x01 if v == 1 else 0x00])
        elif key == "tone":
            hz = CTCSS[int(value)]
            self._set([0x1B, 0x00, *bcd(round(hz * 10), 3, little=False)])

    def _set_rit(self, hz):
        hz = max(-9999, min(9999, int(hz)))
        self._set([0x21, 0x00, *bcd(abs(hz), 2), 0x01 if hz < 0 else 0x00])
        self._rit["clar"] = hz

    def action(self, name, *args):
        if name == "swap":
            self._set([0x07, 0xB0])
        elif name == "a_to_b":
            self._set([0x07, 0xA0])
        elif name == "b_to_a":
            self._set([0x07, 0xB0])
            self._set([0x07, 0xA0])
            self._set([0x07, 0xB0])
        elif name == "vm":
            self._vm = not self._vm
            self._set([0x08] if self._vm else [0x07])
        elif name == "mem_recall":
            self._ch = int(args[0])
            self._vm = True
            self._set([0x08, *bcd(self._ch, 2, little=False)])
        elif name in ("up", "down"):
            f = unbcd(self._cmd([0x03])[:5])
            self.set_freq(f + (10000 if name == "up" else -10000))
        elif name == "tune":
            self._set([0x1C, 0x01, 0x02])
        elif name == "clar_step":
            self._set_rit(self._rit["clar"] + int(args[0]))
        elif name == "clar_clear":
            self._set_rit(0)
        elif name == "rx_clar":
            self._set([0x21, 0x01, 0x01 if args[0] else 0x00])
        elif name == "tx_clar":
            self._set([0x21, 0x02, 0x01 if args[0] else 0x00])
        elif name == "cw_text":
            self.cw_send(*args)
        # zin, QMB, mémoires du keyer : pas d'équivalent CI-V, ignorés

    # --- CW : commande 17h, 30 caractères par trame -------------------------------------
    def cw_send(self, text, slot=None):
        text = text.upper()
        for i in range(0, len(text), 30):
            self._set([0x17, *text[i:i + 30].encode("ascii", "ignore")])

    def cw_play(self, slot):
        pass

    # --- fonctions pas encore prises en charge ---------------------------------------------
    def read_memories(self, progress=None):
        raise RigError("la lecture des mémoires de l'IC-705 n'est pas encore prise en charge")

    def write_memories(self, mems, template, progress=None):
        raise RigError("l'écriture des mémoires de l'IC-705 n'est pas encore prise en charge")

    def read_menus(self, progress=None):
        raise RigError("la sauvegarde des menus de l'IC-705 n'est pas encore prise en charge")

    def write_menus(self, menus, progress=None):
        raise RigError("la restauration des menus de l'IC-705 n'est pas encore prise en charge")
