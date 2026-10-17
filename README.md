# QKD demonstrátor (BB84) – Arduino Uno

Alice (vysílač) a Bob (přijímač), každý Arduino Uno + CNC shield V3, propojení klasickým kanálem přes SoftwareSerial.

## Zapojení
| | Alice | Bob |
|---|---|---|
| Krokáč HWP | osa X: STEP D2, DIR D5, EN D8 | osa X: STEP D2, DIR D5, EN D8 |
| Servo shutter | D9 (X-limit) | – |
| Detektory | – | D9 det1 (H/D = bit 0), D10 det2 (V/A = bit 1), D11 valid |
| Link | A0 RX ← Bob A1, A1 TX → Bob A0 | A0 RX ← Alice A1, A1 TX → Alice A0 |

**Společná GND!** Úroveň detektorů nastav v `ACTIVE` (bob.ino), mikrokrokování v `STEPS_PER_REV`.

## Kalibrace (Serial Monitor 115200, „Newline“)
- Alice: `o`/`c` shutter, `a 22.5` HWP na úhel, `j 10` posun o kroky, `z` nulovat, `H V D A` nastav stav.
- Bob: `d` stav detektorů, `a`, `j`, `z`, `h`/`x` báze HV/DA.
- Před startem ručně/`j` natoč obě HWP do nuly (H prochází na det1) a dej `z`. Doladit `HWP_ANGLE`, `HWP_BASIS`, `SHUTTER_OPEN/CLOSED`.

## Protokol
1. Pro každý z `N_QUBITS`=64 qubitů: Alice náhodně bit+báze, nastaví HWP → `R i`; Bob náhodně báze → `K i`; Alice otevře shutter → `P i`; Bob změří → `M i`; shutter zavřít. (~2–3 s/bit, limit 15 s.)
2. Sifting: Bob pošle báze + které měření bylo validní, Alice pošle báze. Ponechají se shodné báze.
3. Prvních 16 prosetých bitů = klíč, zbytek (≥ 8) se veřejně porovná → QBER. QBER > 11 % ⇒ odposlech, klíč se zahodí a kolo se opakuje automaticky (intercept-resend Eve dává teoreticky 25 %).
4. Po `KEY:XXXX` přejdou Arduina do režimu přenosu obrázku.

## Obrázek (PC)
```
pip install -r pc/requirements.txt
python pc/bob_receive_image.py COM4          # nejdřív Bob
python pc/alice_send_image.py COM3 obr.png   # spustí QKD a pošle obrázek
```
Alice zmenší obrázek na 32×32 RGB, XORuje každé 16bit slovo klíčem (`pc/qcrypt.py`), uloží `encrypted.png` a pošle ho přes linku. Bob dešifruje a zobrazí šifrovaný i dešifrovaný obrázek vedle sebe.

## Eve
Intercept-resend = další stanoviště Bob-setup + Alice-setup v cestě paprsku. Firmware Alice/Boba se nemění; odposlech se projeví QBER ≈ 25 %.
