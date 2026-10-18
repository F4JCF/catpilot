"""Autres postes, dérivés des pilotes FT-991A (Yaesu CAT) et IC-705 (Icom CI-V).

Ces postes partagent l'essentiel des commandes ; les différences sont
décrites ici. Les réglages qu'un poste refuse sont grisés automatiquement.
Testés uniquement sur poste simulé : merci de signaler tout écart.
"""
from .base import RigError
from .ft991a import FT991A, MODE_TO_CODE
from .ic705 import CODE_TO_ICOM, ICOM_MODE, ICOM_TO_CODE, IC705, bcd, unbcd


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
    """IC-7300 : 99 mémoires sans groupes, blocs courts (pas de D-STAR), noms de 10 caractères
    (16 sur l'IC-7300 MK2 : la disposition est reconnue d'après un canal lu sur le poste)."""
    name = "Icom IC-7300"
    civ_addr = 0x94
    max_power = 100
    max_freq = 74_800_000
    has_gps = False
    mem_groups = None
    mem_range = (1, 99)
    mem_tag_len = 10
    menu_last = 280
    # Jamais réécrits : réglages CI-V (la liaison en dépend), date, heure et décalage UTC.
    menu_skip = {f"{n:04d}" for n in range(66, 79)} | {"0094", "0095", "0096"}
    SHORT = 14                       # fréq(5) mode filtre data+tonalité tonalité-relais(3) tsql(3)

    def _mem_payload(self, ch):
        return [*bcd(ch, 2, little=False)]

    def _layout(self, d):
        """(nombre de blocs, longueur du nom) d'après la longueur d'un canal lu."""
        rest = len(d) - 2 - 1
        for nb, tag in ((2, 10), (1, 16), (1, 10), (2, 16)):
            if nb * self.SHORT + tag == rest:
                return nb, tag
        return None

    def _parse_mem(self, ch, d):
        lay = self._layout(d)
        if not lay:
            return None
        nb, tag = lay
        self.mem_tag_len = tag
        blk = d[3:3 + self.SHORT]
        mode_b, filt, dt = blk[5], blk[6], blk[7]
        name = next((k for k, v in ICOM_MODE.items() if v == mode_b), "USB")
        data, tone = bool(dt >> 4), dt & 0x0F
        code = ICOM_TO_CODE.get((name, data, filt >= 2), ICOM_TO_CODE.get((name, data, False), "2"))
        return {"ch": ch, "freq": unbcd(blk[0:5]), "code": code, "mode": name,
                "tag": d[-tag:].decode("ascii", "replace").strip(), "shift": 0,
                "ctcss": {0: 0, 1: 2, 2: 1}.get(tone, 0), "clar": 0, "raw": d.hex()}

    def _build_mem(self, m, template_hex):
        d = bytearray(bytes.fromhex(template_hex))
        lay = self._layout(d)
        if not lay:
            raise RigError("disposition de mémoire inconnue")
        nb, tag = lay
        d[0:2] = bytes(self._mem_payload(int(m["ch"])))
        d[2] = 0x00                                   # pas de split, pas de sélection
        name, data, narrow = CODE_TO_ICOM.get(m.get("code", "2"), ("USB", False, False))
        tone = {0: 0, 1: 2, 2: 1, 3: 2}.get(int(m.get("ctcss", 0)), 0)
        for b in range(nb):
            o = 3 + b * self.SHORT
            d[o:o + 5] = bcd(int(m["freq"]), 5)
            d[o + 5] = ICOM_MODE[name]
            d[o + 6] = 2 if narrow else 1
            d[o + 7] = ((1 if data else 0) << 4) | tone
        d[-tag:] = m.get("tag", "")[:tag].ljust(tag).encode("ascii", "replace")
        return bytes(d)

    def write_memories(self, mems, template, progress=None):
        if template and not self._layout(bytes.fromhex(template)):
            raise RigError("disposition de mémoire inconnue : lisez d'abord les mémoires")
        return super().write_memories(mems, template, progress)


class IC9700(IC705):
    """IC-9700 : mêmes blocs que l'IC-705 (D-STAR), mais rangés par bande (1 = 144, 2 = 430,
    3 = 1 200 MHz) au lieu de groupes ; 99 canaux par bande."""
    name = "Icom IC-9700"
    civ_addr = 0xA2
    min_freq = 144_000_000
    max_freq = 1_300_000_000
    max_power = 100                  # 100 W en 2 m (75 W en 70 cm, 10 W en 23 cm)
    has_gps = True
    mem_groups = 3
    mem_group_range = (1, 3)
    mem_group_hint = "Bande : 1 = 144 MHz, 2 = 430 MHz, 3 = 1 200 MHz"
    mem_range = (1, 99)
    mem_tag_len = 16
    menu_last = 342
    menu_skip = {f"{n:04d}" for n in range(120, 135)} | {"0179", "0180", "0184"}

    def __init__(self, *a):
        super().__init__(*a)
        self.mem_group = 1

    def _mem_select(self, group):
        pass                         # la bande fait partie du numéro de canal

    def _mem_payload(self, ch):
        return [*bcd(max(1, min(3, self.mem_group)), 1, little=False), *bcd(ch, 2, little=False)]
