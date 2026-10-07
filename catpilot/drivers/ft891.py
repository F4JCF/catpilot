"""Pilote Yaesu FT-891.

Le CAT du FT-891 est presque celui du FT-991A. Différences principales :
pas de 2 m / 70 cm ni de C4FM, pas de codec audio USB (la chute d'eau demande
une interface son externe, type SCU-17), et des menus numérotés par groupe et
item (« 05-06 » = CAT RATE), d'où les identifiants à 4 chiffres pour EX.
Les réglages que le poste refuse sont grisés automatiquement.
"""
from .ft991a import FT991A, MODE_TO_CODE

MENU_GROUPS = range(1, 17)        # groupes 01 à 16
MENU_ITEMS = range(1, 31)


class FT891(FT991A):
    name = "Yaesu FT-891"
    modes = [m for m in MODE_TO_CODE if m != "C4FM"]
    default_baud = 38400
    default_stopbits = 1
    max_freq = 56_000_000
    has_c4fm = False
    has_usb_audio = False
    menu_skip = {"0506", "0507", "0508"}       # CAT RATE, CAT TOT, CAT RTS
    menu_stop_after = 0

    def menu_ids(self):
        return [f"{g:02d}{i:02d}" for g in MENU_GROUPS for i in MENU_ITEMS]

    def read_menus(self, progress=None):
        """Parcourt chaque groupe ; passe au suivant après 3 items absents (6 en début de groupe)."""
        menus = {}
        for g in MENU_GROUPS:
            if progress:
                progress(f"Lecture des menus du poste… groupe {g:02d}")
            misses, found = 0, False
            for i in MENU_ITEMS:
                mid = f"{g:02d}{i:02d}"
                try:
                    menus[mid] = self.read_menu(mid)
                    misses, found = 0, True
                except Exception:
                    misses += 1
                    if misses >= (3 if found else 6):
                        break
        return menus
