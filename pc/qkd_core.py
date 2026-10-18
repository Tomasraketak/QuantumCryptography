"""Komunikace s Arduiny (nebo simulace) a vyhodnoceni BB84 - bez GUI.

Obe Arduina posilaji na USB radky; GUI zajimaji hlavne strojove radky:
  Alice: #ROUND n | #A i baze bit | QBER:x | #RESULT OK/FAIL/FEW | KEY:XXXX
  Bob:   #B i baze vysledek(0/1/-) | QBER:x | KEY:XXXX
Po KEY prejdou do rezimu prenosu obrazku (Alice: USB -> linka, potvrzuje '.').
Udalosti se davaji do fronty jako (zdroj, data): ('alice', radek),
('bob', radek), ('bobraw', bajty), ('status', text).
"""
import queue
import random
import threading
import time

N_QUBITS = 64
KEY_BITS = 16
QBER_LIMIT = 0.11


# --------------------------------------------------------------- vyhodnoceni
class Round:
    """Data jednoho kola BB84 tak, jak je GUI vidi z obou stran."""

    def __init__(self, number):
        self.number = number
        self.alice = {}   # i -> (baze, bit)
        self.bob = {}     # i -> (baze, vysledek nebo None)

    def sift(self):
        """Indexy, kde se baze shoduji a Bob neco zmeril."""
        return [i for i in sorted(self.alice)
                if i in self.bob and self.bob[i][1] is not None
                and self.alice[i][0] == self.bob[i][0]]

    def analysis(self):
        s = self.sift()
        key_idx, test_idx = s[:KEY_BITS], s[KEY_BITS:]
        errors = [i for i in test_idx if self.alice[i][1] != self.bob[i][1]]
        qber = len(errors) / len(test_idx) if test_idx else None
        key = None
        if len(key_idx) == KEY_BITS:
            key = 0
            for i in key_idx:
                key = (key << 1) | self.alice[i][1]
        return dict(sifted=s, key_idx=key_idx, test_idx=test_idx,
                    errors=errors, qber=qber, key=key)


def parse_line(line):
    """Strojovy radek -> (typ, hodnoty) nebo None."""
    p = line.split()
    if not p:
        return None
    if p[0] == "#A" and len(p) == 4:
        return "A", (int(p[1]), int(p[2]), int(p[3]))
    if p[0] == "#B" and len(p) == 4:
        return "B", (int(p[1]), int(p[2]), None if p[3] == "-" else int(p[3]))
    if p[0] == "#ROUND":
        return "ROUND", int(p[1])
    if p[0] == "#RESULT":
        return "RESULT", p[1]
    if line.startswith("QBER:"):
        return "QBER", float(line[5:])
    if line.startswith("KEY:"):
        return "KEY", int(line[4:], 16)
    return None


# --------------------------------------------------------------- backendy
class SerialBackend:
    """Dve skutecna Arduina na dvou COM portech."""

    def __init__(self, alice_port, bob_port, events):
        import serial
        self.events = events
        self.acks = queue.Queue()
        self.alice = serial.Serial(alice_port, 115200, timeout=0.1)
        self.bob = serial.Serial(bob_port, 115200, timeout=0.1)
        self.alice_bridge = self.bob_bridge = False
        self.running = True
        events.put(("status", "Porty otevreny, Arduina se restartuji..."))
        threading.Thread(target=self._read, args=("alice",), daemon=True).start()
        threading.Thread(target=self._read, args=("bob",), daemon=True).start()

    def _read(self, who):
        ser = self.alice if who == "alice" else self.bob
        buf = b""
        while self.running:
            data = ser.read(256)
            if not data:
                continue
            if who == "bob" and self.bob_bridge:
                self.events.put(("bobraw", data))
                continue
            if who == "alice" and self.alice_bridge:
                for _ in range(data.count(b".")):
                    self.acks.put(1)
                continue
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode(errors="replace").strip()
                self.events.put((who, line))
                if line.startswith("KEY:"):
                    if who == "alice":
                        self.alice_bridge = True
                    else:
                        self.bob_bridge = True
                        if buf:
                            self.events.put(("bobraw", buf))
                        buf = b""

    def start_qkd(self):
        self.alice.write(b"g\n")

    def send_chunk(self, chunk):
        """Posle max 32 B pres Alici a pocka na potvrzeni."""
        self.alice.write(chunk)
        try:
            self.acks.get(timeout=5)
            return True
        except queue.Empty:
            return False

    def close(self):
        self.running = False
        self.alice.close()
        self.bob.close()


class SimBackend:
    """Simulace obou Arduin (a volitelne Eve) - pro vyzkouseni bez optiky."""

    def __init__(self, events, eve_flag, noise=0.03, loss=0.08, speed=0.12):
        self.events = events
        self.eve = eve_flag          # callable -> bool (zaskrtavatko v GUI)
        self.noise, self.loss, self.speed = noise, loss, speed
        events.put(("status", "Simulace pripravena (bez hardwaru)."))

    def start_qkd(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _a(self, s):
        self.events.put(("alice", s))

    def _b(self, s):
        self.events.put(("bob", s))

    def _run(self):
        rnd = 0
        while True:
            rnd += 1
            self._a(f"===== KOLO {rnd} =====")
            self._a(f"#ROUND {rnd}")
            r = Round(rnd)
            for i in range(N_QUBITS):
                ab, abit = random.randint(0, 1), random.randint(0, 1)
                self._a(f"#A {i} {ab} {abit}")
                r.alice[i] = (ab, abit)
                time.sleep(self.speed)
                # foton letici k Bobovi: (baze, bit)
                pb, pbit = ab, abit
                if self.eve():
                    eb = random.randint(0, 1)
                    ebit = pbit if eb == pb else random.randint(0, 1)
                    pb, pbit = eb, ebit
                bb = random.randint(0, 1)
                if random.random() < self.loss:
                    res = None
                elif bb == pb:
                    res = pbit ^ (random.random() < self.noise)
                else:
                    res = random.randint(0, 1)
                r.bob[i] = (bb, res)
                self._b(f"#B {i} {bb} {'-' if res is None else res}")
                time.sleep(self.speed)
            an = r.analysis()
            if not an["test_idx"] or len(an["test_idx"]) < 8 or an["key"] is None:
                self._a("#RESULT FEW")
                continue
            for out in (self._a, self._b):
                out(f"QBER:{an['qber']:.4f}")
            if an["qber"] > QBER_LIMIT:
                self._a("#RESULT FAIL")
                time.sleep(1.5)
                continue
            self._a("#RESULT OK")
            self._a(f"KEY:{an['key']:04X}")
            self._b(f"KEY:{an['key']:04X}")
            return

    def send_chunk(self, chunk):
        time.sleep(len(chunk) * 10 / 9600 + 0.01)   # 9600 Bd SoftwareSerial
        self.events.put(("bobraw", bytes(chunk)))
        return True

    def close(self):
        pass
