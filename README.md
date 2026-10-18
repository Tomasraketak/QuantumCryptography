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

## GUI – vše v jednom okně (PC)
Obě Arduina zapoj USB do jednoho PC (každé má svůj COM port).
```
pip install -r pc/requirements.txt
python pc/qkd_gui.py
```
1. Vyber port Alice a Boba → **Připojit** (Arduina se restartují, ~2,5 s). Bez hardwaru zaškrtni **Simulace** (+ volitelně **Eve poslouchá**).
2. **START** – tabulka ukazuje qubit po qubitu, co Alice nastavila (bit, báze, úhel HWP, polarizace) a co Bob naměřil. Po siftingu se řádky obarví (klíč / test / chyba / zahozeno), ukáže se QBER na škále s prahem 11 % a klíč.
3. **Nahrát obrázek**, zvol rozlišení a barevnou hloubku (1/8/24 bit) – GUI ukáže velikost a odhad doby přenosu. **Zašifrovat a poslat** – vidíš živě 4 obrázky: originál, zašifrovaná data u Alice, co přišlo k Bobovi a Bobovo dešifrování.

Obrázek fyzicky jde PC → Alice → SoftwareSerial linka → Bob → PC. Serial Monitor nesmí být otevřený současně s GUI.

Soubory: `pc/qkd_gui.py` (okno), `pc/qkd_core.py` (sériová komunikace, simulace, vyhodnocení BB84), `pc/qcrypt.py` (komprese, XOR šifrování, rámec).

## Eve
Intercept-resend = další stanoviště Bob-setup + Alice-setup v cestě paprsku. Firmware Alice/Boba se nemění; odposlech se projeví QBER ≈ 25 %.
