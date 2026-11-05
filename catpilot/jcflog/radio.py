import socket, struct, sys, threading, time, re, queue, xmlrpc.client
from PySide6.QtCore import QObject, Signal

try:
    import serial
except ImportError:
    serial = None

YAESU_MODES = {"1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM", "6": "RTTY", "7": "CW", "8": "PKTLSB",
               "9": "RTTY", "A": "PKTFM", "B": "FM", "C": "PKTUSB", "D": "AM", "E": "C4FM"}
KEN_MODES = {"1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM", "6": "RTTY", "7": "CW", "9": "RTTY"}
ICOM_MODES = {0: "LSB", 1: "USB", 2: "AM", 3: "CW", 4: "RTTY", 5: "FM", 7: "CW", 8: "RTTY"}
TO_YAESU = {"LSB": "1", "USB": "2", "CW": "3", "FM": "4", "AM": "5", "RTTY": "6", "PKTUSB": "C", "PKTLSB": "8"}
TO_KEN = {"LSB": "1", "USB": "2", "CW": "3", "FM": "4", "AM": "5", "RTTY": "6", "PKTUSB": "2", "PKTLSB": "1"}
RIG_TYPES = ["Hamlib rigctld (TCP)", "FLRig (XML-RPC)", "Yaesu CAT (FT-991A, FT-710, FTDX10/101)",
             "Kenwood / Elecraft CAT", "Icom CI-V"]


def to_adif_mode(m):
    m = (m or "").upper()
    if m in ("USB", "LSB"):
        return "SSB", m
    if m.startswith("PKT") or m.startswith("DATA"):
        return "SSB", "USB" if "U" in m[3:] else "LSB"
    if m in ("CWR", "CW-R"):
        return "CW", ""
    if m in ("RTTYR",):
        return "RTTY", ""
    return m, ""


class Rig(QObject):
    status = Signal(float, str, str)   # MHz, mode, power
    state = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.cfg, self.run, self.cmds = {}, False, queue.Queue()

    def start(self, cfg):
        self.stop()
        self.cfg, self.run = cfg, True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.run = False
        time.sleep(0.05)

    def set_freq(self, mhz):
        self.cmds.put(("F", mhz))

    def set_mode(self, mode):
        self.cmds.put(("M", mode))

    def ptt(self, on):
        self.cmds.put(("T", on))

    def _loop(self):
        t = self.cfg.get("rig_type", RIG_TYPES[0])
        try:
            if t.startswith("Hamlib"):
                io = _Rigctld(self.cfg.get("rig_host", "127.0.0.1"), int(self.cfg.get("rig_port", 4532)))
            elif t.startswith("FLRig"):
                io = _Flrig(self.cfg.get("rig_host", "127.0.0.1"), int(self.cfg.get("rig_port", 12345)))
            else:
                if not serial:
                    raise RuntimeError("pyserial absent")
                s = serial.Serial(self.cfg.get("rig_com", "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"), int(self.cfg.get("rig_baud", 38400)), timeout=0.5,
                                  stopbits=2 if t.startswith("Yaesu") and int(self.cfg.get("rig_baud", 38400)) <= 4800 else 1)
                io = _Icom(s, int(self.cfg.get("civ_addr", "94"), 16)) if t.startswith("Icom") else _Ascii(s, t.startswith("Yaesu"))
            self.state.emit(True, "Connecté")
        except Exception as e:
            self.state.emit(False, str(e))
            self.run = False
            return
        while self.run:
            try:
                while not self.cmds.empty():
                    c, v = self.cmds.get()
                    getattr(io, {"F": "setf", "M": "setm", "T": "ptt"}[c])(v)
                f, m, p = io.read()
                self.status.emit(f, m, p)
            except Exception as e:
                self.state.emit(False, str(e))
                break
            time.sleep(float(self.cfg.get("rig_poll", 0.5)))
        io.close()
        self.state.emit(False, "Déconnecté")


class _Rigctld:
    def __init__(self, h, p):
        self.s = socket.create_connection((h, p), 3)
        self.f = self.s.makefile("rw")

    def cmd(self, c, lines=1):
        self.f.write(c + "\n"); self.f.flush()
        return [self.f.readline().strip() for _ in range(lines)]

    def read(self):
        f = float(self.cmd("f")[0]) / 1e6
        m = self.cmd("m", 2)[0]
        try:
            p = str(round(float(self.cmd("l RFPOWER")[0]) * 100))
        except Exception:
            p = ""
        return f, m, p

    def setf(self, mhz): self.cmd("F %d" % round(mhz * 1e6))
    def setm(self, m): self.cmd("M %s 0" % m)
    def ptt(self, on): self.cmd("T %d" % int(on))
    def close(self): self.s.close()


class _Flrig:
    def __init__(self, h, p):
        self.x = xmlrpc.client.ServerProxy(f"http://{h}:{p}/RPC2")
        self.x.rig.get_xcvr()

    def read(self):
        try:
            p = str(self.x.rig.get_power())
        except Exception:
            p = ""
        return float(self.x.rig.get_vfo()) / 1e6, self.x.rig.get_mode(), p

    def setf(self, mhz): self.x.rig.set_frequency(float(round(mhz * 1e6)))
    def setm(self, m): self.x.rig.set_mode(m)
    def ptt(self, on): self.x.rig.set_ptt(int(on))
    def close(self): pass


class _Ascii:
    def __init__(self, s, yaesu):
        self.s, self.y = s, yaesu

    def q(self, c):
        self.s.reset_input_buffer()
        self.s.write(c.encode())
        return self.s.read_until(b";").decode(errors="ignore")

    def read(self):
        f = int(re.sub(r"\D", "", self.q("FA;")) or 0) / 1e6
        md = self.q("MD0;" if self.y else "MD;")
        code = md[3:4] if self.y else md[2:3]
        m = (YAESU_MODES if self.y else KEN_MODES).get(code, "")
        p = re.sub(r"\D", "", self.q("PC;"))
        return f, m, str(int(p)) if p else ""

    def setf(self, mhz):
        hz = round(mhz * 1e6)
        self.s.write((("FA%09d;" if self.y else "FA%011d;") % hz).encode())

    def setm(self, m):
        if self.y and m in TO_YAESU:
            self.s.write(f"MD0{TO_YAESU[m]};".encode())
        elif m in TO_KEN:
            self.s.write(f"MD{TO_KEN[m]};".encode())

    def ptt(self, on): self.s.write(b"TX1;" if on else b"TX0;")
    def close(self): self.s.close()


class _Icom:
    def __init__(self, s, addr):
        self.s, self.a = s, addr

    def tx(self, cmd, data=b""):
        self.s.reset_input_buffer()
        self.s.write(bytes([0xFE, 0xFE, self.a, 0xE0]) + cmd + data + b"\xFD")
        time.sleep(0.05)
        buf = self.s.read(64)
        for fr in buf.split(b"\xFD"):
            i = fr.find(b"\xFE\xFE\xE0")
            if i >= 0 and fr[i + 4:i + 5] == cmd[:1]:
                return fr[i + 5:]
        return b""

    @staticmethod
    def bcd(b):
        return sum(((x >> 4) * 10 + (x & 15)) * 100 ** i for i, x in enumerate(b))

    def read(self):
        f = self.bcd(self.tx(b"\x03")) / 1e6
        m = self.tx(b"\x04")
        return f, ICOM_MODES.get(m[0], "") if m else "", ""

    def setf(self, mhz):
        hz, b = round(mhz * 1e6), b""
        for _ in range(5):
            b += bytes([((hz // 10 % 10) << 4) | (hz % 10)]); hz //= 100
        self.tx(b"\x05", b)

    def setm(self, m):
        inv = {v: k for k, v in ICOM_MODES.items()}
        if m in inv:
            self.tx(b"\x06", bytes([inv[m]]))

    def ptt(self, on): self.tx(b"\x1c\x00", bytes([int(on)]))
    def close(self): self.s.close()


class Rotator(QObject):
    position = Signal(float, float)
    state = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.run, self.target = False, None

    def start(self, host, port):
        self.run = False
        time.sleep(0.05)
        self.run = True
        threading.Thread(target=self._loop, args=(host, int(port)), daemon=True).start()

    def goto(self, az, el=0):
        self.target = (az, el)

    def _loop(self, h, p):
        try:
            io = _Rigctld(h, p)
            self.state.emit(True, "Connecté")
        except Exception as e:
            self.state.emit(False, str(e)); self.run = False; return
        while self.run:
            try:
                if self.target:
                    io.cmd("P %.1f %.1f" % self.target); self.target = None
                az, el = io.cmd("p", 2)
                self.position.emit(float(az), float(el))
            except Exception as e:
                self.state.emit(False, str(e)); break
            time.sleep(1)
        io.close()


SPOT_RE = re.compile(r"DX de ([\w/\-#]+):?\s+([\d.]+)\s+([\w/]+)\s+(.*?)\s+(\d{4})Z", re.I)


class Cluster(QObject):
    spot = Signal(dict)
    line = Signal(str)
    state = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.sock = None

    def connect_(self, host, port, call):
        self.disconnect_()
        threading.Thread(target=self._loop, args=(host, int(port), call), daemon=True).start()

    def send(self, txt):
        if self.sock:
            try: self.sock.sendall((txt + "\r\n").encode())
            except Exception: pass

    def disconnect_(self):
        if self.sock:
            try: self.sock.close()
            except Exception: pass
        self.sock = None

    def _loop(self, h, p, call):
        try:
            self.sock = socket.create_connection((h, p), 10)
            self.state.emit(True, f"Connecté à {h}")
        except Exception as e:
            self.state.emit(False, str(e)); return
        buf, logged = b"", False
        try:
            while self.sock:
                d = self.sock.recv(4096)
                if not d:
                    break
                buf += d
                if not logged and re.search(rb"(login|call|indicatif)\s*:?\s*$", buf.lower()):
                    self.send(call); logged = True
                *lines, buf = buf.split(b"\n")
                for l in lines:
                    s = l.decode("latin-1").strip()
                    if not s:
                        continue
                    self.line.emit(s)
                    m = SPOT_RE.search(s)
                    if m:
                        self.spot.emit(dict(spotter=m.group(1), freq=float(m.group(2)) / 1000, call=m.group(3).upper(),
                                            comment=m.group(4).strip(), time=m.group(5)))
        except Exception:
            pass
        self.state.emit(False, "Déconnecté")


class WSJTX(QObject):
    status = Signal(dict)
    decode = Signal(dict)
    logged = Signal(str)

    def __init__(self):
        super().__init__()
        self.sock, self.addr = None, None

    def start(self, port=2237, mcast=""):
        self.stop()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", int(port)))
        if mcast:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(mcast) + socket.inet_aton("0.0.0.0"))
        self.sock = s
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        if self.sock:
            self.sock.close(); self.sock = None

    def reply(self, d):
        """Ask WSJT-X to answer a decode (message type 4)."""
        if not self.sock or not self.addr:
            return
        def qs(s):
            b = s.encode(); return struct.pack(">I", len(b)) + b
        pkt = struct.pack(">III", 0xADBCCBDA, 2, 4) + qs(d["id"]) + struct.pack(">IidI", d["t"], d["snr"], d["dt"], d["df"]) \
            + qs(d["mode"]) + qs(d["msg"]) + b"\x00" + b"\x00"
        self.sock.sendto(pkt, self.addr)

    def _loop(self):
        while self.sock:
            try:
                data, self.addr = self.sock.recvfrom(4096)
                self._parse(data)
            except OSError:
                break
            except Exception:
                continue

    def _parse(self, d):
        pos = [0]
        def u32():
            v = struct.unpack_from(">I", d, pos[0])[0]; pos[0] += 4; return v
        def i32():
            v = struct.unpack_from(">i", d, pos[0])[0]; pos[0] += 4; return v
        def u64():
            v = struct.unpack_from(">Q", d, pos[0])[0]; pos[0] += 8; return v
        def dbl():
            v = struct.unpack_from(">d", d, pos[0])[0]; pos[0] += 8; return v
        def boo():
            v = d[pos[0]] != 0; pos[0] += 1; return v
        def qs():
            n = u32()
            if n == 0xFFFFFFFF:
                return ""
            v = d[pos[0]:pos[0] + n].decode("utf-8", "replace"); pos[0] += n; return v
        if u32() != 0xADBCCBDA:
            return
        u32(); typ = u32(); ident = qs()
        if typ == 1:
            self.status.emit(dict(freq=u64() / 1e6, mode=qs(), dxcall=qs(), report=qs(), txmode=qs(), txen=boo(), tx=boo()))
        elif typ == 2:
            new = boo(); t = u32(); snr = i32(); dt = dbl(); df = u32(); mode = qs(); msg = qs()
            self.decode.emit(dict(id=ident, new=new, t=t, snr=snr, dt=dt, df=df, mode=mode, msg=msg))
        elif typ == 12:
            self.logged.emit(qs())
