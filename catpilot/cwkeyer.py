"""CW au clavier : code Morse, durées, et manipulateur par la ligne DTR/RTS.

Deux façons d'émettre :
- par la mémoire du keyer du poste (commandes CAT KM / KY), sans réglage ;
- par la ligne DTR (ou RTS) du port COM « Standard » du poste, comme Fldigi ou
  N1MM. Il faut alors régler le menu PC KEYING du poste sur DTR (ou RTS).
"""
import re
import threading
import time

import serial

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "=": "-...-", "+": ".-.-.",
    "-": "-....-", "(": "-.--.", ")": "-.--.-", "'": ".----.", ":": "---...", "@": ".--.-.",
    "<AR>": ".-.-.", "<SK>": "...-.-", "<BT>": "-...-", "<KN>": "-.--.", "<AS>": ".-...",
}
TOKEN = re.compile(r"<[A-Z]{2}>|.", re.S)


def normalize(text):
    """Majuscules, sans accents ni caractères inconnus du Morse."""
    import unicodedata
    t = unicodedata.normalize("NFKD", text.upper()).encode("ascii", "ignore").decode()
    return "".join(tok for tok in TOKEN.findall(t) if tok in MORSE or tok == " ")


def duration(text, wpm):
    """Durée d'émission en secondes (méthode PARIS : 1 point = 1,2 / wpm s)."""
    dot = 1.2 / max(5, wpm)
    units = 0
    for word in normalize(text).split():
        for tok in TOKEN.findall(word):
            code = MORSE.get(tok, "")
            units += sum(1 if c == "." else 3 for c in code) + (len(code) - 1) + 3
        units += 4                      # 3 + 4 = 7 unités entre les mots
    return units * dot


class LineKeyer:
    """Manipulation par une ligne de contrôle d'un port série, dans un fil dédié."""

    def __init__(self, port, line="DTR"):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = 9600
        self.ser.dtr = False             # surtout ne pas émettre à l'ouverture
        self.ser.rts = False
        self.ser.open()
        self.line = line
        self._stop = threading.Event()
        self._thread = None

    def _key(self, down):
        if self.line == "RTS":
            self.ser.rts = down
        else:
            self.ser.dtr = down

    @staticmethod
    def _wait(t):
        end = time.perf_counter() + t
        while True:
            left = end - time.perf_counter()
            if left <= 0:
                return
            time.sleep(left - 0.002 if left > 0.004 else 0)

    def send(self, text, wpm, done=None):
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(normalize(text), wpm, done), daemon=True)
        self._thread.start()

    def _run(self, text, wpm, done):
        dot = 1.2 / max(5, wpm)
        try:
            for wi, word in enumerate(text.split()):
                if wi:
                    self._wait(4 * dot)
                for tok in TOKEN.findall(word):
                    for ci, c in enumerate(MORSE.get(tok, "")):
                        if self._stop.is_set():
                            return
                        if ci:
                            self._wait(dot)
                        self._key(True)
                        self._wait(dot if c == "." else 3 * dot)
                        self._key(False)
                    self._wait(3 * dot)
        finally:
            self._key(False)
            if done:
                done()

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1)
        self._key(False)

    def close(self):
        self.stop()
        self.ser.close()
