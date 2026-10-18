"""Balises NCDXF / IARU (International Beacon Project) : 18 balises, 5 bandes, cycle de 3 minutes.

Chaque balise émet 10 s sur 14,100, puis 18,110, 21,150, 24,930 et 28,200 MHz : sur une bande,
on entend donc une balise différente toutes les 10 secondes. Elle émet son indicatif en CW puis
quatre traits de 1 s à 100 W, 10 W, 1 W et 0,1 W : écouter jusqu'où on l'entend renseigne sur la
propagation vers sa région.
"""
import datetime
import time

FREQS = [("20m", 14_100_000), ("17m", 18_110_000), ("15m", 21_150_000), ("12m", 24_930_000), ("10m", 28_200_000)]

# indicatif, lieu, locator
BEACONS = [
    ("4U1UN", "New York (ONU)", "FN30as"), ("VE8AT", "Nunavut, Canada", "EQ79ax"),
    ("W6WX", "Californie, États-Unis", "CM97bd"), ("KH6RS", "Hawaï", "BL10ts"),
    ("ZL6B", "Nouvelle-Zélande", "RE78tw"), ("VK6RBP", "Australie-Occidentale", "OF87av"),
    ("JA2IGY", "Japon", "PM84jk"), ("RR9O", "Novossibirsk, Russie", "NO14kx"),
    ("VR2B", "Hong Kong", "OL72bg"), ("4S7B", "Sri Lanka", "MJ96wv"),
    ("ZS6DN", "Afrique du Sud", "KG44dc"), ("5Z4B", "Kenya", "KI88ks"),
    ("4X6TU", "Israël", "KM72jb"), ("OH2B", "Finlande", "KP20eh"),
    ("CS3B", "Madère", "IM12or"), ("LU4AA", "Argentine", "GF05tj"),
    ("OA4B", "Pérou", "FH17mw"), ("YV5B", "Venezuela", "FJ69cc"),
]
SLOT = 10
CYCLE = SLOT * len(BEACONS)          # 180 s


def _t(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.timestamp() if hasattr(now, "timestamp") else float(now)


def on_air(now=None):
    """[(bande, fréquence, indice de la balise, secondes restantes dans le créneau)] pour les 5 bandes."""
    t = _t(now)
    sec = t % CYCLE
    slot = int(sec // SLOT)
    left = SLOT - (sec % SLOT)
    return [(band, hz, (slot - k) % len(BEACONS), left) for k, (band, hz) in enumerate(FREQS)]


def where_is(idx, now=None):
    """Bande sur laquelle la balise n° idx émet maintenant (ou None si elle ne parle pas)."""
    for band, hz, b, left in on_air(now):
        if b == idx:
            return band, hz, left
    return None


def next_on(idx, band_k, now=None):
    """Secondes avant que la balise idx émette sur la bande n° band_k."""
    t = _t(now)
    slot_needed = (idx + band_k) % len(BEACONS)
    start = slot_needed * SLOT
    sec = t % CYCLE
    return (start - sec) % CYCLE


def monotonic_ok():
    return time.time() > 1_600_000_000            # horloge du PC plausible
