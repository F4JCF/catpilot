import math, datetime

BANDS = [("2190m", .1357, .1378), ("630m", .472, .479), ("160m", 1.8, 2.0), ("80m", 3.5, 4.0),
         ("60m", 5.06, 5.45), ("40m", 7.0, 7.3), ("30m", 10.1, 10.15), ("20m", 14.0, 14.35),
         ("17m", 18.068, 18.168), ("15m", 21.0, 21.45), ("12m", 24.89, 24.99), ("10m", 28.0, 29.7),
         ("6m", 50, 54), ("4m", 70, 71), ("2m", 144, 148), ("1.25m", 222, 225), ("70cm", 420, 450),
         ("23cm", 1240, 1300), ("13cm", 2300, 2450), ("3cm", 10000, 10500)]

MODES = {"CW": [], "SSB": ["USB", "LSB"], "AM": [], "FM": [], "RTTY": [], "PSK": ["PSK31", "PSK63"],
         "MFSK": ["FT4", "JS8", "Q65"], "FT8": [], "JT65": [], "JT9": [], "OLIVIA": [], "SSTV": [],
         "DIGITALVOICE": [], "DSTAR": [], "C4FM": [], "DMR": [], "HELL": [], "CONTESTI": [], "MSK144": []}

DEFAULT_RST = {"CW": "599", "RTTY": "599", "PSK": "599", "FT8": "-10", "MFSK": "-10", "JT65": "-15", "JT9": "-15"}


def band_of(mhz):
    try:
        f = float(mhz)
    except (TypeError, ValueError):
        return ""
    for b, lo, hi in BANDS:
        if lo <= f <= hi:
            return b
    return ""


def loc2ll(loc):
    loc = (loc or "").strip().upper()
    if len(loc) < 4 or not loc[:2].isalpha() or not loc[2:4].isdigit():
        return None
    lon = (ord(loc[0]) - 65) * 20 - 180 + int(loc[2]) * 2
    lat = (ord(loc[1]) - 65) * 10 - 90 + int(loc[3])
    if len(loc) >= 6 and loc[4:6].isalpha():
        lon += (ord(loc[4]) - 65) * 5 / 60 + 2.5 / 60
        lat += (ord(loc[5]) - 65) * 2.5 / 60 + 1.25 / 60
    else:
        lon += 1
        lat += .5
    return lat, lon


def ll2loc(lat, lon):
    lon += 180
    lat += 90
    s = chr(65 + int(lon / 20)) + chr(65 + int(lat / 10))
    s += str(int(lon % 20 / 2)) + str(int(lat % 10))
    s += chr(97 + int(lon % 2 * 12)) + chr(97 + int(lat % 1 * 24))
    return s.upper()[:4] + s[4:]


def dist_bearing(a, b):
    if not a or not b:
        return None, None
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * 6371 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return round(d), round((math.degrees(math.atan2(y, x)) + 360) % 360)


def sun_times(lat, lon, date=None):
    date = date or datetime.datetime.now(datetime.timezone.utc).date()
    n = date.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
    c = (math.cos(math.radians(90.833)) / (math.cos(math.radians(lat)) * math.cos(decl)) - math.tan(math.radians(lat)) * math.tan(decl))
    if abs(c) > 1:
        return None, None
    ha = math.degrees(math.acos(c))
    rise = 720 - 4 * (lon + ha) - eqt
    sset = 720 - 4 * (lon - ha) - eqt
    f = lambda m: "%02d:%02d" % ((m // 60) % 24, m % 60)
    return f(rise), f(sset)
