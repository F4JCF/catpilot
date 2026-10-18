"""FT8 et FT4 : décodage, émission (GFSK) et analyse des messages, autour de ft8_lib (MIT).

La bibliothèque C (ft8lib.dll sous Windows) est compilée par GitHub Actions et livrée
avec l'exécutable. Les créneaux sont calés sur l'heure UTC (15 s en FT8, 7,5 s en FT4) :
l'horloge du PC doit être juste à moins d'une seconde près.
"""
import ctypes
import math
import os
import re
import sys

import numpy as np

RATE = 12000
MODES = {
    "FT8": {"slot": 15.0, "sym": 0.160, "nn": 79, "bt": 2.0, "spacing": 6.25, "ft4": 0, "tones": 8},
    "FT4": {"slot": 7.5, "sym": 0.048, "nn": 105, "bt": 1.0, "spacing": 20.833, "ft4": 1, "tones": 4},
}
# fréquences habituelles (kHz, cadran en USB)
FREQS = {
    "FT8": {"160m": 1840, "80m": 3573, "60m": 5357, "40m": 7074, "30m": 10136, "20m": 14074, "17m": 18100,
            "15m": 21074, "12m": 24915, "10m": 28074, "6m": 50313, "4m": 70154, "2m": 144174},
    "FT4": {"80m": 3575.5, "40m": 7047.5, "30m": 10140, "20m": 14080, "17m": 18104, "15m": 21140,
            "12m": 24919, "10m": 28180, "6m": 50318, "2m": 144170},
}


class _Result(ctypes.Structure):
    _fields_ = [("text", ctypes.c_char * 40), ("freq", ctypes.c_float), ("dt", ctypes.c_float),
                ("score", ctypes.c_float), ("ldpc_errors", ctypes.c_int)]


_lib = None
LIB_ERROR = ""


def lib():
    global _lib, LIB_ERROR
    if _lib is not None:
        return _lib
    here = os.path.dirname(os.path.abspath(__file__))
    bases = [getattr(sys, "_MEIPASS", ""), here]
    names = ["ft8lib.dll"] if os.name == "nt" else ["libft8lib.so"]
    for b in bases:
        for n in names:
            p = os.path.join(b, n) if b else ""
            if p and os.path.exists(p):
                try:
                    L = ctypes.CDLL(p)
                    L.ft8w_decode.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              ctypes.c_float, ctypes.c_float, ctypes.POINTER(_Result), ctypes.c_int]
                    L.ft8w_decode.restype = ctypes.c_int
                    L.ft8w_encode.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
                    L.ft8w_encode.restype = ctypes.c_int
                    L.ft8w_hash_add.argtypes = [ctypes.c_char_p]
                    _lib = L
                    return L
                except OSError as e:
                    LIB_ERROR = str(e)
    LIB_ERROR = LIB_ERROR or "bibliothèque ft8lib introuvable"
    return None


def resample(x, sr, to=RATE):
    """Rééchantillonnage (filtre passe-bas par FFT), suffisant pour un créneau de 15 s."""
    x = np.asarray(x, np.float32)
    if sr == to:
        return x
    n = int(round(len(x) * to / sr))
    X = np.fft.rfft(x)
    keep = n // 2 + 1
    if keep < len(X):
        X = X[:keep]
    else:
        X = np.concatenate([X, np.zeros(keep - len(X), X.dtype)])
    return (np.fft.irfft(X, n) * (n / len(x))).astype(np.float32)


def tones(message, mode="FT8"):
    L = lib()
    if not L:
        raise RuntimeError(LIB_ERROR)
    m = MODES[mode]
    buf = (ctypes.c_uint8 * m["nn"])()
    n = L.ft8w_encode(message.upper().encode("ascii", "ignore"), m["ft4"], buf)
    if n < 0:
        raise ValueError(f"message impossible à coder en {mode} : « {message} »")
    return np.array(buf[:n], np.int32)


def hash_add(call):
    L = lib()
    if L and call:
        L.ft8w_hash_add(call.upper().encode("ascii", "ignore"))


def synth(tone_seq, f0, sr, mode="FT8", amp=0.5):
    """Signal GFSK (même méthode que WSJT-X), montée et descente douces."""
    from math import erf
    m = MODES[mode]
    nsps = int(round(sr * m["sym"]))
    nsym = len(tone_seq)
    k = math.pi * math.sqrt(2 / math.log(2))
    t = np.arange(3 * nsps) / nsps - 1.5
    verf = np.vectorize(erf)
    pulse = (verf(k * m["bt"] * (t + 0.5)) - verf(k * m["bt"] * (t - 0.5))) / 2
    dphi_peak = 2 * math.pi / nsps                    # indice de modulation 1
    n_wave = nsym * nsps
    dphi = np.full(n_wave + 2 * nsps, 2 * math.pi * f0 / sr)
    for i, s in enumerate(tone_seq):
        dphi[i * nsps:i * nsps + 3 * nsps] += dphi_peak * s * pulse
    dphi[:2 * nsps] += dphi_peak * pulse[nsps:] * tone_seq[0]
    dphi[nsym * nsps:nsym * nsps + 2 * nsps] += dphi_peak * pulse[:2 * nsps] * tone_seq[-1]
    phi = np.concatenate([[0.0], np.cumsum(dphi[nsps:nsps + n_wave - 1])])
    sig = np.sin(phi)
    nr = nsps // 8
    env = (1 - np.cos(2 * math.pi * np.arange(nr) / (2 * nr))) / 2
    sig[:nr] *= env
    sig[-nr:] *= env[::-1]
    return (amp * sig).astype(np.float32)


def decode(x, sr, mode="FT8", fmin=200.0, fmax=3000.0):
    """Décode un créneau. Renvoie [{"text", "freq", "dt", "snr"}], trié par fréquence."""
    L = lib()
    if not L:
        raise RuntimeError(LIB_ERROR)
    y = resample(x, sr)
    m = MODES[mode]
    n = min(len(y), int(m["slot"] * RATE))
    y = np.ascontiguousarray(y[:n], np.float32)
    out = (_Result * 100)()
    k = L.ft8w_decode(y.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(y), RATE, m["ft4"],
                      fmin, fmax, out, 100)
    res = []
    for r in out[:k]:
        text = r.text.decode("ascii", "replace").strip()
        d = {"text": text, "freq": float(r.freq), "dt": float(r.dt) - 0.5, "score": float(r.score)}
        try:
            d["snr"] = estimate_snr(y, d, mode)
        except Exception:
            d["snr"] = max(-24, min(20, int(r.score * 0.5) - 20))
        res.append(d)
    res.sort(key=lambda d: d["freq"])
    return res


def estimate_snr(y, d, mode):
    """Rapport signal / bruit dans 2 500 Hz (comme WSJT-X), à partir des tonalités du message.
    Cherche aussi le calage exact du signal (pour un DT juste)."""
    m = MODES[mode]
    seq = tones(d["text"], mode)
    nsps = int(round(RATE * m["sym"]))
    fbin = RATE / nsps
    win = np.hanning(nsps)
    t_guess = d["dt"] + 0.5
    best = None
    step = nsps // 8
    for off in range(-nsps, nsps + 1, step):
        t0 = int(round(t_guess * RATE)) + off
        idx = t0 + np.arange(len(seq)) * nsps
        ok = (idx >= 0) & (idx + nsps <= len(y))
        if ok.sum() < len(seq) * 0.7:
            continue
        frames = np.stack([y[a:a + nsps] * win for a in idx[ok]])
        spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
        b = np.round((d["freq"] + seq[ok] * m["spacing"]) / fbin).astype(int)
        b = np.clip(b, 0, spec.shape[1] - 1)
        ps = float(spec[np.arange(len(b)), b].mean())
        if best is None or ps > best[0]:
            best = (ps, t0, spec)
    if best is None:
        raise ValueError
    ps, t0, spec = best
    lo = int(round((d["freq"] - 80) / fbin))
    hi = int(round((d["freq"] + m["tones"] * m["spacing"] + 80) / fbin))
    band = np.concatenate([spec[:, max(0, lo - 60):max(0, lo)], spec[:, hi:hi + 60]], axis=1)
    pn = float(np.median(band)) / 0.693           # médiane -> moyenne (loi exponentielle)
    d["dt"] = t0 / RATE - 0.5
    # fenêtre de Hann : le bruit est compté sur 1,5 case (largeur équivalente de bruit)
    snr = 10 * math.log10(max(ps - pn, 1e-12) / (pn / 1.5)) - 10 * math.log10(2500 / fbin)
    return int(round(max(-30, min(30, snr))))


# --- lecture des messages -------------------------------------------------------------------
GRID = re.compile(r"^[A-R]{2}\d{2}$")
REPORT = re.compile(r"^R?[+-]\d{2}$")
CALL = re.compile(r"^(<[^>]+>|[A-Z0-9/]*\d[A-Z0-9/]*)$")


def parse(text):
    """Découpe un message : {"to", "de", "grid", "report", "rr73", "cq", "cq_tag"}."""
    w = text.upper().split()
    d = {"to": "", "de": "", "grid": "", "report": "", "rr73": "", "cq": False, "cq_tag": ""}
    if not w:
        return d
    if w[0] == "CQ":
        d["cq"] = True
        rest = w[1:]
        if len(rest) >= 2 and not CALL.match(rest[0]) or (len(rest) == 3):
            d["cq_tag"], rest = rest[0], rest[1:]
        if rest:
            d["de"] = rest[0].strip("<>")
        if len(rest) > 1 and GRID.match(rest[1]):
            d["grid"] = rest[1]
        return d
    if len(w) >= 2:
        d["to"], d["de"] = w[0].strip("<>"), w[1].strip("<>")
    if len(w) >= 3:
        x = w[2]
        if GRID.match(x) and x != "RR73":
            d["grid"] = x
        elif REPORT.match(x):
            d["report"] = x
        elif x in ("RRR", "RR73", "73"):
            d["rr73"] = x
        if len(w) >= 4 and w[2] == "R" and REPORT.match("R" + w[3]):
            d["report"] = "R" + w[3]
    return d


def fmt_report(snr):
    snr = int(max(-30, min(49, snr)))
    return f"{snr:+03d}"
