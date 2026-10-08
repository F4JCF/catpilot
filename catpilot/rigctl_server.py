"""Serveur TCP compatible avec le protocole rigctld de Hamlib.

WSJT-X, JTDX, Fldigi, Log4OM, N1MM, GridTracker... peuvent s'y connecter en
choisissant le poste « Hamlib NET rigctl » à l'adresse 127.0.0.1:4532.
Seul le sous-ensemble utile au trafic courant est implémenté.
"""
import socketserver
import threading

OK = "RPRT 0\n"
ERR_INVAL = "RPRT -1\n"
ERR_IO = "RPRT -6\n"
ERR_NAVAIL = "RPRT -11\n"

PASSBAND = {"CW": 500, "CWR": 500, "AM": 6000, "FM": 12000, "WFM": 200000,
            "PKTFM": 12000, "RTTY": 500, "RTTYR": 500}

ALIASES = {
    "\\get_freq": "f", "\\set_freq": "F", "\\get_mode": "m", "\\set_mode": "M",
    "\\get_ptt": "t", "\\set_ptt": "T", "\\get_vfo": "v", "\\set_vfo": "V",
    "\\get_split_vfo": "s", "\\set_split_vfo": "S", "\\get_split_freq": "i",
    "\\set_split_freq": "I", "\\get_split_mode": "x", "\\set_split_mode": "X",
    "\\get_level": "l", "\\set_level": "L", "\\get_info": "_", "\\quit": "q",
}

DUMP_STATE = (
    "0\n"            # version du protocole
    "2\n"            # modèle (NET rigctl)
    "1\n"            # région UIT
    "100000.000000 470000000.000000 0x1fff -1 -1 0x1 0x0\n"        # plage RX
    "0 0 0 0 0 0 0\n"
    "1800000.000000 440000000.000000 0x1fff 5000 100000 0x1 0x0\n"  # plage TX
    "0 0 0 0 0 0 0\n"
    "0x1fff 1\n"     # pas d'accord
    "0 0\n"
    "0x0c 2400\n"    # filtres : SSB
    "0x82 500\n"     # CW
    "0x21 12000\n"   # AM/FM
    "0 0\n"
    "0\n0\n0\n0\n"   # RIT, XIT, IF shift, annonces
    "0\n0\n"         # préamplis, atténuateurs
    "0x0\n0x0\n"     # fonctions get/set
    "0x40001000\n"   # niveaux lisibles : RFPOWER | STRENGTH
    "0x1000\n"       # niveaux réglables : RFPOWER
    "0x0\n0x0\n"     # paramètres get/set
)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        owner = self.server.owner
        owner._clients_delta(+1)
        self.ptt_on = False
        try:
            for raw in self.rfile:
                line = raw.decode("ascii", "ignore").strip()
                if not line:
                    continue
                resp = owner.process(line, self)
                if resp is None:
                    break
                self.wfile.write(resp.encode("ascii"))
        except OSError:
            pass
        finally:
            if self.ptt_on:              # client parti en pleine émission : on coupe
                owner.ctrl.set_ptt(False)
            owner._clients_delta(-1)


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class RigctlServer:
    def __init__(self, controller, port=4532, host="127.0.0.1"):
        self.ctrl = controller
        self.port = port
        self.host = host
        self.clients = 0
        self._lock = threading.Lock()
        self._srv = None

    def start(self):
        self._srv = _TCPServer((self.host, self.port), _Handler)
        self._srv.owner = self
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def _clients_delta(self, d):
        with self._lock:
            self.clients += d

    def process(self, line, handler):
        parts = line.split()
        cmd, args = parts[0], parts[1:]
        if cmd[0] in "+;|," and len(cmd) > 1:    # formats étendus : réponse standard
            cmd = cmd[1:]
        cmd = ALIASES.get(cmd, cmd)

        if cmd in ("q", "Q"):
            return None
        if cmd == "\\dump_state":
            return DUMP_STATE
        if cmd == "\\chk_vfo":
            return "0\n"
        if cmd == "\\get_powerstat":
            return "1\n"
        if cmd == "_":
            return "CAT Pilot\n"
        if not self.ctrl.connected:
            return ERR_IO

        st = self.ctrl.snapshot()
        drv = self.ctrl.driver
        try:
            if cmd == "f" or cmd == "i":
                return f"{st.freq}\n"
            if cmd == "F" or cmd == "I":
                self.ctrl.set_freq(int(float(args[-1])))
                return OK
            if cmd == "m" or cmd == "x":
                mode = "FM" if st.mode == "C4FM" else st.mode
                return f"{mode}\n{PASSBAND.get(mode, 2400)}\n"
            if cmd == "M":
                mode = args[0].upper()
                if mode == "?":
                    return " ".join(drv.modes) + "\n"
                if mode not in drv.modes:
                    return ERR_INVAL
                self.ctrl.set_mode(mode)
                return OK
            if cmd == "X":
                return OK
            if cmd == "t":
                return f"{int(st.ptt)}\n"
            if cmd == "T":
                on = args[-1] != "0"
                handler.ptt_on = on
                self.ctrl.set_ptt(on)
                return OK
            if cmd == "v":
                return "VFOA\n"
            if cmd in ("V", "S"):
                return OK
            if cmd == "s":
                return "0\nVFOA\n"
            if cmd == "l":
                name = args[0].upper() if args else "?"
                if name == "?":
                    return "STRENGTH RFPOWER\n"
                if name == "STRENGTH":
                    return f"{st.s_db}\n"
                if name == "RFPOWER":
                    return f"{st.p.get('pwr', 0) / getattr(drv, 'max_power', 100):.6f}\n"
                return ERR_NAVAIL
            if cmd == "L":
                if args and args[0].upper() == "RFPOWER":
                    self.ctrl.set_power(float(args[1]) * getattr(drv, "max_power", 100))
                    return OK
                return ERR_NAVAIL
        except (IndexError, ValueError):
            return ERR_INVAL
        return ERR_NAVAIL
