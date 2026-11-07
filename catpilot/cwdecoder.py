"""Décodeur CW (morse) à partir de l'audio de réception du poste.

Principe :
1. on repère la note CW (pic le plus fort entre 250 et 1500 Hz d'un spectre moyenné, ou la
   tonalité CW du poste) ;
2. on mesure l'enveloppe du signal à cette fréquence avec un filtre adapté à la vitesse ;
3. les niveaux du bruit et du signal sont suivis en continu (fenêtre centrée : tient le QSB) ;
4. un décodage de Viterbi choisit la suite « appuyé / relâché » la plus probable, avec une durée
   minimale par élément : il résiste au bruit bien mieux qu'un simple seuil (décision retardée
   d'environ une seconde) ;
5. les durées donnent points, traits et espaces ; la vitesse et les espaces (lettres, mots,
   Farnsworth) s'apprennent tout seuls.
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

FILT = 0.6             # longueur du filtre adapté, en points
MINRUN = 0.35          # durée minimale d'un élément ou d'un espace, en points
LLR_K = 6.0            # poids de la vraisemblance par pas (les pas voisins sont liés par le filtre)
LAG = 12.0             # retard de décision (en points)
MODE = 0
ASC = 0.75
TAU_MAX = 4.0
CLIP = 4.0
LLR_K2 = 3.0
PKQ = 90
RECENT = 1.2           # fenêtre du niveau du signal (s) : suit le QSB
GATE = 5.0             # rapport signal/bruit minimum (dB)
STEP = 0.0025          # pas d'analyse de l'enveloppe (s) : 400 points par seconde


def _pct(a, q):
    return float(np.percentile(a, q)) if len(a) else 0.0


class CwDecoder:
    """Décodeur en flux. Améliorations (0.28.6) :
    - spectre moyenné sur plusieurs secondes pour trouver une note faible ; verrouillage stable
      (un signal voisin ne prend la main que s'il est nettement plus fort, deux fois de suite) ;
    - correction fine de la note par la phase du signal (suit la dérive) ;
    - filtre adapté à la vitesse (70 % d'un point) : la bande se resserre aux vitesses lentes ;
    - niveaux « bruit » et « signal » suivis en continu sur une fenêtre courte : tient le QSB ;
    - seuil à hystérésis entre bruit et signal, sans barrière de 9 dB ;
    - espaces appris comme les points et traits (trois groupes : entre éléments, lettres, mots),
      ce qui décode aussi le Farnsworth et la manipulation à la main.
    """

    def __init__(self):
        self.auto = True               # suivre la note la plus forte
        self.freq = 700.0              # note CW suivie (Hz)
        self.pitch = 700.0             # tonalité CW du poste (utilisée si auto est faux)
        self.reset()

    def reset(self):
        self.sr = 0
        self._ph = 0.0                 # phase de l'oscillateur local
        self._n = 0                    # numéro absolu de l'échantillon (continuité de phase)
        self._buf = np.zeros(0, np.float32)     # pour la recherche de la note
        self._psd = None               # spectre moyenné
        self._since_fft = 0.0
        self._cand = None
        self._tail = np.zeros(0, np.complex64)  # reste de la 1re décimation
        self._z = collections.deque(maxlen=64)  # signal complexe décimé (400/s) pour le filtre adapté
        self._env = collections.deque(maxlen=int(3.0 / STEP))
        self._dq = collections.deque()
        self._recent = collections.deque(maxlen=int(RECENT / STEP))
        self._k = 0
        self.noise = None
        self.peak = None
        self._S = None
        self._m = 2
        self._bp = []
        self._vt0 = 0
        self._vkey, self._vrun = False, 1000
        self.key = False
        self._dur = 0.0                # durée de l'état actuel (s)
        self.dit, self.dah = 0.060, 0.180   # durées moyennes point / trait (s), 20 mots/min au départ
        self._marks = collections.deque(maxlen=24)
        self._gaps = collections.deque(maxlen=40)
        self._char_thr, self._word_thr = 2.0, 5.0    # en points
        self._egap = 0.0
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
        # un élément mesuré est un peu trop long et l'espace qui suit un peu trop court du même
        # écart (filtre) : leur moyenne donne la vraie durée du point
        u = 0.5 * (self.dit + self._egap) if self._egap else self.dot
        return round(1.2 / u)

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
        # oscillateur à phase continue : changer de note ne crée pas de saut de phase
        ph = self._ph + 2 * math.pi * f * np.arange(len(x)) / sr
        self._ph = float((self._ph + 2 * math.pi * f * len(x) / sr) % (2 * math.pi))
        self._n += len(x)
        bb = np.concatenate([self._tail, (x * np.exp(-1j * ph)).astype(np.complex64)])
        step = max(1, int(round(sr * STEP)))
        nblk = len(bb) // step
        self._tail = bb[nblk * step:]
        if not nblk:
            return ""
        z = bb[:nblk * step].reshape(nblk, step).mean(axis=1)     # 1er filtre : 400 Hz de large
        out = []
        for v in z:
            out.append(self._sample(complex(v)))
        return "".join(out)

    # --- recherche de la note --------------------------------------------------------
    def _track_freq(self, x):
        self._buf = np.concatenate([self._buf, x])[-int(self.sr * 1.0):]
        self._since_fft += len(x) / self.sr
        if self._since_fft < 0.4 or len(self._buf) < self.sr * 0.5:
            return
        self._since_fft = 0.0
        n = len(self._buf)
        p = np.abs(np.fft.rfft(self._buf * np.hanning(n))) ** 2
        freqs = np.fft.rfftfreq(n, 1 / self.sr)
        band = (freqs > 250) & (freqs < 1500)
        if not band.any():
            return
        p, fb = p[band], freqs[band]
        if self._psd is None or len(self._psd) != len(p):
            self._psd = p
        else:
            self._psd = 0.6 * self._psd + 0.4 * p           # moyenne sur ~2 s
        sb = np.sqrt(self._psd)
        sb = np.convolve(sb, np.ones(3) / 3, "same")          # regroupe les 3 cases autour du pic
        med = np.median(sb) + 1e-12
        now = self._n / self.sr
        if not self.auto:                                 # note imposée : y a-t-il un signal dessus ?
            near = np.abs(fb - self.pitch) < 40
            if near.any() and sb[near].max() >= 3.5 * med:
                self._tone_t = now
            return
        near = np.abs(fb - self.freq) < 30
        cur = float(sb[near].max()) if near.any() else 0.0
        if self._locked and cur >= 3.5 * med:
            self._tone_t = now                            # la note suivie est toujours là
        i = int(np.argmax(sb))
        if sb[i] < 4.5 * med:                             # rien qui dépasse nettement le bruit
            return
        fpk = float(fb[i])
        if 0 < i < len(sb) - 1:                           # position fine du pic
            a, b, c = sb[i - 1], sb[i], sb[i + 1]
            den = a - 2 * b + c
            if den:
                fpk += 0.5 * (a - c) / den * (fb[1] - fb[0])
        self._tone_t = now
        if not self._locked:
            self._set_freq(fpk)
            self._locked = True
        elif abs(fpk - self.freq) < 30:
            self._cand = None                             # même signal : suivi doux (dérive)
            self.freq = 0.85 * self.freq + 0.15 * fpk
        elif cur < 3.5 * med or sb[i] > 1.6 * cur:        # le signal suivi a disparu ou un autre est bien plus fort
            if self._cand is not None and abs(fpk - self._cand) < 25:
                self._set_freq(fpk)
                self._cand = None
            else:
                self._cand = fpk
        else:
            self._cand = None

    def _set_freq(self, f):
        self.freq = f
        self._dq.clear()
        self._z.clear()
        self._env.clear()
        self._recent.clear()
        self.noise = self.peak = None

    # --- découpage appuyé / relâché ------------------------------------------------
    def _sample(self, z):
        self._z.append(z)
        L = int(min(60, max(2, round(FILT * self.dot / STEP))))   # filtre adapté à la durée d'un point
        L = min(L, len(self._z))
        acc = 0j
        for k in range(1, L + 1):
            acc += self._z[-k]
        e = abs(acc) / L
        self._env.append(e)
        self._recent.append(e)
        self._k += 1
        if self.noise is None or self._k >= 20:  # niveaux remis à jour toutes les 50 ms
            if len(self._env) < int(0.5 / STEP):
                return ""
            self._k = 0
            a = np.fromiter(self._env, np.float32)
            # bruit seul ~ loi de Rayleigh : moyenne = 1,65 x 25e percentile
            noise = _pct(a, 25) * 1.65 + 1e-12
            r = np.fromiter(self._recent, np.float32)
            pk = max(_pct(r, PKQ), noise)                   # niveau du signal, sur ~1 s (QSB)
            self.noise = noise if self.noise is None else 0.7 * self.noise + 0.3 * noise
            self.peak = pk if self.peak is None else 0.5 * self.peak + 0.5 * pk
            self.snr = 20 * math.log10(self.peak / self.noise)
        span = self.peak - self.noise
        self.level = min(1.0, max(0.0, (e - self.noise) / (span + 1e-12)))
        # les niveaux sont mesurés sur une fenêtre centrée : on décide un peu plus tard
        self._dq.append(e)
        if len(self._dq) <= int(0.5 * RECENT / STEP):
            return ""
        e = self._dq.popleft()
        # vraisemblance « appuyé » contre « relâché » (Rice contre Rayleigh)
        sig2 = (self.noise / 1.2533) ** 2                 # sigma² du bruit
        A = ASC * math.sqrt(max(self.peak ** 2 - 2 * sig2, 0.25 * self.peak ** 2))
        if self.snr < GATE:
            llr = -3.0
        elif MODE == 0:
            xx = e * A / sig2
            li0 = xx - 0.5 * math.log(2 * math.pi * xx) if xx > 30 else math.log(float(np.i0(xx)))
            llr = (li0 - A * A / (2 * sig2)) * LLR_K / L
        else:
            # puissance rapportée au bruit, seuil plafonné : un signal qui s'enfonce dans le QSB
            # reste « appuyé » tant qu'il dépasse nettement le bruit
            pw = e * e / (2 * sig2)
            tau = min(TAU_MAX, max(1.6, 0.5 * (1 + A * A / (2 * sig2))))
            llr = max(-CLIP, min(CLIP, pw - tau)) * LLR_K2 / L
        return self._vstep(llr)

    # --- Viterbi en flux, à durée minimale (« appuyé » ou « relâché » au moins MINRUN point) ----
    def _vinit(self, key, run):
        m = self._m
        NEG = -1e18
        self._S = [NEG] * m          # S[i] : relâché depuis i+1 pas (S[m-1] : depuis au moins m)
        self._M = [NEG] * m
        (self._M if key else self._S)[min(run, m) - 1] = 0.0
        self._bp = []                # par pas : (S long venait de S long ?, M long venait de M long ?)
        self._vt0 = 0                # nombre de pas déjà rendus parmi ceux en mémoire

    def _vstep(self, llr):
        dsamp = self.dot / STEP
        m = max(2, int(round(MINRUN * dsamp)))
        if self._S is None:
            self._m = m
            self._vinit(False, 1000)
        elif abs(m - self._m) >= max(2, 0.25 * self._m):          # la vitesse a changé
            out = self._vcommit(final=True)
            k, r = self._vkey, self._vrun
            self._m = m
            self._vinit(k, r)
            return out + self._vstep(llr)
        m = self._m
        lp = -math.log(1.0 + 1.2 * dsamp)                         # changer d'état après la durée minimale
        lq = math.log(1.0 - math.exp(lp))
        S, M = self._S, self._M
        s0 = M[-1] + lp                       # on relâche
        m0 = S[-1] + lp                       # on appuie
        a1, a2 = S[-2], S[-1] + lq
        b1, b2 = M[-2], M[-1] + lq
        S = [s0] + S[:-2] + [max(a1, a2)]
        M = [m0 + llr] + [v + llr for v in M[:-2]] + [max(b1, b2) + llr]
        top = max(S[-1], M[-1], max(S), max(M))
        if top > 1e6 or top < -1e6:
            S = [v - top for v in S]
            M = [v - top for v in M]
        self._S, self._M = S, M
        self._bp.append((a2 >= a1, b2 >= b1))
        if len(self._bp) - self._vt0 >= 40 + int(LAG * max(1.0, dsamp)):   # rendre ce qui est sûr
            return self._vcommit(final=False)
        return ""

    def _vcommit(self, final):
        if self._S is None or not self._bp:
            return ""
        m, n = self._m, len(self._bp)
        S, M = self._S, self._M
        bs, bm = max(range(m), key=lambda i: S[i]), max(range(m), key=lambda i: M[i])
        st = ("M", bm) if M[bm] > S[bs] else ("S", bs)
        lag = 0 if final else int(LAG * max(1.0, self.dot / STEP))
        path = [False] * n
        for t in range(n - 1, self._vt0 - 1, -1):
            kind, i = st
            path[t] = kind == "M"
            fs, fm = self._bp[t]
            if i == 0:
                st = ("S" if kind == "M" else "M", m - 1)
            elif i == m - 1 and (fs if kind == "S" else fm):
                st = (kind, m - 1)
            else:
                st = (kind, i - 1)
        end = n if final else max(self._vt0, n - lag)
        out = []
        for t in range(self._vt0, end):
            on = path[t]
            out.append(self._step(on))
            if on == self._vkey:
                self._vrun += 1
            else:
                self._vkey, self._vrun = on, 1
        self._vt0 = end
        if self._vt0 > 4000:                  # on oublie les pas déjà rendus
            drop = self._vt0 - 1
            del self._bp[:drop]
            self._vt0 -= drop
        return "".join(out)

    def flush(self):
        """Rend tout ce qui est en attente (fin de réception)."""
        return self._vcommit(final=True)

    def _step(self, on):
        """Un pas de 2,5 ms déjà tranché : appuyé ou relâché."""
        out = ""
        if on != self.key:
            if self.key:
                self._mark(self._dur)
            else:
                self._space_end(self._dur)
            self.key, self._dur = on, 0.0
        self._dur += STEP
        if not self.key:
            out = self._check_gap()
            # sans note CW repérée depuis 6 s, c'est du bruit : on n'affiche rien
            if out and (self._n / self.sr) - self._tone_t >= 6.0:
                out = ""
        return out

    def _mark(self, d):
        if d < max(0.008, self.dit * 0.25):      # parasite
            return
        if d > 6 * self.dah and d > 0.5:         # porteuse ou bruit long : pas du morse
            self._sym = ""
            return
        self._marks.append(d)
        self._learn()
        self._sym += "." if d < math.sqrt(self.dit * self.dah) else "-"
        self._char_done = self._word_done = False
        if len(self._sym) > 8:                   # séquence absurde : on repart de zéro
            self._sym = ""

    def _learn(self):
        """Sépare les durées récentes en deux groupes (points / traits), sans se laisser entraîner
        par deux éléments collés (signal faible) ou par un parasite."""
        d = self._marks[-1]
        if d > 2.2 * self.dah or d < 0.4 * self.dit:
            return
        m = np.log(np.array([x for x in self._marks if 0.4 * self.dit <= x <= 2.2 * self.dah]))
        dit, dah = self.dit, self.dah
        if len(m) >= 6 and m.max() - m.min() > math.log(1.8):     # il y a bien des points et des traits
            cut = 0.5 * (m.min() + m.max())
            for _ in range(8):
                a, b = m[m < cut], m[m >= cut]
                if not len(a) or not len(b):
                    break
                lo, hi = float(np.median(a)), float(np.median(b))
                cut = 0.5 * (lo + hi)
            else:
                pass
            if len(a) and len(b):
                ndit, ndah = math.exp(lo), math.exp(hi)
                if 2.0 <= ndah / ndit <= 4.5:
                    dit, dah = ndit, ndah
        else:                                          # un seul groupe : du côté le plus proche
            if abs(math.log(d / self.dit)) < abs(math.log(d / self.dah)):
                dit, dah = d, 3 * d
            else:
                dit, dah = d / 3, d
        # changement limité à chaque élément (15 %)
        lim = lambda new, old: old * min(1.15, max(1 / 1.15, new / old))
        self.dit = 0.6 * self.dit + 0.4 * lim(dit, self.dit)
        self.dah = 0.6 * self.dah + 0.4 * lim(dah, self.dah)
        self._clamp()

    def _clamp(self):
        self.dit = min(0.24, max(0.02, self.dit))
        self.dah = min(0.72, max(0.06, self.dah))

    def _space_end(self, d):
        """Apprend les espaces : entre éléments (~1), entre lettres (~3), entre mots (~7 points)."""
        u = self.dot
        if d < 0.3 * u or d > 30 * u:
            return
        self._gaps.append(d / u)
        if d < 2.0 * u:                                    # espace entre deux éléments
            self._egap = d if not self._egap else 0.8 * self._egap + 0.2 * d
        g = np.array(self._gaps)
        if len(g) < 10:
            return
        el = g[g < 2.0]
        e = float(np.median(el)) if len(el) >= 3 else 1.0
        big = np.log(g[g >= 2.0])
        if len(big) < 4:
            return
        lo, hi = big.min(), big.max()
        for _ in range(10):                       # deux groupes : entre lettres / entre mots
            cut = 0.5 * (lo + hi)
            a, b = big[big < cut], big[big >= cut]
            if not len(a) or not len(b):
                break
            lo, hi = float(np.median(a)), float(np.median(b))
        ch, w = math.exp(lo), math.exp(hi)
        if hi - lo > math.log(1.7) and len(a) >= 2 and len(b) >= 2:
            self._char_thr = min(5.0, max(1.7, math.sqrt(e * ch)))
            self._word_thr = min(18.0, max(self._char_thr * 1.6, 4.5, math.sqrt(ch * w)))
        else:                                      # un seul groupe : ce sont les espaces entre lettres
            c = math.exp(float(np.median(big)))
            self._char_thr = min(5.0, max(1.7, math.sqrt(e * c)))
            self._word_thr = max(5.0, 2.0 * c if c > 4 else self._char_thr * 2.2)

    def _check_gap(self):
        out = ""
        if not self._char_done and self._dur > self._char_thr * self.dot:
            if self._sym:
                out += MORSE.get(self._sym, "*")
            self._sym = ""
            self._char_done = True
        if self._char_done and not self._word_done and self._dur > self._word_thr * self.dot:
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
