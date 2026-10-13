"""Autres postes, dérivés des pilotes FT-991A (Yaesu CAT) et IC-705 (Icom CI-V).

Ces postes partagent l'essentiel des commandes ; les différences sont
décrites ici. Les réglages qu'un poste refuse sont grisés automatiquement.
Testés uniquement sur poste simulé : merci de signaler tout écart.
"""
from .base import RigError
from .ft991a import FT991A, MODE_TO_CODE
from .ic705 import IC705


class _YaesuHF(FT991A):
    """FT-710 / FTDX10 : HF + 6 m, pas de C4FM, menus numérotés groupe-sous-groupe-item."""
    modes = [m for m in MODE_TO_CODE if m != "C4FM"]
    max_freq = 56_000_000
    has_c4fm = False
    menu_skip = set()

    def menu_ids(self):
        return [f"{g:02d}{sg:02d}{i:02d}" for g in range(1, 13) for sg in range(1, 13) for i in range(1, 41)]

    def read_menus(self, progress=None):
        """Parcours groupe > sous-groupe > item, en s'arrêtant aux zones vides."""
        menus, empty_groups = {}, 0
        for g in range(1, 13):
            if progress:
                progress(f"Lecture des menus du poste… groupe {g:02d}")
            found_g, empty_sub = False, 0
            for sg in range(1, 13):
                found_sg, misses = False, 0
                for i in range(1, 41):
                    mid = f"{g:02d}{sg:02d}{i:02d}"
                    try:
                        menus[mid] = self.read_menu(mid)
                        found_sg = found_g = True
                        misses = 0
                    except RigError:
                        misses += 1
                        if misses >= (3 if found_sg else 2):
                            break
                empty_sub = 0 if found_sg else empty_sub + 1
                if empty_sub >= 2:
                    break
            empty_groups = 0 if found_g else empty_groups + 1
            if empty_groups >= 2:
                break
        return menus


class FT710(_YaesuHF):
    name = "Yaesu FT-710"


class FTDX10(_YaesuHF):
    name = "Yaesu FTDX10"
    max_freq = 71_000_000


class IC7300(IC705):
    name = "Icom IC-7300"
    civ_addr = 0x94
    max_power = 100
    max_freq = 74_800_000
    has_gps = False
    mem_groups = None
    mem_range = (1, 99)
    mem_tag_len = 10
    menu_skip = set()

    def read_memories(self, progress=None):
        raise RigError("la lecture des mémoires de l'IC-7300 n'est pas encore prise en charge")

    def write_memories(self, mems, template, progress=None):
        raise RigError("l'écriture des mémoires de l'IC-7300 n'est pas encore prise en charge")

    def read_menus(self, progress=None):
        raise RigError("la sauvegarde des menus de l'IC-7300 n'est pas encore prise en charge")


class IC9700(IC7300):
    name = "Icom IC-9700"
    civ_addr = 0xA2
    min_freq = 144_000_000
    max_freq = 1_300_000_000
    max_power = 100                  # 100 W en 2 m (75 W en 70 cm, 10 W en 23 cm)
    has_gps = True

    def read_memories(self, progress=None):
        raise RigError("la lecture des mémoires de l'IC-9700 n'est pas encore prise en charge")

    def write_memories(self, mems, template, progress=None):
        raise RigError("l'écriture des mémoires de l'IC-9700 n'est pas encore prise en charge")

    def read_menus(self, progress=None):
        raise RigError("la sauvegarde des menus de l'IC-9700 n'est pas encore prise en charge")
