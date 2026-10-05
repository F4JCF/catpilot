from .ft991a import FT991A
from .sim import SimDriver

DRIVERS = {
    "Yaesu FT-991A": FT991A,
    "Simulateur (sans poste)": SimDriver,
}
