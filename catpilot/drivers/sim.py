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
    "tone_mode": 0, "tone": 12, "pitch": 40, "vox_gain": 50, "mic_eq": False, "proc_lvl": 50,
    "mon": False, "mon_lvl": 30,
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
    max_freq = 470_000_000
    has_c4fm = True
    has_usb_audio = True
    menu_skip = {"031", "032", "033"}

    def __init__(self, port="SIM", baud=0, stopbits=1):
        super().__init__(port or "SIM", baud, stopbits)
        self.f, self.m, self.ptt = 14074000, "USB", False
        self.p = dict(DEFAULTS)
        self.info = {"ch": 1, "freq": 0, "clar": 0, "rx_clar": False, "tx_clar": False,
                     "mode": "USB", "vm": 0, "ctcss": 0, "shift": 0}
        self._s = 0.4
        self.mems = {}
        for ch, f, mode, tag, *rest in SAMPLE_MEMORIES:
            ctcss, shift = (rest + [0, 0])[:2]
            self.mems[ch] = {"ch": ch, "freq": f, "mode": mode, "tag": tag, "clar": 0,
                             "rx_clar": False, "tx_clar": False, "ctcss": ctcss, "shift": shift,
                             "raw": f"{ch:03d}{f:09d}+0000000000000000          "}
        self.menus = {f"{n:03d}": f"{n % 7}" for n in range(1, 154)}
        self.menus["031"] = "3"
        self.cw_log = []

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
        st.p["mem_tag"] = self.mems.get(self.info["ch"], {}).get("tag", "")

    def read_memories(self, progress=None):
        time.sleep(0.5)
        return [dict(m) for _ch, m in sorted(self.mems.items())]

    def write_memories(self, mems, template, progress=None):
        from .ft991a import CODE_TO_MODE
        for m in mems:
            m = dict(m)
            m["mode"] = CODE_TO_MODE.get(m.get("code"), "FM")
            m["mode_label"] = {"B": "FM-N", "D": "AM-N"}.get(m.get("code"))
            self.mems[int(m["ch"])] = m
        time.sleep(0.3)
        return [(int(m["ch"]), True) for m in mems]

    def read_menus(self, progress=None):
        time.sleep(0.5)
        return dict(self.menus)

    def write_menus(self, menus, progress=None):
        changed = [n for n, v in menus.items() if n not in self.menu_skip and self.menus.get(n) != v]
        for n in changed:
            self.menus[n] = menus[n]
        return {"changed": changed, "same": len(menus) - len(changed), "failed": [],
                "skipped": sorted(self.menu_skip & set(menus))}

    def read_menu(self, mid):
        return self.menus[mid]

    def write_menu(self, mid, value):
        if mid in self.menu_skip:
            return False
        self.menus[mid] = value
        return True

    def cw_send(self, text, slot=5):
        self.cw_log.append(text)

    def cw_play(self, slot):
        self.cw_log.append(f"<mémoire {slot}>")

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
        if name == "cw_text":
            self.cw_send(*args)
        elif name == "cw_play":
            self.cw_play(*args)
        elif name == "swap":
            self.f, self.p["vfob"] = self.p["vfob"], self.f
        elif name == "a_to_b":
            self.p["vfob"] = self.f
        elif name == "b_to_a":
            self.f = self.p["vfob"]
        elif name == "vm":
            i["vm"] = 0 if i["vm"] else 1
        elif name == "mem_recall":
            i["vm"], i["ch"] = 1, int(args[0])
            m = self.mems.get(i["ch"])
            if m:
                self.f, self.m = m["freq"], m["mode"]
        elif name == "clar_step":
            i["clar"] = max(-9999, min(9999, i["clar"] + int(args[0])))
        elif name == "clar_clear":
            i["clar"] = 0
        elif name in ("rx_clar", "tx_clar"):
            i[name] = bool(args[0])
        elif name in ("up", "down"):
            self.f += 10000 if name == "up" else -10000
