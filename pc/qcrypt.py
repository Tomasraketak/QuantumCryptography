"""16bitove symetricke sifrovani (XOR s klicem) a format ramce obrazku."""
import numpy as np

MAGIC = b"IMG"


def xor16(data: bytes, key: int) -> bytes:
    """XOR kazdeho 16bit slova (big-endian) s klicem. Sifrovani = desifrovani."""
    buf = bytearray(data)
    hi, lo = (key >> 8) & 0xFF, key & 0xFF
    for i in range(0, len(buf), 2):
        buf[i] ^= hi
        if i + 1 < len(buf):
            buf[i + 1] ^= lo
    return bytes(buf)


def image_to_bytes(img: np.ndarray) -> bytes:
    return img.astype(np.uint8).tobytes()


def bytes_to_image(data: bytes, w: int, h: int) -> np.ndarray:
    return np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)


def make_frame(enc: bytes, w: int, h: int) -> bytes:
    return MAGIC + bytes([w, h]) + enc + bytes([sum(enc) & 0xFF])
