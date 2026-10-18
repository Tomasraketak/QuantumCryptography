"""16bitove symetricke sifrovani (XOR s klicem), komprese obrazku a ramec prenosu."""
import numpy as np
from PIL import Image

MAGIC = b"IMG"

# rezim barev: (popis, bitu na pixel)
MODES = {
    0: ("1 bit - cernobile", 1),
    1: ("8 bit - odstiny sedi", 8),
    2: ("24 bit - barevne RGB", 24),
}


def xor16(data: bytes, key: int) -> bytes:
    """XOR kazdeho 16bit slova (big-endian) s klicem. Sifrovani = desifrovani.
    Funguje i na zacatek dat (prefix) - diky tomu lze desifrovat prubezne."""
    buf = bytearray(data)
    hi, lo = (key >> 8) & 0xFF, key & 0xFF
    for i in range(0, len(buf), 2):
        buf[i] ^= hi
        if i + 1 < len(buf):
            buf[i + 1] ^= lo
    return bytes(buf)


def payload_len(w: int, h: int, mode: int) -> int:
    return (w * h * MODES[mode][1] + 7) // 8


def encode_image(img: Image.Image, size: int, mode: int):
    """Zmensi a prevede obrazek do zvoleneho rezimu -> (bajty, nahled RGB)."""
    small = img.convert("RGB").resize((size, size), Image.LANCZOS)
    if mode == 0:
        bw = np.array(small.convert("L")) >= 128
        data = np.packbits(bw).tobytes()
    elif mode == 1:
        data = np.array(small.convert("L"), dtype=np.uint8).tobytes()
    else:
        data = np.array(small, dtype=np.uint8).tobytes()
    return data, decode_image(data, size, size, mode)


def decode_image(data: bytes, w: int, h: int, mode: int) -> np.ndarray:
    """Bajty -> RGB pole h x w x 3. Chybejici (neprijata) data = tmave sede."""
    n = payload_len(w, h, mode)
    known = len(data)
    data = data + bytes(n - known)
    if mode == 0:
        px = np.unpackbits(np.frombuffer(data, np.uint8))[: w * h] * 255
        done = min(known * 8, w * h)
        rgb = np.repeat(px[:, None], 3, axis=1).astype(np.uint8)
    elif mode == 1:
        px = np.frombuffer(data, np.uint8)[: w * h]
        done = min(known, w * h)
        rgb = np.repeat(px[:, None], 3, axis=1)
    else:
        rgb = np.frombuffer(data, np.uint8)[: w * h * 3].reshape(-1, 3)
        done = min(known // 3, w * h)
    rgb = rgb.copy()
    rgb[done:] = (40, 40, 48)
    return rgb.reshape(h, w, 3)


def make_frame(enc: bytes, w: int, h: int, mode: int) -> bytes:
    return MAGIC + bytes([w, h, mode]) + enc + bytes([sum(enc) & 0xFF])


class FrameParser:
    """Postupne skladani ramce z bajtu, ktere prichazi od Boba."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.buf = b""
        self.header = None      # (w, h, mode)
        self.data = b""
        self.checksum_ok = None

    def feed(self, chunk: bytes):
        if self.checksum_ok is not None:
            return
        self.buf += chunk
        if self.header is None:
            i = self.buf.find(MAGIC)
            if i < 0:
                self.buf = self.buf[-2:]
                return
            if len(self.buf) < i + 6:
                return
            w, h, mode = self.buf[i + 3:i + 6]
            self.header = (w, h, mode)
            self.buf = self.buf[i + 6:]
        n = payload_len(*self.header)
        need = n - len(self.data)
        self.data += self.buf[:need]
        self.buf = self.buf[need:]
        if len(self.data) == n and self.buf:
            self.checksum_ok = self.buf[0] == (sum(self.data) & 0xFF)

    @property
    def total(self):
        return payload_len(*self.header) if self.header else 0
