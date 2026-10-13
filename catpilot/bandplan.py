"""Plan de bandes IARU Région 1 (simplifié, à titre indicatif) et barre d'affichage.

Les segments reprennent les grandes lignes du plan IARU R1 ; les limites de
bandes sont celles du tableau BANDS du logiciel. Ils ne remplacent ni le plan
de bandes officiel à jour ni la réglementation de votre licence.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

KINDS = {   # nature : (libellé, couleur)
    "CW":  ("CW", "#2f6fd6"),
    "NUM": ("Numérique", "#9b4fd0"),
    "BLU": ("BLU et tous modes", "#2e9e48"),
    "ALL": ("Tous modes", "#5b8c3a"),
    "BAL": ("Balises (ne pas émettre)", "#d4342a"),
    "FM":  ("FM simplex", "#c98a12"),
    "RLY": ("Relais FM", "#d0632a"),
    "SAT": ("Satellites (ne pas émettre en terrestre)", "#1aa3a3"),
    "GRD": ("Garde", "#555555"),
}

# (début Hz, fin Hz, nature)
SEGMENTS = [
    (135_700, 137_800, "CW"),
    (472_000, 475_000, "CW"), (475_000, 479_000, "NUM"),
    (1_810_000, 1_838_000, "CW"), (1_838_000, 1_843_000, "NUM"), (1_843_000, 2_000_000, "BLU"),
    (3_500_000, 3_570_000, "CW"), (3_570_000, 3_600_000, "NUM"), (3_600_000, 3_800_000, "BLU"),
    (5_351_500, 5_354_000, "CW"), (5_354_000, 5_366_000, "BLU"), (5_366_000, 5_366_500, "NUM"),
    (7_000_000, 7_040_000, "CW"), (7_040_000, 7_060_000, "NUM"), (7_060_000, 7_200_000, "BLU"),
    (10_100_000, 10_130_000, "CW"), (10_130_000, 10_150_000, "NUM"),
    (14_000_000, 14_070_000, "CW"), (14_070_000, 14_099_000, "NUM"), (14_099_000, 14_101_000, "BAL"),
    (14_101_000, 14_112_000, "NUM"), (14_112_000, 14_350_000, "BLU"),
    (18_068_000, 18_095_000, "CW"), (18_095_000, 18_109_000, "NUM"), (18_109_000, 18_111_000, "BAL"),
    (18_111_000, 18_168_000, "BLU"),
    (21_000_000, 21_070_000, "CW"), (21_070_000, 21_149_000, "NUM"), (21_149_000, 21_151_000, "BAL"),
    (21_151_000, 21_450_000, "BLU"),
    (24_890_000, 24_915_000, "CW"), (24_915_000, 24_929_000, "NUM"), (24_929_000, 24_931_000, "BAL"),
    (24_931_000, 24_990_000, "BLU"),
    (28_000_000, 28_070_000, "CW"), (28_070_000, 28_190_000, "NUM"), (28_190_000, 28_225_000, "BAL"),
    (28_225_000, 29_200_000, "BLU"), (29_200_000, 29_300_000, "NUM"), (29_300_000, 29_510_000, "SAT"),
    (29_510_000, 29_520_000, "GRD"), (29_520_000, 29_620_000, "FM"), (29_620_000, 29_700_000, "RLY"),
    (50_000_000, 50_100_000, "CW"), (50_100_000, 50_500_000, "BLU"), (50_500_000, 52_000_000, "ALL"),
    (144_000_000, 144_110_000, "CW"), (144_110_000, 144_150_000, "NUM"), (144_150_000, 144_400_000, "BLU"),
    (144_400_000, 144_490_000, "BAL"), (144_490_000, 144_500_000, "GRD"), (144_500_000, 144_794_000, "ALL"),
    (144_794_000, 144_990_000, "NUM"), (144_990_000, 145_194_000, "RLY"), (145_194_000, 145_594_000, "FM"),
    (145_594_000, 145_794_000, "RLY"), (145_794_000, 145_806_000, "ALL"), (145_806_000, 146_000_000, "SAT"),
    (430_000_000, 430_400_000, "RLY"), (430_400_000, 431_600_000, "NUM"), (431_600_000, 432_000_000, "RLY"),
    (432_000_000, 432_100_000, "CW"), (432_100_000, 432_400_000, "BLU"), (432_400_000, 432_490_000, "BAL"),
    (432_490_000, 432_500_000, "GRD"), (432_500_000, 433_000_000, "ALL"), (433_000_000, 433_400_000, "RLY"),
    (433_400_000, 433_600_000, "FM"), (433_600_000, 435_000_000, "ALL"), (435_000_000, 438_000_000, "SAT"),
    (438_000_000, 440_000_000, "ALL"),
    (1_240_000_000, 1_260_000_000, "ALL"), (1_260_000_000, 1_270_000_000, "SAT"),
    (1_270_000_000, 1_296_000_000, "ALL"), (1_296_000_000, 1_296_150_000, "CW"),
    (1_296_150_000, 1_296_800_000, "BLU"), (1_296_800_000, 1_296_994_000, "BAL"),
    (1_296_994_000, 1_300_000_000, "ALL"),
]


def segment_at(hz):
    for lo, hi, kind in SEGMENTS:
        if lo <= hz < hi:
            return lo, hi, kind
    return None


class BandPlanBar(QWidget):
    """Bande colorée de la bande en cours, avec un repère sur la fréquence."""

    def __init__(self, bands):
        super().__init__()
        self.bands = bands                # [(nom, début, fin, défaut)]
        self.freq = 0
        self.tx = False
        self.dim = False                  # mode nuit : couleurs assombries
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("Plan de bandes IARU Région 1, à titre indicatif")

    def set_freq(self, hz, tx=False):
        if hz != self.freq or tx != self.tx:
            self.freq, self.tx = hz, tx
            self.update()

    def band(self):
        return next(((n, lo, hi) for n, lo, hi, _d in self.bands if lo <= self.freq <= hi), None)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bar = QRectF(0, 0, w, 10)
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        b = self.band()
        if not b:
            p.fillRect(bar, QColor("#3a0b08"))
            p.setPen(QColor("#ff5a40"))
            p.drawText(QRectF(0, 11, w, h - 11), Qt.AlignCenter, "Hors des bandes amateurs")
            return
        name, lo, hi = b
        span = hi - lo
        for slo, shi, kind in SEGMENTS:
            if shi <= lo or slo >= hi:
                continue
            x0 = (max(slo, lo) - lo) / span * w
            x1 = (min(shi, hi) - lo) / span * w
            col = QColor(KINDS[kind][1])
            p.fillRect(QRectF(x0, 0, max(1.0, x1 - x0), 10), col.darker(260) if self.dim else col)
        x = (self.freq - lo) / span * w
        p.setPen(QPen(QColor("#ff2a1a" if self.tx else "#ffffff"), 2))
        p.drawLine(int(x), 0, int(x), 13)
        seg = segment_at(self.freq)
        if seg:
            slo, shi, kind = seg
            txt = (f"{name} — {KINDS[kind][0]}  ({slo / 1e6:.3f} – {shi / 1e6:.3f} MHz)"
                   .replace(".", ","))
            color = KINDS[kind][1]
        else:
            txt, color = f"{name} — hors segment du plan", "#aaaaaa"
        p.setPen(QColor(color).darker(170) if self.dim else QColor(color).lighter(140))
        p.drawText(QRectF(0, 12, w, h - 12), Qt.AlignCenter, txt)
