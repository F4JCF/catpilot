"""Décodeur CW (morse) à partir de l'audio de réception du poste.

Principe :
1. on repère la note CW (pic le plus fort entre 300 et 1500 Hz, ou la tonalité CW du poste) ;
2. on mesure l'enveloppe du signal à cette fréquence (filtre étroit d'environ 100 Hz) ;
3. un seuil qui s'adapte au bruit et au signal découpe en « appuyé / relâché » ;
4. les durées donnent points, traits et espaces ; la vitesse (mots/min) s'adapte toute seule.
Aucune dépendance Qt : le module se teste seul.
"""
import collections
import math

import numpy as np

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F", "--.": "G", "....": "H",
    "..": "I", ".---": "J", "-.-": "K", ".-..": "L", "--": "M", "-.": "N", "---": "O", ".--.": "P",
    "--.-": "Q", ".-.": "R", "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4", ".....": "5", "-....": "6",
    "--...": "7", "---..": "8", "----.": "9",
    ".-.-.-": ".", "--..--": ",", "..--..": "?", "-..-.": "/", "-....-": "-", ".----.": "'",
    "---...": ":", "-.-.-.": ";", ".-..-.": '"', ".--.-.": "@", "-.-.--": "!",
    "-...-": "=", ".-.-.": "<AR>", "...-.-": "<SK>", "-.--.": "<KN>", ".-...": "<AS>",
    "........": "<HH>", "-.--.-": ")", "...-.": "<SN>",
}

STEP = 0.0025          # pas d'analyse de l'enveloppe (s)
WINDOW = 0.010         # largeur du filtre (s) : environ 100 Hz de bande


class CwDecoder:
    def __init__(self):
        self.auto = True               # suivre la note la plus forte
        self.freq = 700.0              # note CW suivie (Hz)
        self.pitch = 700.0             # tonalité CW du poste (utilisée si auto est faux)
        self.reset()

    def reset(self):
        self.sr = 0
        self._n = 0                    # numéro absolu de l'échantillon (continuité de phase)
        self._buf = np.zeros(0, np.float32)     # pour la recherche de la note
        self._tail = np.zeros(0, np.complex64)  # restes du filtre entre deux blocs
        self._since_fft = 0.0
        self._cand = None
        self.noise = None
        self.peak = None
        self._env = collections.deque(maxlen=int(2.0 / STEP))
        self._k, self._pend = 0, 0
        self.key = False
        self._dur = 0.0                # durée de l'état actuel (s)
        self.dit, self.dah = 0.060, 0.180   # durées moyennes point / trait (s), 20 mots/min au départ
        self._marks = collections.deque(maxlen=24)
        self._locked = False
        self._tone_t = -99.0           # dernier instant (s) où une note CW a été repérée
        self._sym = ""
        self._char_done = True
        self._word_done = True
        self.level = 0.0               # 0..1, pour un indicateur
        self.snr = 0.0

    @property
    def dot(self):
        return 0.5 * (self.dit + self.dah / 3)

    @property
    def wpm(self):
        return round(1.2 / self.dot)

    # --- entrée audio ----------------------------------------------------------------
    def feed(self, x, sr):
        """Reçoit des échantillons (float, mono) ; renvoie le texte nouvellement décodé."""
        if sr != self.sr:
            self.reset()
            self.sr = sr
        x = np.asarray(x, np.float32)
        if not len(x):
            return ""
        self._track_freq(x)
        f = self.freq if self.auto else self.pitch
        t = (self._n + np.arange(len(x))) / sr
        self._n += len(x)
        bb = np.concatenate([self._tail, (x * np.exp(-2j * math.pi * f * t)).astype(np.complex64)])
        # filtre adapté à la vitesse : environ 40 % d'un point (de 10 à 40 ms)
        step = max(1, int(sr * STEP))
        win = max(2, int(sr * min(0.040, max(WINDOW, 0.4 * self.dit))))
        nblk = (len(bb) - win) // step + 1 if len(bb) >= win else 0
        if nblk <= 0:
            self._tail = bb
            return ""
        cs = np.concatenate([[0], np.cumsum(bb)])
        idx = np.arange(nblk) * step
        env = np.abs(cs[idx + win] - cs[idx]) / win
        self._tail = bb[nblk * step:]
        out = []
        for e in env:
            out.append(self._sample(float(e)))
        return "".join(out)

    # --- recherche de la note --------------------------------------------------------
    def _track_freq(self, x):
        self._buf = np.concatenate([self._buf, x])[-int(self.sr * 1.0):]
        self._since_fft += len(x) / self.sr
        if self._since_fft < 0.4 or len(self._buf) < self.sr * 0.5:
            return
        self._since_fft = 0.0
        n = len(self._buf)
        spec = np.abs(np.fft.rfft(self._buf * np.hanning(n)))
        freqs = np.fft.rfftfreq(n, 1 / self.sr)
        band = (freqs > 300) & (freqs < 1500)
        if not band.any():
            return
        sb, fb = spec[band], freqs[band]
        med = np.median(sb) + 1e-12
        now = self._n / self.sr
        if not self.auto:                                 # note imposée : y a-t-il un signal dessus ?
            near = np.abs(fb - self.pitch) < 40
            if near.any() and sb[near].max() >= 5 * med:
                self._tone_t = now
            return
        near = np.abs(fb - self.freq) < 40
        if self._locked and near.any() and sb[near].max() >= 5 * med:
            self._tone_t = now                            # la note suivie est toujours là
        i = int(np.argmax(sb))
        if sb[i] < 8 * med:                               # rien qui dépasse nettement le bruit
            return
        fpk = float(fb[i])
        self._tone_t = now
        if not self._locked:
            self.freq, self._locked, self._cand = fpk, True, None
            self.noise = self.peak = None
        elif abs(fpk - self.freq) < 25:
            self.freq = 0.7 * self.freq + 0.3 * fpk
            self._cand = None
        elif self._cand is not None and abs(fpk - self._cand) < 25:   # confirmé deux fois de suite
            self.freq, self._cand = fpk, None
            self.noise = self.peak = None
        else:
            self._cand = fpk

    # --- découpage appuyé / relâché ------------------------------------------------
    def _sample(self, e):
        self._env.append(e)
        self._k += 1
        if self.noise is None or self._k >= 40:  # statistiques remises à jour toutes les 0,1 s
            if len(self._env) < int(0.25 / STEP):
                return ""
            self._k = 0
            a = np.fromiter(self._env, np.float32)
            # bruit seul ~ loi de Rayleigh : moyenne = 1,87 x 20e percentile
            self.noise = float(np.percentile(a, 20)) * 1.87 + 1e-9
            self.peak = max(float(np.percentile(a, 96)), self.noise)
            self.snr = 20 * math.log10(self.peak / self.noise)
        span = self.peak - self.noise
        self.level = min(1.0, max(0.0, (e - self.noise) / (span + 1e-12)))
        thr = max(self.noise * 2.2, self.noise + span * (0.40 if self.key else 0.55))
        on = self.snr >= 9 and e > thr
        out = ""
        if on != self.key:
            self._pend += 1
            if self._pend >= max(2, int(0.25 * self.dit / STEP)):   # anti-rebond : 1/4 de point
                d = self._dur - (self._pend - 1) * STEP
                if self.key:
                    self._mark(d)
                else:
                    self._space_end(d)
                self.key, self._dur, self._pend = on, (self._pend - 1) * STEP, 0
        else:
            self._pend = 0
        self._dur += STEP
        if not self.key:
            out = self._check_gap()
            # sans note CW repérée depuis 6 s, c'est du bruit : on n'affiche rien
            if out and (self._n / self.sr) - self._tone_t >= 6.0:
                out = ""
        return out

    def _mark(self, d):
        if d < max(0.010, self.dit * 0.3):      # parasite
            return
        self._marks.append(d)
        self._learn()
        self._sym += "." if d < math.sqrt(self.dit * self.dah) else "-"
        self._char_done = self._word_done = False
        if len(self._sym) > 9:                   # séquence absurde : on repart de zéro
            self._sym = ""

    def _learn(self):
        """Sépare les durées récentes en deux groupes (points / traits)."""
        m = np.log(np.array(self._marks))
        if len(m) >= 4:
            lo, hi = m.min(), m.max()
            if hi - lo > math.log(1.8):          # il y a bien des points et des traits
                for _ in range(8):
                    cut = 0.5 * (lo + hi)
                    a, b = m[m < cut], m[m >= cut]
                    if not len(a) or not len(b):
                        break
                    lo, hi = a.mean(), b.mean()
                dit, dah = math.exp(lo), math.exp(hi)
                if 2.0 <= dah / dit <= 4.5:
                    self.dit = 0.6 * self.dit + 0.4 * dit
                    self.dah = 0.6 * self.dah + 0.4 * dah
                    return
            # un seul groupe : on le range du côté le plus proche
            g = math.exp(m[-4:].mean())
            if abs(math.log(g / self.dit)) < abs(math.log(g / self.dah)):
                self.dit, self.dah = 0.7 * self.dit + 0.3 * g, 0.7 * self.dah + 0.3 * 3 * g
            else:
                self.dit, self.dah = 0.7 * self.dit + 0.3 * g / 3, 0.7 * self.dah + 0.3 * g
        self.dit = min(0.24, max(0.02, self.dit))
        self.dah = min(0.72, max(0.06, self.dah))

    def _space_end(self, d):
        pass

    def _check_gap(self):
        out = ""
        if not self._char_done and self._dur > 2.2 * self.dot:
            if self._sym:
                out += MORSE.get(self._sym, "*")
            self._sym = ""
            self._char_done = True
        if self._char_done and not self._word_done and self._dur > 5.5 * self.dot:
            out += " "
            self._word_done = True
        return out


# --- génération de morse (signal de test du simulateur) ----------------------------------
REVERSE = {v: k for k, v in MORSE.items() if len(v) == 1}


def keying(text, wpm):
    """Liste de (appuyé ?, durée en s) pour un texte."""
    dot = 1.2 / wpm
    seq = []
    for w, word in enumerate(text.upper().split()):
        if w:
            seq.append((False, 7 * dot))
        for c, ch in enumerate(word):
            if c:
                seq.append((False, 3 * dot))
            code = REVERSE.get(ch, "")
            for i, s in enumerate(code):
                if i:
                    seq.append((False, dot))
                seq.append((True, dot if s == "." else 3 * dot))
    return seq


class CwGenerator:
    """Produit en continu un message CW répété (pour le simulateur)."""

    def __init__(self, text="CQ CQ CQ DE F4JCF F4JCF K", wpm=20, freq=700.0, amp=0.05):
        self.freq, self.amp = freq, amp
        self.seq = keying(text, wpm) + [(False, 2.0)]
        self.total = sum(d for _, d in self.seq)
        self.edges = np.cumsum([0] + [d for _, d in self.seq])

    def samples(self, t):
        tt = np.mod(t, self.total)
        i = np.searchsorted(self.edges, tt, side="right") - 1
        i = np.clip(i, 0, len(self.seq) - 1)
        on = np.array([k for k, _ in self.seq])[i].astype(np.float32)
        return self.amp * on * np.sin(2 * math.pi * self.freq * t).astype(np.float32)
