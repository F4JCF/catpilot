"""Séquence automatique d'un QSO FT8 / FT4 (même déroulé que WSJT-X).

Répondre à un CQ :      Tx1 « DX MOI LOC »  -> Tx3 « DX MOI R-xx »  -> Tx5 « DX MOI 73 »
Appeler CQ :            Tx6 « CQ MOI LOC »  -> Tx2 « DX MOI -xx »   -> Tx4 « DX MOI RR73 »
Le QSO est noté dans le carnet dès que les deux reports sont échangés et confirmés.
"""
from . import ftx


class FtxQso:
    MAX_REPEAT = 6                 # sans réponse, on arrête après ce nombre d'appels identiques

    def __init__(self, mycall="", mygrid=""):
        self.mycall, self.mygrid = mycall.upper(), mygrid.upper()[:4]
        self.auto_cq = False           # après un QSO lancé par notre CQ, relancer CQ
        self.reset()

    def reset(self):
        self.dx, self.dx_grid = "", ""
        self.sent_rpt, self.rcvd_rpt = "", ""
        self.step = 0                  # numéro du message à émettre (1 à 6), 0 = rien
        self.repeat = 0
        self.last_tx = ""
        self.logged = False
        self.cq_mode = False
        self.t_start = None
        self.done_reason = ""

    # --- messages ---------------------------------------------------------------------------
    def msg(self, n):
        dx, me, g = self.dx, self.mycall, self.mygrid
        return {1: f"{dx} {me} {g}".strip(), 2: f"{dx} {me} {self.sent_rpt}", 3: f"{dx} {me} R{self.sent_rpt}",
                4: f"{dx} {me} RR73", 5: f"{dx} {me} 73", 6: f"CQ {me} {g}".strip()}[n]

    def next_message(self):
        if not self.step:
            return ""
        return self.msg(self.step)

    # --- commandes --------------------------------------------------------------------------
    def call_cq(self):
        self.reset()
        self.cq_mode = True
        self.step = 6

    def answer(self, dec, snr):
        """Répond à un décodage (double-clic) : CQ ou message qui nous est adressé."""
        p = ftx.parse(dec["text"])
        if not p["de"] or p["de"] == self.mycall:
            return False
        if p["to"] == self.mycall:
            self.reset()
            self.dx, self.dx_grid = p["de"], p["grid"]
            self.sent_rpt = ftx.fmt_report(snr)
            self._handle(p, snr)
            return True
        self.reset()
        self.dx, self.dx_grid = p["de"], p["grid"]
        self.sent_rpt = ftx.fmt_report(snr)
        self.step = 1
        return True

    def transmitted(self, text):
        """Appelé après chaque émission."""
        self.repeat = self.repeat + 1 if text == self.last_tx else 1
        self.last_tx = text
        if self.step in (4, 5) and self.logged:
            # RR73 ou 73 envoyé : le QSO est fini (si le correspondant renvoie son R-report,
            # on_decodes repasse en RR73)
            self.done_reason = "QSO terminé"
            self.step = 6 if (self.cq_mode and self.auto_cq) else 0
            if self.step == 6:
                self.dx = self.dx_grid = self.sent_rpt = self.rcvd_rpt = ""
                self.logged = False
            return
        if self.repeat >= self.MAX_REPEAT and self.step in (1, 2, 3, 4):
            self.done_reason = f"pas de réponse de {self.dx}"
            self.step = 0

    def on_decodes(self, decodes):
        """Examine les décodages du créneau ; renvoie True si un QSO est à noter."""
        log = False
        for d in decodes:
            p = ftx.parse(d["text"])
            if p["to"] != self.mycall:
                continue
            if self.cq_mode and self.step == 6 and not self.dx and (p["grid"] or p["report"]):
                # quelqu'un répond à notre CQ
                self.dx, self.dx_grid = p["de"], p["grid"]
                self.sent_rpt = ftx.fmt_report(d.get("snr", -10))
            if p["de"] != self.dx:
                continue
            log = self._handle(p, d.get("snr", -10)) or log
        return log

    def _handle(self, p, snr):
        """Fait avancer le QSO selon le message reçu de dx. Renvoie True s'il faut le noter."""
        if not self.sent_rpt:
            self.sent_rpt = ftx.fmt_report(snr)
        if p["grid"] and not p["report"]:
            self.dx_grid = self.dx_grid or p["grid"]
            if self.step in (6, 1, 0) or self.cq_mode:
                self.step = 2                         # il répond à notre CQ : on passe le report
        elif p["report"] and not p["report"].startswith("R"):
            self.rcvd_rpt = p["report"]
            self.step = 3                             # on confirme avec R+report
        elif p["report"].startswith("R"):
            self.rcvd_rpt = p["report"][1:]
            self.step = 4                             # RR73
            return self._log()
        elif p["rr73"] in ("RRR", "RR73"):
            self.step = 5                             # 73 final
            return self._log()
        elif p["rr73"] == "73":
            if self.step == 4:
                self.step = 0
                self.done_reason = "QSO terminé"
            return self._log()
        return False

    def _log(self):
        if self.logged or not self.dx:
            return False
        self.logged = True
        return True
