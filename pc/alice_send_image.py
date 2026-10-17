"""Alice PC: spusti QKD, ziska klic, zasifruje obrazek a posle ho Bobovi.

Pouziti:  python alice_send_image.py COM3 obrazek.png [--size 32]
Nejdriv spust bob_receive_image.py (otevreni portu restartuje Arduino).
"""
import argparse
import time

import numpy as np
import serial
from PIL import Image

from qcrypt import image_to_bytes, make_frame, xor16

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("image")
ap.add_argument("--size", type=int, default=32, help="strana obrazku v px (max 255)")
args = ap.parse_args()

img = np.array(Image.open(args.image).convert("RGB").resize((args.size, args.size)))
h, w, _ = img.shape

ser = serial.Serial(args.port, 115200, timeout=1)
time.sleep(2.5)                      # Arduino se po otevreni portu restartuje
ser.reset_input_buffer()
ser.write(b"g\n")                    # start QKD

key = None
qbers = []
while key is None:
    line = ser.readline().decode(errors="replace").rstrip()
    if not line:
        continue
    print(line)
    if line.startswith("QBER:"):
        qbers.append(float(line[5:]))
    if line.startswith("KEY:"):
        key = int(line[4:], 16)

print(f"\nKlic: {key:016b} (0x{key:04X}), QBER pokusu: {qbers}")
enc = xor16(image_to_bytes(img), key)
Image.fromarray(np.frombuffer(enc, np.uint8).reshape(h, w, 3)).save("encrypted.png")
print("Zasifrovany obrazek ulozen do encrypted.png")

time.sleep(0.5)
ser.reset_input_buffer()
frame = make_frame(enc, w, h)
print(f"Posilam {len(frame)} B ...")
for i in range(0, len(frame), 32):   # rizeni toku: 32 B, cekej na '.'
    ser.write(frame[i:i + 32])
    if ser.read(1) != b".":
        raise SystemExit("Alice nepotvrdila blok - zkontroluj spojeni")
    print(f"\r{min(i + 32, len(frame))}/{len(frame)} B", end="")
print("\nHotovo.")
