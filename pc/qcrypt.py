"""Šifrování obrázku AES-128 (CTR) klíčem odvozeným z 16bitového QKD klíče + komprese obrázku."""
import hashlib
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import numpy as np
from PIL import Image

MAGIC = b"IMG"

# rezim barev: (popis, bitu na pixel)
MODES = {
    0: ("1 bit - cernobile", 1),
    1: ("8 bit - odstiny sedi", 8),
    2: ("24 bit - barevne RGB", 24),
}


def derive_key(key16: int) -> bytes:
    """16bitový klíč z QKD -> 128bitový klíč pro AES (SHA-256, prvních 16 B)."""
    return hashlib.sha256(key16.to_bytes(2, "big")).digest()[:16]


def new_nonce() -> bytes:
    """Náhodné číslo pro režim CTR. Není tajné, posílá se veřejně."""
    return os.urandom(16)


def cipher(key16: int, nonce: bytes):
    """AES-128 v režimu CTR. Šifrování i dešifrování je stejné: .update(bajty).
    Funguje po kouscích - Bob může dešifrovat průběžně, jak data přicházejí."""
    return Cipher(algorithms.AES(derive_key(key16)), modes.CTR(nonce)).encryptor()


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
