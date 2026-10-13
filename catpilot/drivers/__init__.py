from .ft891 import FT891
from .ft991a import FT991A
from .ic705 import IC705
from .models import FT710, FTDX10, IC7300, IC9700
from .sim import SimDriver

DRIVERS = {
    "Yaesu FT-991A": FT991A,
    "Yaesu FT-891": FT891,
    "Yaesu FT-710": FT710,
    "Yaesu FTDX10": FTDX10,
    "Icom IC-705": IC705,
    "Icom IC-7300": IC7300,
    "Icom IC-9700": IC9700,
    "Simulateur (sans poste)": SimDriver,
}


def _remote():
    from ..remote import RemoteDriver
    return RemoteDriver


DRIVERS = {**DRIVERS, "Poste distant (CAT Pilot)": _remote()
}
