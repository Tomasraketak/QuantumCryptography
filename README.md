# QKD demonstrátor (BB84) – Arduino Uno

Alice (vysílač) a Bob (přijímač), každý Arduino Uno + CNC shield V3, propojení klasickým kanálem přes SoftwareSerial.

## Zapojení
| | Alice | Bob |
|---|---|---|
| Krokáč HWP | osa X: STEP D2, DIR D5, EN D8 | osa X: STEP D2, DIR D5, EN D8 |
| Servo shutter | D9 (X-limit) | – |
| Detektory | – | D9 det1 (H/D = bit 0), D10 det2 (V/A = bit 1), **D3 VALID** (pin Y.STEP – v Y slotu nesmí být driver; D3 umí přerušení) |
| Link | A0 RX ← Bob A1, A1 TX → Bob A0 | A0 RX ← Alice A1, A1 TX → Alice A0 |

**Společná GND!** Úroveň detektorů nastav v `ACTIVE` (bob.ino), mikrokrokování v `STEPS_PER_REV`.

## Příkazy (Serial Monitor 115200)
- Alice: `g` start, `o`/`c` shutter otevřít/zavřít.
- Bob: `d` vypíše stav det1, det2, VALID.
- Před startem natoč obě HWP ručně do nuly (H prochází na det1). Úhly a servo dolaď v konstantách `UHEL`, `UHEL_BAZE`, `SERVO_OTEVRENO/ZAVRENO`.

## Protokol
Jeden qubit (kvantový kanál):

| Alice | linka | Bob |
|---|---|---|
| náhodný bit + báze, natočí HWP | `R i` → | náhodná báze, natočí HWP |
| | ← `K` | |
| otevře shutter | `P` → | čeká na přerušení VALID↑ (max 2 s, jinak ztráta), v něm přečte det1/det2 |
| | ← `M` | |
| zavře shutter | `Z` → | čeká, až VALID = 0, pak 100 ms |
| další qubit | ← `D` | |

Po 64 qubitech: Bob pošle báze (`BB`) a které měření bylo platné (`BV`), Alice pošle báze (`AB`). Nechají se jen shodné báze. Prvních 16 bitů = klíč, zbytek (≥ 8) Alice veřejně pošle (`TB`), Bob vrátí počet chyb (`Q`) → QBER. QBER > 11 % ⇒ odposlech (Eve ≈ 25 %), kolo se opakuje. Pak `KEY:XXXX` a přenos obrázku.

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
