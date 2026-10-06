"""Poste simulé : permet de tester l'interface et le partage CAT sans radio."""
import random
import time

from .base import RigDriver, s_text_from_db
from .ft991a import FT991A

DEFAULTS = {
    "af": 70, "rf": 255, "sql": 0, "pwr": 50, "mic": 50, "proc": False, "vox": False,
    "nb": False, "dnr": False, "dnr_lvl": 8, "dnf": False, "nar": False, "width": 13,
    "shift": 0, "contour": False, "contour_f": 1000, "apf": False, "notch": False,
    "notch_f": 100, "att": False, "pre": 1, "agc": 4, "atu": 0, "keyer": True,
    "bkin": False, "wpm": 20, "split": False, "vfob": 7074000, "rpt_shift": 0,
    "tone_mode": 0, "tone": 12,
}
SAMPLE_MEMORIES = [
    (1, 145500000, "FM", "APPEL"), (2, 145600000, "FM", "R0", 2, 2),
    (3, 145625000, "FM", "R1", 2, 2), (4, 145750000, "FM", "R6", 2, 2),
    (5, 430025000, "FM", "RU1", 2, 2), (6, 14074000, "PKTUSB", "FT8 20M"),
    (7, 7074000, "PKTUSB", "FT8 40M"), (8, 144174000, "PKTUSB", "FT8 2M"),
]


class SimDriver(RigDriver):
    name = "Simulateur"
    modes = FT991A.modes

    def __init__(self, port="SIM", baud=0, stopbits=1):
        super().__init__(port or "SIM", baud, stopbits)
        self.f, self.m, self.ptt = 14074000, "USB", False
        self.p = dict(DEFAULTS)
        self.info = {"ch": 1, "freq": 0, "clar": 0, "rx_clar": False, "tx_clar": False,
                     "mode": "USB", "vm": 0, "ctcss": 0, "shift": 0}
        self._s = 0.4

    def open(self):
        pass

    def close(self):
        pass

    def poll(self, st):
        time.sleep(0.01)
        self._s = min(1.0, max(0.0, self._s + random.uniform(-0.06, 0.06)))
        st.freq, st.mode, st.ptt = self.f, self.m, self.ptt
        if self.ptt:
            st.smeter = 0.0
            st.po, st.swr, st.swr_val = self.p["pwr"] / 100 * 0.8, 0.12, 1.3
            st.alc = 0.25 + random.uniform(0, 0.1)
        else:
            st.smeter = self._s
            st.s_db = round(-54 + self._s * 114)
            st.s_text = s_text_from_db(st.s_db)
            st.po = st.swr = st.alc = st.swr_val = 0.0
        st.p.update(self.p)
        st.p["info"] = dict(self.info)
        st.p["mem_tag"] = next((m[3] for m in SAMPLE_MEMORIES if m[0] == self.info["ch"]), "")

    def read_memories(self):
        time.sleep(0.5)
        out = []
        for ch, f, mode, tag, *rest in SAMPLE_MEMORIES:
            ctcss, shift = (rest + [0, 0])[:2]
            out.append({"ch": ch, "freq": f, "mode": mode, "tag": tag, "clar": 0,
                        "rx_clar": False, "tx_clar": False, "ctcss": ctcss, "shift": shift})
        return out

    def set_freq(self, hz):
        self.f = int(hz)

    def set_mode(self, mode):
        self.m = mode

    def set_ptt(self, on):
        self.ptt = bool(on)

    def set_param(self, key, value):
        self.p[key] = value

    def action(self, name, *args):
        i = self.info
        if name == "swap":
            self.f, self.p["vfob"] = self.p["vfob"], self.f
        elif name == "a_to_b":
            self.p["vfob"] = self.f
        elif name == "b_to_a":
            self.f = self.p["vfob"]
        elif name == "vm":
            i["vm"] = 0 if i["vm"] else 1
        elif name == "mem_recall":
            i["vm"], i["ch"] = 1, int(args[0])
            for ch, f, mode, *_r in SAMPLE_MEMORIES:
                if ch == i["ch"]:
                    self.f, self.m = f, mode
        elif name == "clar_step":
            i["clar"] = max(-9999, min(9999, i["clar"] + int(args[0])))
        elif name == "clar_clear":
            i["clar"] = 0
        elif name in ("rx_clar", "tx_clar"):
            i[name] = bool(args[0])
        elif name in ("up", "down"):
            self.f += 10000 if name == "up" else -10000
