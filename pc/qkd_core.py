"""BB84 v Pythonu: Alice a Bob jako dva oddělené "počítače".

Pravidla, aby se nešvindlovalo:
  * Alice a Bob jsou samostatné objekty, každý běží ve svém vlákně a má svá
    soukromá data (bity, báze, klíč). Bob nemá na Alici žádný odkaz.
  * Jediná cesta mezi nimi je PublicChannel (vše, co jím projde, je veřejné
    a vypisuje se v GUI) + kvantový kanál = laser, který Bob změří detektory.
  * Bob si klíč skládá jen z vlastních měření. Když kvantový kanál nefunguje,
    Bob má jiný klíč a obrázek se mu nerozšifruje.

Hardware: jedno Arduino pro oba (SerialDevice). Alice posílá V H D A O C,
Bob + X; Arduino samo hlásí L<d0><d1> (VALID na 1) a W (VALID na 0).
Simulace: SimOptics nahrazuje Arduino i optiku (volitelně s Eve).
"""
import math
import queue
import random
import threading
import time

import qcrypt

KEY_BITS = 16
QBER_LIMIT = 0.11
NOISE = 0.03           # očekávaný šum optiky bez Eve
EVE_ERR = 0.25         # chybovost, kterou způsobí Eve (změř a pošli znovu)
VALID_TIMEOUT = 15     # s, déle bez L / W = chyba

# stav HWP pro (báze, bit); báze 0 = HV, 1 = DA; bit 0 = H/D, bit 1 = V/A
ALICE_CMD = {(0, 0): "H", (0, 1): "V", (1, 0): "D", (1, 1): "A"}
BOB_CMD = {0: "+", 1: "X"}        # báze HV = HWP 0°, báze DA = HWP +22.5°


# =================================================================== hardware
class SerialDevice:
    """Jedno Arduino na USB pro Alici i Boba.

    cmd(c)       pošle příkaz a počká na odpověď 'OK ...'
    wait(kind)   počká na zprávu, kterou Arduino pošle samo: L<d0><d1> nebo W
    """

    def __init__(self, port, log):
        import serial
        self.log = log
        self.ser = serial.Serial(port, 115200, timeout=0.2)
        self.lock = threading.Lock()
        self.replies, self.events = queue.Queue(), queue.Queue()
        time.sleep(2.5)                 # Arduino se po otevření portu restartuje
        self.ser.reset_input_buffer()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while True:
            line = self.ser.readline().decode(errors="replace").strip()
            if not line:
                continue
            self.log("Arduino", line)
            if line[0] == "L" or line == "W":
                self.events.put(line)        # samo od Arduina (VALID)
            # --- kamarádčin firmware: jiné texty, stejný význam
            elif line.startswith("COUNT=") and "D0=" in line:
                f = dict(x.split("=") for x in line.split())
                self.events.put("L" + f["D0"] + f["D1"])
            elif line.startswith("VALIDITY = 0"):  # bez 100 ms -> počkáme tady
                threading.Timer(0.1, self.events.put, ["W"]).start()
            elif line.startswith("OK BOTH"):       # samo vrátilo HWP na 0
                pass
            else:
                self.replies.put(line)       # odpověď na příkaz

    def cmd(self, c):
        with self.lock:
            self.ser.write((c + "\n").encode())
            self.log("PC", c)
            try:
                line = self.replies.get(timeout=6)
            except queue.Empty:
                raise IOError(f"žádná odpověď na '{c}'")
            if line.startswith("ERR"):
                raise IOError(f"Arduino: {line} (příkaz '{c}' – nejdřív ZERO1 a ZERO2?)")
            return line[3:] if line.startswith("OK ") else line

    def wait(self, kind, timeout=VALID_TIMEOUT):
        while True:
            try:
                line = self.events.get(timeout=timeout)
            except queue.Empty:
                what = "neskočil na 1 (chybí L)" if kind == "L" else "nespadl na 0 (chybí W)"
                raise IOError(f"VALID {what} do {timeout} s – zkontroluj detektor a laser")
            if line[0] == kind:
                return line[1:]

    def clear(self):
        while not self.events.empty():
            self.events.get()

    def close(self):
        self.ser.close()


class SimOptics(SerialDevice):
    """Simulace Arduina i optiky: laser, HWP, PBS, detektory, (Eve)."""

    ANGLE = {"V": ("alice", 0), "H": ("alice", 45), "D": ("alice", -22.5), "A": ("alice", 22.5),
             "+": ("bob", 0), "X": ("bob", 22.5)}

    def __init__(self, eve=lambda: False, noise=0.02, loss=0.05, delay=0.05):
        self.eve, self.noise, self.loss, self.delay = eve, noise, loss, delay
        self.hwp = {"alice": 0.0, "bob": 0.0}
        self.events = queue.Queue()

    @staticmethod
    def _measure(pol, hwp):
        """Polarizace (V=0°, H=90°, D=-45°, A=+45°) přes HWP a PBS -> bit."""
        out = 2 * hwp - pol
        return 1 if random.random() < math.cos(math.radians(out)) ** 2 else 0

    def cmd(self, c):
        time.sleep(self.delay)
        if c in self.ANGLE:
            who, a = self.ANGLE[c]
            self.hwp[who] = a
        elif c == "O":                       # laser svítí -> detektor -> L
            self.events.put("L" + self._flash())
        elif c == "C":                       # laser zhasl -> W
            self.events.put("W")
        return "OK"

    def _flash(self):
        if random.random() < self.loss:
            return "00"
        pol = 2 * self.hwp["alice"]                # polarizace za HWP Alice
        if self.eve():                             # Eve: změří a pošle znovu
            eb = random.randint(0, 1)
            ebit = self._measure(pol, [0, 22.5][eb])
            pol = {(0, 0): 90, (0, 1): 0, (1, 0): -45, (1, 1): 45}[(eb, ebit)]
        bit = self._measure(pol, self.hwp["bob"]) ^ (random.random() < self.noise)
        return "01" if bit else "10"

    def close(self):
        pass


# =================================================================== veřejný kanál
class PublicChannel:
    """Klasický veřejný kanál. Všechno, co jím jde, vidí i Eve (a GUI)."""

    def __init__(self, events):
        self.events = events
        self.box = {"alice": queue.Queue(), "bob": queue.Queue()}
        self.stopped = False

    def send(self, frm, to, kind, data=None, show=None):
        self.events.put(("PUB", frm, kind, data if show is None else show))
        self.box[to].put((kind, data))

    def recv(self, who, kind, timeout=60):
        k, data = self.box[who].get(timeout=timeout)
        if k == "STOP":
            raise SystemExit
        if k != kind:
            raise RuntimeError(f"{who}: čekal jsem {kind}, přišlo {k}")
        return data


def eve_probability(n, e):
    """Jak pravděpodobné je, že poslouchá Eve, když z n testovacích bitů vyšlo e chyb.
    Bayes s apriorní šancí 50 : 50 - porovnáme, co je pravděpodobnější:
    šum optiky (NOISE) nebo Eve (EVE_ERR). Bez testovacích bitů nevíme nic -> 0.5."""
    if n == 0:
        return 0.5
    l_eve = EVE_ERR ** e * (1 - EVE_ERR) ** (n - e)
    l_ok = NOISE ** e * (1 - NOISE) ** (n - e)
    return l_eve / (l_eve + l_ok)


def bits_str(bits):
    return "".join(str(b) for b in bits)


# =================================================================== Alice
class Alice(threading.Thread):
    def __init__(self, hw, ch, events):
        super().__init__(daemon=True)
        self.hw, self.ch, self.ev = hw, ch, events
        self.key = None              # soukromé!
        self.images = queue.Queue()
        self.go_on = threading.Event()

    def run(self):
        try:
            for rnd in range(1, 1000):
                self.ev.put(("ROUND", rnd))
                if self.one_round():
                    break
                self.ev.put(("PAUSE", rnd))   # počkej, až uživatel klikne „Další kolo“
                self.go_on.wait()
                self.go_on.clear()
                if self.ch.stopped:
                    return
            self.ev.put(("KEY", "alice", self.key))
            while True:                       # čekáme na obrázky k odeslání
                job = self.images.get()
                if job is None:
                    return
                self.send_image(*job)
        except SystemExit:
            pass
        except Exception as e:
            if not self.ch.stopped:
                self.ev.put(("ERROR", f"Alice: {e}"))

    def one_round(self):
        bits, bases, sifted = [], [], []
        k = self.n
        while True:
            # --- kvantová fáze: dávka k qubitů (veřejně ohlásíme kolik)
            start = len(bits)
            self.ch.send("alice", "bob", "BATCH", k, f"{k} qubitů (č. {start + 1}–{start + k})")
            for i in range(start, start + k):
                bits.append(random.randint(0, 1))
                bases.append(random.randint(0, 1))
                self.hw.cmd(ALICE_CMD[(bases[i], bits[i])])
                self.ev.put(("A", i, bases[i], bits[i]))
                self.ch.send("alice", "bob", "READY", i)
                self.ch.recv("alice", "BOB_READY")
                self.hw.cmd("O")                         # laser svítí
                self.ch.send("alice", "bob", "OPEN", i)
                self.ch.recv("alice", "MEASURED")
                self.hw.cmd("C")                         # laser zakrytý
                self.ch.send("alice", "bob", "CLOSED", i)
                self.ch.recv("alice", "DARK")
            self.hw.cmd("V")                             # HWP do nuly (V)
            # --- sifting této dávky
            bob_bases, bob_valid = self.ch.recv("alice", "BOB_BASES")
            self.ch.send("alice", "bob", "ALICE_BASES", bases[start:], bits_str(bases[start:]))
            sifted += [bits[i] for j, i in enumerate(range(start, len(bits)))
                       if bob_valid[j] and bases[i] == bob_bases[j]]
            if len(sifted) >= KEY_BITS:
                break
            if self.extra <= 0:                          # nedoposílat -> kolo znovu
                self.ch.send("alice", "bob", "VERDICT", "FEW")
                self.ev.put(("RESULT", "FEW", None, None, [], 0))
                return False
            k = self.extra                               # doposlat další
        # --- test odposlechu: vše nad 16 bitů klíče
        test = sifted[KEY_BITS:]
        errors = 0
        if test:
            self.ch.send("alice", "bob", "TEST_BITS", test, bits_str(test))
            errors = self.ch.recv("alice", "ERRORS")
        p_eve = eve_probability(len(test), errors)
        verdict = "FAIL" if p_eve > 0.5 else "OK"
        self.ch.send("alice", "bob", "VERDICT", verdict)
        self.ev.put(("RESULT", verdict, errors / len(test) if test else None, p_eve, test, errors))
        if verdict == "OK":
            self.key = int(bits_str(sifted[:KEY_BITS]), 2)
        return verdict == "OK"

    def send_image(self, img, size, mode):
        data, preview = qcrypt.encode_image(img, size, mode)
        enc = qcrypt.xor16(data, self.key)           # šifruje SVÝM klíčem
        self.ev.put(("ALICE_IMG", preview, enc, size, mode))
        self.ch.send("alice", "bob", "IMG_HEADER", (size, mode), f"{size}x{size}, režim {mode}")
        step = max(32, len(enc) // 100 // 2 * 2)     # ~100 kousků, sudá délka
        for i in range(0, len(enc), step):
            chunk = enc[i:i + step]
            shown = chunk[:32].hex(" ") + (f" … ({len(chunk)} B)" if len(chunk) > 32 else "")
            self.ch.send("alice", "bob", "IMG_DATA", chunk, shown)
            self.ev.put(("ALICE_SENT", i + len(chunk)))
            time.sleep(0.03)
        self.ch.send("alice", "bob", "IMG_END")


# =================================================================== Bob
class Bob(threading.Thread):
    def __init__(self, hw, ch, events):
        super().__init__(daemon=True)
        self.hw, self.ch, self.ev = hw, ch, events
        self.key = None              # soukromé!

    def run(self):
        try:
            while self.key is None:
                self.one_round()
            self.ev.put(("KEY", "bob", self.key))
            while True:
                self.receive_image()
        except SystemExit:
            pass
        except Exception as e:
            if not self.ch.stopped:
                self.ev.put(("ERROR", f"Bob: {e}"))

    def one_round(self):
        bases, results, sifted = [], [], []
        first = True
        while True:
            kind, data = self.ch.box["bob"].get(timeout=None if first else 60)  # pauza mezi koly
            first = False
            if kind == "STOP":
                raise SystemExit
            if kind != "BATCH":
                break                                    # TEST_BITS nebo VERDICT
            start = len(bases)
            for i in range(start, start + data):
                self.ch.recv("bob", "READY")
                b = random.randint(0, 1)
                self.hw.cmd(BOB_CMD[b])
                bases.append(b)
                self.hw.clear()                          # staré L/W zahodit
                self.ch.send("bob", "alice", "BOB_READY", i)
                self.ch.recv("bob", "OPEN")
                d = self.hw.wait("L")                    # VALID na 1: "10" nebo "01"
                res = {"10": 0, "01": 1}.get(d)          # jinak ztráta
                results.append(res)
                self.ev.put(("B", i, b, res))
                self.ch.send("bob", "alice", "MEASURED", i)
                self.ch.recv("bob", "CLOSED")
                self.hw.wait("W")                        # VALID = 0 + 100 ms
                self.ch.send("bob", "alice", "DARK", i)
            self.hw.cmd("+")                             # HWP do nuly
            valid = [r is not None for r in results[start:]]
            self.ch.send("bob", "alice", "BOB_BASES", (bases[start:], valid),
                         f"báze {bits_str(bases[start:])}\nzachyceno {bits_str(int(v) for v in valid)}")
            alice_bases = self.ch.recv("bob", "ALICE_BASES")
            sifted += [results[i] for j, i in enumerate(range(start, len(bases)))
                       if valid[j] and bases[i] == alice_bases[j]]
        if kind == "TEST_BITS":
            errors = sum(a != b for a, b in zip(data, sifted[KEY_BITS:]))
            self.ch.send("bob", "alice", "ERRORS", errors)
            self.ev.put(("BOB_QBER", errors / len(data)))
            kind, data = "VERDICT", self.ch.recv("bob", "VERDICT")
        if data == "OK":
            self.key = int(bits_str(sifted[:KEY_BITS]), 2)

    def receive_image(self):
        size, mode = self.ch.recv("bob", "IMG_HEADER")
        enc = dec = b""
        while True:
            kind, data = self.ch.box["bob"].get()
            if kind == "IMG_END":
                break
            enc += data
            dec += qcrypt.xor16(data, self.key)      # dešifruje SVÝM klíčem
            self.ev.put(("BOB_IMG", enc, dec, size, mode))
        self.ev.put(("BOB_IMG_DONE",))


# =================================================================== celé
class Session:
    """Spojí hardware (nebo simulaci), kanál, Alici a Boba."""

    def __init__(self, events, alice_hw, bob_hw):
        self.events = events
        self.alice_hw, self.bob_hw = alice_hw, bob_hw
        self.ch = PublicChannel(events)
        self.alice = self.bob = None

    def start(self, n=64, extra=16):
        self.alice = Alice(self.alice_hw, self.ch, self.events)
        self.alice.n, self.alice.extra = n, extra
        self.bob = Bob(self.bob_hw, self.ch, self.events)
        self.bob.start()
        self.alice.start()

    def next_round(self):
        self.alice.go_on.set()

    def stop(self):
        """Okamžitě ukončí Alici i Boba (tlačítko vypnutí)."""
        self.ch.stopped = True
        for who in ("alice", "bob"):
            self.ch.box[who].put(("STOP", None))
        self.alice.go_on.set()
        self.alice.images.put(None)
        for e in ("L00", "W"):                   # ať Bob nečeká na detektor
            self.bob_hw.events.put(e)

    def send_image(self, img, size, mode):
        self.alice.images.put((img, size, mode))
