"""Pilote Yaesu FT-991A : protocole CAT texte (commandes terminées par « ; »).

Chaque réglage est décrit une fois dans PARAMS (commande de lecture, position
de la valeur dans la réponse, format d'écriture). Le pilote lit les réglages à
tour de rôle ; une commande refusée par le poste est marquée « non prise en
charge » et le bouton correspondant est grisé, sans couper la liaison.
"""
import time

from .base import RigDriver, RigRefused, RigTimeout, RigError, interp, s_text_from_db

MODE_TO_CODE = {
    "LSB": "1", "USB": "2", "CW": "3", "FM": "4", "AM": "5", "RTTY": "6",
    "CWR": "7", "PKTLSB": "8", "RTTYR": "9", "PKTFM": "A", "PKTUSB": "C", "C4FM": "E",
}
CODE_TO_MODE = {v: k for k, v in MODE_TO_CODE.items()}
CODE_TO_MODE.update({"B": "FM", "D": "AM"})   # FM-N, AM-N

SM_CAL = [(0, -54), (12, -48), (27, -42), (40, -36), (55, -30), (65, -24), (80, -18),
          (95, -12), (112, -6), (130, 0), (150, 10), (172, 20), (190, 30), (220, 40),
          (240, 50), (255, 60)]
SWR_CAL = [(0, 1.0), (26, 1.2), (52, 1.5), (89, 2.0), (150, 3.0), (255, 5.0)]


class P:
    def __init__(self, query, idx, kind="int", fmt=None):
        self.query, self.idx, self.kind, self.fmt = query, idx, kind, fmt


PARAMS = {
    "af":        P("AG0;", 3, "int", "AG0{:03d};"),     # gain BF 0-255
    "rf":        P("RG0;", 3, "int", "RG0{:03d};"),     # gain HF 0-255
    "sql":       P("SQ0;", 3, "int", "SQ0{:03d};"),     # squelch 0-100
    "pwr":       P("PC;", 2, "int", "PC{:03d};"),       # puissance 5-100 W
    "mic":       P("MG;", 2, "int", "MG{:03d};"),       # gain micro 0-100
    "proc":      P("PR0;", 3, "bool", "PR0{:d};"),      # processeur de modulation
    "vox":       P("VX;", 2, "bool", "VX{:d};"),
    "vox_gain":  P("VG;", 2, "int", "VG{:03d};"),       # gain VOX 0-100
    "mic_eq":    P("PR1;", 3, "bool", "PR1{:d};"),      # égaliseur micro paramétrique
    "proc_lvl":  P("PL;", 2, "int", "PL{:03d};"),       # niveau du processeur 0-100
    "mon":       P("ML0;", 3, "bool", "ML0{:03d};"),    # moniteur d'émission
    "mon_lvl":   P("ML1;", 3, "int", "ML1{:03d};"),     # niveau du moniteur 0-100
    "nb":        P("NB0;", 3, "bool", "NB0{:d};"),
    "dnr":       P("NR0;", 3, "bool", "NR0{:d};"),
    "dnr_lvl":   P("RL0;", 3, "int", "RL0{:02d};"),     # niveau DNR 1-15
    "dnf":       P("BC0;", 3, "bool", "BC0{:d};"),      # notch automatique
    "nar":       P("NA0;", 3, "bool", "NA0{:d};"),
    "width":     P("SH0;", 3, "int", "SH0{:02d};"),     # index de largeur de filtre
    "shift":     P("IS0;", 3, "int", "IS0{:+05d};"),    # IF shift en Hz
    "contour":   P("CO00;", 4, "bool", "CO00{:04d};"),
    "contour_f": P("CO01;", 4, "int", "CO01{:04d};"),   # 10-3200 Hz
    "apf":       P("CO02;", 4, "bool", "CO02{:04d};"),
    "notch":     P("BP00;", 4, "bool", "BP00{:03d};"),
    "notch_f":   P("BP01;", 4, "int", "BP01{:03d};"),   # x 10 Hz
    "att":       P("RA0;", 3, "bool", "RA0{:d};"),
    "pre":       P("PA0;", 3, "int", "PA0{:d};"),       # 0 IPO, 1 AMP1, 2 AMP2
    "agc":       P("GT0;", 3, "int", "GT0{:d};"),       # 0 OFF 1 FAST 2 MID 3 SLOW 4 AUTO
    "atu":       P("AC;", 4, "int", "AC00{:d};"),       # 0 arrêt, 1 marche
    "keyer":     P("KR;", 2, "bool", "KR{:d};"),
    "bkin":      P("BI;", 2, "bool", "BI{:d};"),
    "wpm":       P("KS;", 2, "int", "KS{:03d};"),       # 4-60 mots/min
    "pitch":     P("KP;", 2, "int", "KP{:02d};"),       # note CW : 300 + 10 x valeur (Hz)
    "split":     P("ST;", 2, "bool", "ST{:d};"),
    "vfob":      P("FB;", 2, "int", "FB{:09d};"),
    "rpt_shift": P("OS0;", 3, "int", "OS0{:d};"),       # 0 simplex, 1 +, 2 -
    "tone_mode": P("CT0;", 3, "int", "CT0{:d};"),       # 0 off, 1 TSQ, 2 tone, 3 DCS
    "tone":      P("CN00;", 4, "int", "CN00{:03d};"),   # index de tonalité CTCSS
    "info":      P("IF;", 2, "if"),                      # canal, clarifier, VFO/mémoire
}
SLOW_PER_CYCLE = 3
RETRY_AFTER = 8.0      # s avant de réessayer un réglage refusé par le poste

ACTIONS = {
    "swap": "SV;", "a_to_b": "AB;", "b_to_a": "BA;", "vm": "VM;",
    "up": "UP;", "down": "DN;", "zin": "ZI;", "clar_clear": "RC;", "tune": "AC002;",
    "qmb_store": "QI;", "qmb_recall": "QR;",
}
# Menus jamais réécrits lors d'une restauration : les changer couperait la liaison CAT.
MENU_SKIP = {"031", "032", "033"}        # CAT RATE, CAT TOT, CAT RTS


def parse_mem(s):
    """Décode le corps d'une réponse IF / MR / MT (sans les 2 lettres de tête)."""
    m = {"ch": int(s[0:3]), "freq": int(s[3:12]), "raw": s}
    try:
        m["clar"] = int(s[12:17])
        m["rx_clar"] = s[17] == "1"
        m["tx_clar"] = s[18] == "1"
        m["mode"] = CODE_TO_MODE.get(s[19], "?")
        m["mode_label"] = {"B": "FM-N", "D": "AM-N"}.get(s[19])
        m["vm"] = int(s[20])
        m["ctcss"] = int(s[21])
        m["shift"] = int(s[24])
        m["tag"] = s[26:].strip()        # s[25] est un champ fixe, pas une lettre du nom
    except (IndexError, ValueError):
        pass
    return m


class FT991A(RigDriver):
    name = "Yaesu FT-991A"
    modes = [m for m in MODE_TO_CODE if m != "C4FM"]   # modes exposés à Hamlib
    default_baud = 38400
    default_stopbits = 1
    max_freq = 470_000_000          # le FT-991A couvre aussi 2 m et 70 cm
    has_c4fm = True
    has_usb_audio = True            # codec audio USB intégré
    menu_skip = MENU_SKIP
    menu_stop_after = 0             # lire toute la plage de menus

    def __init__(self, *a):
        super().__init__(*a)
        self._keys = list(PARAMS)
        self._slow = 0
        self._fails = {}
        self.unsupported = {}      # réglage -> heure du refus
        self._context = None       # (mode, gamme de fréquence) au dernier cycle
        self._mem_cmd = "MT"
        self._tags = {}            # canal -> nom de la mémoire

    # --- échanges bas niveau ------------------------------------------------
    def _write(self, cmd):
        self.ser.write(cmd.encode("ascii"))

    def _query(self, cmd):
        self.ser.reset_input_buffer()
        self._write(cmd)
        r = self.ser.read_until(b";").decode("ascii", "ignore")
        if r == "?;":
            raise RigRefused(f"commande refusée : {cmd}")
        if not r.endswith(";"):
            raise RigTimeout(f"pas de réponse à {cmd}")
        if not r.startswith(cmd[:2]):
            raise RigError(f"réponse inattendue {r!r} à {cmd}")
        return r[:-1]

    @staticmethod
    def _num(s):
        return int("".join(c for c in s if c.isdigit()) or 0)

    # --- marche / arrêt -------------------------------------------------------
    def is_on(self):
        try:
            self._query("FA;")
            return True
        except RigError:
            return False

    def power_on(self, wait=15.0):
        if self.is_on():
            return False
        # Poste éteint : son processeur CAT dort. Un premier envoi le réveille,
        # le second, environ une seconde plus tard, déclenche réellement l'allumage.
        self._write("PS1;")
        time.sleep(1.0)
        self._write("PS1;")
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            time.sleep(0.5)
            if self.is_on():
                time.sleep(1.0)          # laisser le poste finir son démarrage
                return True
        raise RigError("le poste ne s'est pas allumé (alimentation 13,8 V coupée ?)")

    def power_off(self):
        self._write("PS0;")
        time.sleep(0.3)

    # --- lecture -----------------------------------------------------------
    def poll(self, st):
        st.freq = int(self._query("FA;")[2:])
        st.mode = CODE_TO_MODE.get(self._query("MD0;")[3:4], st.mode)
        st.ptt = self._query("TX;")[2:3] in ("1", "2")
        if st.ptt:
            st.po = self._num(self._query("RM5;")[3:6]) / 255
            raw = self._num(self._query("RM6;")[3:6])
            st.swr, st.swr_val = raw / 255, interp(SWR_CAL, raw)
            st.alc = self._num(self._query("RM4;")[3:6]) / 255
            st.smeter = 0.0
        else:
            raw = self._num(self._query("SM0;")[3:6])
            st.smeter = raw / 255
            st.s_db = round(interp(SM_CAL, raw))
            st.s_text = s_text_from_db(st.s_db)
            st.po = st.swr = st.alc = st.swr_val = 0.0
        # Beaucoup de refus dépendent du contexte (ATT ou DNR en FM/UHF, shift en FM...).
        # Au changement de mode ou de gamme, on redonne sa chance à tout le monde.
        ctx = (st.mode, 0 if st.freq < 60_000_000 else 1 if st.freq < 300_000_000 else 2)
        if ctx != self._context:
            self._context = ctx
            self.unsupported.clear()
            self._fails.clear()
        self._poll_slow(st)
        st.unsupported = set(self.unsupported)

    def _poll_slow(self, st):
        """Lit quelques réglages par cycle, à tour de rôle."""
        done = 0
        for _ in range(len(self._keys)):
            if done >= SLOW_PER_CYCLE:
                break
            key = self._keys[self._slow]
            self._slow = (self._slow + 1) % len(self._keys)
            refused_at = self.unsupported.get(key)
            if refused_at is not None and time.monotonic() - refused_at < RETRY_AFTER:
                continue
            done += 1
            p = PARAMS[key]
            try:
                body = self._query(p.query)[p.idx:]
                if p.kind == "if":
                    st.p[key] = info = parse_mem(body)
                    if info.get("vm") in (1, 2):     # mode mémoire : on cherche son nom
                        st.p["mem_tag"] = self._tag(info["ch"])
                elif p.kind == "bool":
                    st.p[key] = int(body) != 0
                else:
                    st.p[key] = int(body)
                self._fails.pop(key, None)
                self.unsupported.pop(key, None)
            except (RigError, ValueError):
                # « ?; » vient souvent d'un état temporaire : réglage indisponible
                # dans ce mode ou sur cette bande. On grise et on réessaiera.
                self._fails[key] = self._fails.get(key, 0) + 1
                if self._fails[key] >= 2:
                    self.unsupported[key] = time.monotonic()

    def _tag(self, ch):
        if ch not in self._tags:
            try:
                self._tags[ch] = parse_mem(self._query(f"MT{ch:03d};")[2:]).get("tag", "")
            except (RigError, ValueError, IndexError):
                self._tags[ch] = ""
        return self._tags[ch]

    def read_memories(self, progress=None):
        out = []
        for ch in range(1, 118):
            if progress and ch % 10 == 0:
                progress(f"Lecture des mémoires… {ch}/117")
            try:
                r = self._query(f"{self._mem_cmd}{ch:03d};")
            except RigRefused:
                if self._mem_cmd == "MT" and ch <= 3:
                    try:   # au cas où le poste ne connaîtrait pas MT : repli sur MR
                        r = self._query(f"MR{ch:03d};")
                        self._mem_cmd = "MR"
                    except RigError:
                        continue
                else:
                    continue           # canal vide
            except RigError:
                continue
            try:
                m = parse_mem(r[2:])
                m["ch"] = ch
                out.append(m)
                self._tags[ch] = m.get("tag", "")
            except (IndexError, ValueError):
                pass
        return out

    @staticmethod
    def build_mem(m, template):
        """Corps MT complet : on part d'un canal lu sur le poste et on remplace les champs."""
        t = list(template.ljust(38))
        t[3:12] = f"{int(m['freq']):09d}"
        t[12:17] = f"{int(m.get('clar', 0)):+05d}"
        t[17] = "1" if m.get("rx_clar") else "0"
        t[18] = "1" if m.get("tx_clar") else "0"
        t[19] = m["code"]
        t[21] = str(int(m.get("ctcss", 0)))
        t[24] = str(int(m.get("shift", 0)))
        t[26:38] = f"{m.get('tag', '')[:12]:<12}"
        t[0:3] = f"{int(m['ch']):03d}"
        return "".join(t[:38])

    def write_memories(self, mems, template, progress=None):
        """Écrit les canaux puis les relit pour vérifier. Renvoie [(canal, réussi)]."""
        out = []
        for i, m in enumerate(mems, 1):
            if progress:
                progress(f"Écriture des mémoires… {i}/{len(mems)}")
            body = self.build_mem(m, m.get("raw") or template)
            ok = False
            try:
                self._write(f"MT{body};")
                time.sleep(0.15)
                back = parse_mem(self._query(f"MT{int(m['ch']):03d};")[2:])
                ok = back["freq"] == int(m["freq"]) and back.get("tag", "") == m.get("tag", "")[:12].strip()
                self._tags[int(m["ch"])] = back.get("tag", "")
            except (RigError, ValueError, IndexError):
                pass
            out.append((int(m["ch"]), ok))
        return out

    # --- menus du poste (commande EX) -----------------------------------------------
    # Identifiants en texte : « 031 » sur le FT-991A, « 0506 » (groupe-item) sur le FT-891.
    def menu_ids(self):
        return [f"{n:03d}" for n in range(1, 161)]

    def read_menu(self, mid):
        return self._query(f"EX{mid};")[2 + len(mid):]

    def write_menu(self, mid, value):
        """Écrit un menu puis le relit. Renvoie True si la valeur est bien en place."""
        if mid in self.menu_skip:
            return False
        self._write(f"EX{mid}{value};")
        time.sleep(0.08)
        return self.read_menu(mid) == value

    def read_menus(self, progress=None):
        menus, misses = {}, 0
        for i, mid in enumerate(self.menu_ids(), 1):
            if progress and i % 10 == 0:
                progress(f"Lecture des menus du poste… {mid}")
            try:
                menus[mid] = self.read_menu(mid)
                misses = 0
            except RigError:
                misses += 1
                if self.menu_stop_after and misses >= self.menu_stop_after and menus:
                    break
        return menus

    def write_menus(self, menus, progress=None):
        res = {"changed": [], "same": 0, "failed": [], "skipped": sorted(self.menu_skip & set(menus))}
        for i, (mid, value) in enumerate(sorted(menus.items()), 1):
            if mid in self.menu_skip:
                continue
            if progress and i % 10 == 0:
                progress(f"Restauration des menus… {i}/{len(menus)}")
            try:
                if self.read_menu(mid) == value:
                    res["same"] += 1
                elif self.write_menu(mid, value):
                    res["changed"].append(mid)
                else:
                    res["failed"].append(mid)
            except RigError:
                res["failed"].append(mid)
        return res

    # --- CW au clavier par la mémoire du keyer du poste --------------------------------
    def cw_send(self, text, slot=5):
        """Écrit le texte dans la mémoire de keyer « slot » puis la fait jouer."""
        self._write(f"KM{slot}{text}}};")      # « } » marque la fin du message
        time.sleep(0.1)
        self._write(f"KY{slot};")

    def cw_play(self, slot):
        self._write(f"KY{int(slot)};")

    # --- commandes ---------------------------------------------------------
    def set_freq(self, hz):
        self._write(f"FA{int(hz):09d};")
        time.sleep(0.02)

    def set_mode(self, mode):
        code = MODE_TO_CODE.get(mode)
        if code:
            self._write(f"MD0{code};")

    def set_ptt(self, on):
        self._write("TX1;" if on else "TX0;")

    def set_param(self, key, value):
        p = PARAMS.get(key)
        if p and p.fmt:
            self._write(p.fmt.format(bool(value) if p.kind == "bool" else int(value)))

    def action(self, name, *args):
        if name == "cw_text":
            self.cw_send(*args)
        elif name == "cw_play":
            self.cw_play(*args)
        elif name == "mem_recall":
            self._write(f"MC{int(args[0]):03d};")
        elif name == "clar_step":
            hz = int(args[0])
            self._write(f"RU{hz:04d};" if hz > 0 else f"RD{-hz:04d};")
        elif name == "rx_clar":
            self._write(f"RT{int(bool(args[0]))};")
        elif name == "tx_clar":
            self._write(f"XT{int(bool(args[0]))};")
        elif name in ACTIONS:
            self._write(ACTIONS[name])
