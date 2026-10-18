"""Modems « clavier à clavier » : PSK31 (BPSK31) et RTTY 45,45 bauds (170 Hz).

Réception en continu par blocs (fonction feed), émission en fabriquant le signal audio
complet d'un texte (fonction modulate). Sans dépendance Qt : testable seul.
"""
import math

import numpy as np

# --- PSK31 ---------------------------------------------------------------------------------
_VARI = ("1010101011 1011011011 1011101101 1101110111 1011101011 1101011111 1011101111 1011111101 1011111111 "
         "11101111 11101 1101101111 1011011101 11111 1101110101 1110101011 1011110111 1011110101 1110101101 "
         "1110101111 1101011011 1101101011 1101101101 1101010111 1101111011 1101111101 1110110111 1101010101 "
         "1101011101 1110111011 1011111011 1101111111 1 111111111 101011111 111110101 111011011 1011010101 "
         "1010111011 101111111 11111011 11110111 101101111 111011111 1110101 110101 1010111 110101111 10110111 "
         "10111101 11101101 11111111 101110111 101011011 101101011 110101101 110101011 110110111 11110101 "
         "110111101 111101101 1010101 111010111 1010101111 1010111101 1111101 11101011 10101101 10110101 1110111 "
         "11011011 11111101 101010101 1111111 111111101 101111101 11010111 10111011 11011101 10101011 11010101 "
         "111011101 10101111 1101111 1101101 101010111 110110101 101011101 101110101 101111011 1010101101 "
         "111110111 111101111 111111011 1010111111 101101101 1011011111 1011 1011111 101111 101101 11 111101 "
         "1011011 101011 1101 111101011 10111111 11011 111011 1111 111 111111 110111111 10101 10111 101 110111 "
         "1111011 1101011 11011111 1011101 111010101 1010110111 110111011 1010110101 1011010111 1110110101").split()
VARICODE = {chr(i): c for i, c in enumerate(_VARI)}
VARI_DEC = {c: chr(i) for i, c in enumerate(_VARI)}

BAUD_PSK = 31.25
FS2 = 500.0                     # fréquence après décimation (16 échantillons par symbole)


def _lowpass(fc, fs, taps):
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * fc / fs * n) * np.hamming(taps)
    return (h / h.sum()).astype(np.float32)


class _Down:
    """Mélange vers la bande de base puis décimation à FS2, avec mémoire entre les blocs."""

    def __init__(self, cutoff, out_rate=FS2, taps=129):
        self.out_rate = out_rate
        self.cutoff, self.taps = cutoff, taps
        self.sr = 0

    def reset(self, sr):
        self.sr = sr
        self.n = 0
        self.d1 = max(1, int(round(sr / (self.out_rate * 4))))     # moyenne glissante vers 4 x FS2
        self.mid = sr / self.d1
        self.h = _lowpass(self.cutoff, self.mid, self.taps)
        self.d2 = max(1, int(round(self.mid / self.out_rate)))
        self.rest = np.zeros(0, np.complex64)
        self.hist = np.zeros(self.taps - 1, np.complex64)
        self.phase2 = 0
        self.ph = 0.0

    @property
    def rate(self):
        return self.mid / self.d2

    def run(self, x, sr, f):
        if sr != self.sr:
            self.reset(sr)
        w = 2 * math.pi * f / sr
        ph = self.ph + w * np.arange(len(x))
        self.ph = float((self.ph + w * len(x)) % (2 * math.pi))
        self.n += len(x)
        bb = np.concatenate([self.rest, (x * np.exp(-1j * ph)).astype(np.complex64)])
        k = len(bb) // self.d1
        self.rest = bb[k * self.d1:]
        if not k:
            return np.zeros(0, np.complex64)
        y = bb[:k * self.d1].reshape(k, self.d1).mean(axis=1)
        z = np.concatenate([self.hist, y])
        self.hist = z[-(self.taps - 1):]
        filt = np.convolve(z, self.h, mode="valid")
        out = filt[self.phase2::self.d2]
        self.phase2 = (self.phase2 - len(filt)) % self.d2
        return out.astype(np.complex64)


class Psk31Rx:
    def __init__(self):
        self.freq = 1000.0
        self.afc = True
        self.squelch = 0.25           # qualité minimale (0 à 1) pour afficher le texte
        self.reset()

    def reset(self):
        self.down = _Down(cutoff=40.0)
        self.down.sr = 0
        self.buf = np.zeros(0, np.complex64)
        self.tn = 0.0                 # instant du prochain symbole (en échantillons de buf)
        self.prev = 0j
        self.bits = ""
        self.quality = 0.0
        self.level = 0.0
        self.peak = 1e-9

    def set_freq(self, f):
        self.freq = float(f)
        self.bits, self.quality = "", 0.0

    def _at(self, t):
        i = int(t)
        f = t - i
        return self.buf[i] * (1 - f) + self.buf[i + 1] * f

    def feed(self, x, sr):
        y = self.down.run(np.asarray(x, np.float32), sr, self.freq)
        if not len(y):
            return ""
        self.buf = np.concatenate([self.buf, y])
        sps = self.down.rate / BAUD_PSK
        q = sps / 4
        out = []
        if self.tn < q:
            self.tn = q
        while self.tn + q + 2 < len(self.buf):
            v = self._at(self.tn)
            early, late = abs(self._at(self.tn - q)), abs(self._at(self.tn + q))
            # rythme : l'enveloppe est maximale aux instants des symboles
            gain = 0.03 if self.quality > 0.6 else 0.12
            err = (late - early) / (late + early + 1e-12)
            self.tn += sps + gain * sps * err
            out.append(self._symbol(v))
        cut = min(int(self.tn - q - 1), len(self.buf))   # jamais au-delà des échantillons reçus
        if cut > 0:
            self.buf = self.buf[cut:]
            self.tn -= cut
        return "".join(out)

    def _symbol(self, v):
        d = v * np.conj(self.prev)
        self.prev = v
        a = abs(v)
        if abs(d) < 1e-20:
            return ""
        ang = math.atan2(d.imag, d.real)
        self.quality = 0.95 * self.quality + 0.05 * math.cos(2 * ang)
        self.level = 0.9 * self.level + 0.1 * a
        self.peak = max(a, self.peak * 0.995)
        carrier = a > 0.35 * self.peak            # la porteuse est toujours là
        if self.afc and self.quality > 0.2:
            # erreur de phase par symbole, modulation retirée (angle doublé)
            e = math.atan2(math.sin(2 * ang), math.cos(2 * ang)) / 2
            df = e / (2 * math.pi) * BAUD_PSK
            self.freq += max(-1.0, min(1.0, 0.08 * df))
        self.bits += "1" if d.real > 0 else "0"
        if self.bits.endswith("00"):
            code = self.bits[:-2]
            self.bits = ""
            if code and self.quality >= self.squelch and carrier:
                ch = VARI_DEC.get(code)
                if ch is not None and (ch >= " " or ch in "\n\t"):
                    return ch
        elif len(self.bits) > 14:
            self.bits = ""
        return ""


def psk31_modulate(text, f, sr, amp=0.6):
    """Signal audio complet : préambule (inversions), texte, postambule (porteuse pure)."""
    bits = "0" * 48
    for ch in text.replace("\r\n", "\n").replace("\n", "\r\n"):
        code = VARICODE.get(ch) or VARICODE.get("?")
        bits += code + "00"
    bits += "1" * 32
    sps = sr / BAUD_PSK
    n_total = int(len(bits) * sps)
    t_idx = np.arange(n_total)
    sym = np.minimum((t_idx / sps).astype(int), len(bits) - 1)
    frac = t_idx / sps - sym
    signs = np.empty(len(bits))
    s = 1.0
    prev_signs = np.empty(len(bits))
    for i, b in enumerate(bits):
        prev_signs[i] = s
        if b == "0":
            s = -s
        signs[i] = s
    rev = signs[sym] != prev_signs[sym]
    base = np.where(rev, prev_signs[sym] * np.cos(math.pi * frac), signs[sym])
    # montée et descente douces de 20 ms
    ramp = int(0.02 * sr)
    env = np.ones(n_total)
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    t = t_idx / sr
    return (amp * base * env * np.cos(2 * math.pi * f * t)).astype(np.float32)


# --- RTTY ---------------------------------------------------------------------------------
LTRS = "\x00E\nA SIU\rDRJNFCKTZLWHYPQOBG\x0eMXV\x0f"
FIGS = "\x003\n- \x0787\r$4',!:(5\")2#6019?&\x0e./;\x0f"
# codes 27 = FIGS, 31 = LTRS (positions 0x1B et 0x1F)
LTRS = list(LTRS)
FIGS = list(FIGS)
LTRS[27], LTRS[31], FIGS[27], FIGS[31] = "<F>", "<L>", "<F>", "<L>"
ENC_L = {c: i for i, c in enumerate(LTRS) if len(c) == 1 and c not in "\x00"}
ENC_F = {c: i for i, c in enumerate(FIGS) if len(c) == 1 and c not in "\x00"}
CODE_FIGS, CODE_LTRS = 27, 31


class RttyRx:
    def __init__(self, baud=45.45, shift=170.0):
        self.baud, self.shift = baud, shift
        self.freq = 1500.0               # centre entre les deux tonalités
        self.reverse = False
        self.squelch = 0.35
        self.reset()

    def reset(self):
        cut = self.baud * 0.75
        self.dm = _Down(cutoff=cut, out_rate=self.baud * 16, taps=97)
        self.ds = _Down(cutoff=cut, out_rate=self.baud * 16, taps=97)
        self.dm.sr = self.ds.sr = 0
        self.mpk = self.spk = 1e-6
        self.state = "idle"
        self.cnt = 0
        self.bits = []
        self.prev_mark = True
        self.figs = False
        self.quality = 0.0
        self.level = 0.0
        self.fs_out = self.baud * 16

    def set_freq(self, f):
        self.freq = float(f)
        self.reset()

    def feed(self, x, sr):
        x = np.asarray(x, np.float32)
        fm = self.freq + self.shift / 2
        fsp = self.freq - self.shift / 2
        if self.reverse:
            fm, fsp = fsp, fm
        m = np.abs(self.dm.run(x, sr, fm))
        sp = np.abs(self.ds.run(x, sr, fsp))
        n = min(len(m), len(sp))
        out = []
        spb = self.dm.rate / self.baud        # échantillons par bit (environ 16)
        for i in range(n):
            a, b = float(m[i]), float(sp[i])
            # suivi des crêtes (contrôle automatique de seuil)
            self.mpk = max(a, 0.9985 * self.mpk)
            self.spk = max(b, 0.9985 * self.spk)
            d = a / self.mpk - b / self.spk
            tot = a + b + 1e-12
            self.quality = 0.995 * self.quality + 0.005 * abs(a - b) / tot
            self.level = 0.99 * self.level + 0.01 * tot
            mark = d > 0
            if self.state == "idle":
                if self.prev_mark and not mark:
                    self.state, self.cnt, self.bits = "run", 0.0, []
                    self.nxt = 0.5 * spb          # milieu du bit de départ
            else:
                self.cnt += 1
                if self.cnt >= self.nxt:
                    k = len(self.bits)            # 0 : départ, 1 à 5 : données, 6 : arrêt
                    if k == 0 and getattr(self, "_started", False) is False:
                        if mark:
                            self.state = "idle"   # fausse alerte
                        else:
                            self._started = True
                            self.nxt += spb
                    elif len(self.bits) < 5:
                        self.bits.append(1 if mark else 0)
                        self.nxt += spb
                    else:
                        self.state = "idle"
                        self._started = False
                        if mark:                  # bit d'arrêt correct
                            ch = self._char(sum(bb << j for j, bb in enumerate(self.bits)))
                            if ch and self.quality >= self.squelch:
                                out.append(ch)
                    if self.state == "idle":
                        self._started = False
            self.prev_mark = mark
        return "".join(out)

    def _char(self, code):
        if code == CODE_FIGS:
            self.figs = True
            return ""
        if code == CODE_LTRS:
            self.figs = False
            return ""
        c = (FIGS if self.figs else LTRS)[code]
        if c == " ":
            self.figs = False                       # USOS : retour aux lettres après une espace
        if c == "\r" or c == "\x00":
            return ""
        return c if len(c) == 1 and (c >= " " or c == "\n") else ""


def rtty_modulate(text, f, sr, baud=45.45, shift=170.0, amp=0.6, reverse=False):
    codes = [CODE_LTRS] * 4                           # quelques LTRS pour caler le récepteur
    figs = False
    for ch in text.upper().replace("\r\n", "\n"):
        if ch == "\n":
            codes += [8, 2]                           # CR LF
            continue
        if ch == " ":
            codes.append(ENC_L[" "])
            figs = False                              # le récepteur (USOS) repasse en lettres
            continue
        if ch in ENC_L and not figs:
            codes.append(ENC_L[ch])
        elif ch in ENC_F:
            if not figs:
                codes.append(CODE_FIGS)
                figs = True
            codes.append(ENC_F[ch])
        elif ch in ENC_L:
            codes += [CODE_LTRS, ENC_L[ch]]
            figs = False
    codes += [CODE_LTRS, CODE_LTRS]
    bits = [1] * int(baud * 0.4)                      # repos (mark) avant
    for c in codes:
        bits += [0] + [(c >> k) & 1 for k in range(5)] + [1, "h"]   # 1,5 bit d'arrêt
    bits += [1] * int(baud * 0.2)
    spb = sr / baud
    freqs = []
    for b in bits:
        n = int(round(spb * (0.5 if b == "h" else 1)))
        mark = (b != 0)
        if reverse:
            mark = not mark
        freqs.append(np.full(n, f + (shift / 2 if mark else -shift / 2)))
    fr = np.concatenate(freqs)
    phase = 2 * math.pi * np.cumsum(fr) / sr
    ramp = int(0.01 * sr)
    env = np.ones(len(fr))
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    return (amp * env * np.sin(phase)).astype(np.float32)
