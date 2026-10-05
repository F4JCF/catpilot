"""Éléments communs au pilote FT-991A et au simulateur."""
import copy
from dataclasses import dataclass, field, replace

import serial


@dataclass
class RigState:
    freq: int = 0            # Hz, VFO A
    mode: str = "USB"        # nom de mode Hamlib (USB, PKTUSB, CW...)
    ptt: bool = False
    smeter: float = 0.0      # 0..1 (valeur brute / 255)
    s_text: str = "S0"
    s_db: int = -54          # dB par rapport à S9 (niveau Hamlib STRENGTH)
    po: float = 0.0          # 0..1
    swr: float = 0.0         # 0..1
    swr_val: float = 0.0     # ROS estimé
    alc: float = 0.0         # 0..1
    p: dict = field(default_factory=dict)          # réglages lus sur le poste
    unsupported: set = field(default_factory=set)  # réglages refusés par le poste

    def copy(self):
        return replace(self, p=copy.deepcopy(self.p), unsupported=set(self.unsupported))


class RigError(Exception):
    pass


class RigRefused(RigError):
    """Le poste a répondu « ?; » : commande inconnue ou impossible dans l'état actuel."""


class RigTimeout(RigError):
    pass


def interp(table, x):
    """Interpolation linéaire dans une table de calibration [(brut, valeur), ...]."""
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def s_text_from_db(db):
    if db <= 0:
        return f"S{max(0, round(9 + db / 6))}"
    return f"S9+{round(db)} dB"


class RigDriver:
    name = "?"
    modes = []
    default_baud = 38400
    default_stopbits = 1

    def __init__(self, port, baud, stopbits):
        self.port = port
        self.baud = baud
        self.stopbits = stopbits
        self.ser = None

    def open(self):
        self.ser = serial.Serial(
            self.port, self.baud, bytesize=8, parity="N",
            stopbits=serial.STOPBITS_TWO if self.stopbits == 2 else serial.STOPBITS_ONE,
            timeout=0.3, write_timeout=0.5, rtscts=False, dsrdtr=False,
        )

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
