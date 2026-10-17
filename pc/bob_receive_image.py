"""Bob PC: ceka na klic z QKD, prijme zasifrovany obrazek, desifruje a zobrazi.

Pouziti:  python bob_receive_image.py COM4
"""
import argparse
import time

import matplotlib.pyplot as plt
import serial

from qcrypt import MAGIC, bytes_to_image, xor16

ap = argparse.ArgumentParser()
ap.add_argument("port")
args = ap.parse_args()

ser = serial.Serial(args.port, 115200, timeout=1)
time.sleep(2.5)

key = None
while key is None:
    line = ser.readline().decode(errors="replace").rstrip()
    if not line:
        continue
    print(line)
    if line.startswith("KEY:"):
        key = int(line[4:], 16)
print(f"\nKlic: {key:016b} (0x{key:04X}) - cekam na obrazek...")

ser.timeout = None
buf = b""
while not buf.endswith(MAGIC):       # najdi zacatek ramce
    buf = (buf + ser.read(1))[-3:]
w, h = ser.read(2)
n = w * h * 3
enc = b""
while len(enc) < n:
    enc += ser.read(n - len(enc))
    print(f"\r{len(enc)}/{n} B", end="")
chk = ser.read(1)[0]
print()
if chk != sum(enc) & 0xFF:
    print("VAROVANI: kontrolni soucet nesedi, data mohou byt poskozena")

dec = xor16(enc, key)
fig, ax = plt.subplots(1, 2, figsize=(8, 4))
ax[0].imshow(bytes_to_image(enc, w, h), interpolation="nearest")
ax[0].set_title("Prijato (zasifrovano)")
ax[1].imshow(bytes_to_image(dec, w, h), interpolation="nearest")
ax[1].set_title(f"Desifrovano klicem 0x{key:04X}")
for a in ax:
    a.axis("off")
plt.tight_layout()
plt.show()
