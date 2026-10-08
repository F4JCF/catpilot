from .ft891 import FT891
from .ft991a import FT991A
from .ic705 import IC705
from .sim import SimDriver

DRIVERS = {
    "Yaesu FT-991A": FT991A,
    "Yaesu FT-891": FT891,
    "Icom IC-705": IC705,
    "Simulateur (sans poste)": SimDriver,
}
