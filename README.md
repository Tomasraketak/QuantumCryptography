# QKD demonstrátor (BB84) – Arduino Uno + PC

Školní demonstrátor kvantové distribuce klíče protokolem **BB84** (Talentová akademie 2026).
Alice pošle Bobovi laserem polarizované „qubity“. Z nich si oba složí stejný tajný **16bitový klíč**.
Kdyby kanál někdo odposlouchával (Eve), prozradí se zvýšenou chybovostí (QBER).
Nakonec Alice klíčem zašifruje malý obrázek. Bob ho svým klíčem dešifruje a GUI ukáže celý průběh.

---

## Obsah
1. [Jak BB84 funguje](#1-jak-bb84-funguje)
2. [Optika a polarizace](#2-optika-a-polarizace)
3. [Architektura: kdo co dělá](#3-architektura-kdo-co-dělá)
4. [Proč to „nepodvádí“](#4-proč-to-nepodvádí)
5. [Hardware a zapojení](#5-hardware-a-zapojení)
6. [Firmware a příkazy Arduina](#6-firmware-a-příkazy-arduina)
7. [Průběh jednoho qubitu (časování)](#7-průběh-jednoho-qubitu-časování)
8. [Sifting, QBER a klíč](#8-sifting-qber-a-klíč)
9. [Šifrování obrázku](#9-šifrování-obrázku)
10. [Instalace a spuštění GUI](#10-instalace-a-spuštění-gui)
11. [Popis GUI](#11-popis-gui)
12. [Kalibrace](#12-kalibrace)
13. [Simulace a Eve](#13-simulace-a-eve)
14. [Struktura souborů](#14-struktura-souborů)
15. [Řešení problémů](#15-řešení-problémů)

---

## 1. Jak BB84 funguje

Bit se kóduje do polarizace světla ve dvou **bázích**:

| báze | bit 0 | bit 1 |
|---|---|---|
| **HV** (přímá, „+“) | H – horizontální | V – vertikální |
| **DA** (diagonální, „×“) | D – diagonální | A – antidiagonální |

Postup:
1. **Alice** pro každý qubit náhodně zvolí bit a bázi a pošle odpovídající polarizaci.
2. **Bob** náhodně zvolí bázi, ve které měří.
   - Když se báze shodují, naměří přesně Alicin bit.
   - Když se liší, naměří náhodně 0 nebo 1 (50 : 50).
3. **Sifting:** veřejně si řeknou jen *báze*, ne bity. Qubity s různými bázemi zahodí.
   Zbylé bity („prosáté“) by měly být u obou stejné.
4. **Test odposlechu:** část prosátých bitů zveřejní a porovná. Podíl chyb je **QBER**.
5. Když QBER ≤ 11 %, zbytek bitů je tajný klíč. Když je vyšší, někdo poslouchá a kolo se opakuje.

**Proč se Eve prozradí:** neví, ve které bázi Alice posílala. Musí hádat, změřit a poslat nový foton.
V polovině případů hádá špatně a pošle špatnou polarizaci. Bob pak i při správné bázi dostane
v polovině těchto případů chybný bit. To je 0,5 · 0,5 = **25 % chyb**. Šum skutečné optiky bývá
jen pár procent, proto je hranice 11 %.

---

## 2. Optika a polarizace

**Alice:** laser → shutter (kruh na servu) → polarizátor (pevně V) → HWP na krokovém motoru → vzduch
**Bob:** HWP na krokovém motoru → polarizační dělič (PBS) → detektor 0 (H) / detektor 1 (V)

**Půlvlnná destička (HWP)** otočená o úhel θ otočí polarizaci o 2θ. Proto stačí natáčet HWP o polovinu úhlu:

| stav | polarizace | úhel HWP Alice | příkaz |
|---|---|---|---|
| V (bit 1, HV) | 0° | 0° | `V` |
| H (bit 0, HV) | 90° | 45° | `H` |
| D (bit 0, DA) | −45° | −22,5° | `D` |
| A (bit 1, DA) | +45° | +22,5° | `A` |

**Bob** má HWP jen ve dvou polohách:
- **báze HV:** HWP 0° (`+`). H jde na detektor 0, V na detektor 1.
- **báze DA:** HWP +22,5° (`X`). Otočí D na H (detektor 0) a A na V (detektor 1).
  H a V se otočí na diagonálu, takže PBS je rozdělí náhodně 50 : 50.

Pravidlo: **detektor 0 = bit 0, detektor 1 = bit 1.**

Když laser není potřeba (konec kola, před vypnutím), obě HWP jdou do **nuly** (vertikální polarizace).

---

## 3. Architektura: kdo co dělá

```
                          ┌─────────────── PC (Python) ───────────────┐
                          │  Alice (vlákno)  ◄─ PublicChannel ─►  Bob │
                          │  soukromé:         (vše se vypisuje  soukr.│
                          │  bity, báze,       v GUI)            báze, │
                          │  klíč, obrázek                   měření,  │
                          └──────────────────┬─────────────────klíč───┘
                                             │ USB (jeden port)
                          ┌──────────────────┴────────────────────────┐
                          │ Arduino Uno + CNC shield                  │
                          │  Alice: servo + HWP (Z)   Bob: HWP (X) +   │
                          │                           detektory, VALID │
                          └───────┬───────────────────────────▲───────┘
                                  └──── laser (kvantový kanál) ┘
```

- **PC** dělá všechno chytré: náhodu, sifting, QBER, klíč, šifrování a GUI.
- **Jedno Arduino** slouží Alici i Bobovi. Je „hloupé“: dostává jednoduché textové příkazy (natoč HWP, otevři shutter) a odpovídá `OK …`.
  Samo od sebe hlásí jen stav detektoru (`L..`, `W`).
- Alicina a Bobova strana mají **každá své příkazy**. Python je posílá ze dvou oddělených objektů, které o sobě nevědí.
  Jediné, co jde od Alice k Bobovi fyzicky, je laserový paprsek.

---

## 4. Proč to „nepodvádí“

V jednom programu by bylo snadné „omylem“ dát Bobovi Alicin klíč. Kód tomu brání takto (`pc/qkd_core.py`):

- `Alice` a `Bob` jsou **dvě samostatné třídy, každá ve vlastním vlákně**. Bob nemá na objekt Alice žádný odkaz.
- Jediné spojení je `PublicChannel`. **Každá zpráva** se vypíše v GUI v okně „Veřejný kanál (vidí i Eve)“.
- Veřejným kanálem jde jen:
  - synchronizace („připraveno“, „otevřeno“, „změřeno“…),
  - Bobovy báze a informace, které qubity zachytil,
  - Aliciny báze,
  - testovací bity a počet chyb,
  - verdikt OK/FAIL,
  - **zašifrovaný** obrázek.
- **Klíč ani nezašifrovaný obrázek kanálem nikdy nejdou.** Bob si klíč skládá jen ze zpráv `L..` od detektorů.
- GUI ukazuje **klíč Alice a klíč Boba zvlášť** a označí, zda se shodují (✔/✘).
- Bob dešifruje **svým** klíčem. Když optika nefunguje, obrázek u Boba zůstane šum. Je tak hned vidět, jestli kvantový kanál opravdu funguje.

---

## 5. Hardware a zapojení

**Jedno Arduino Uno + CNC shield V3** pro Alici i Boba. Drivery A4988/DRV8825: Alice 1/16 mikrokrok (3200 kroků/otáčku), Bob 1/32 (6400). Jiné nastavení jumperů → uprav `KROKU_NA_OTACKU` v `qkd/qkd.ino`.

| co | pin Arduina | kde na shieldu |
|---|---|---|
| HWP **Alice** | STEP D4, DIR D7 | slot **Z** |
| HWP **Bob** | STEP D2, DIR D5 | slot **X** |
| Enable driverů | D8 (LOW = zapnuto) | společný |
| **VALID** (měření platné) | **D3** – přerušení | STEP pin slotu **Y** (slot Y **bez driveru**) |
| Servo shutteru (Alice) | **D9** (PWM) | header X‑ endstop (je u něj 5V a GND) |
| Detektor 0 (bit 0, H/D) | **D10** | header Y‑ endstop |
| Detektor 1 (bit 1, V/A) | **D11** | header Z‑ endstop |

Poznámky:
- Přerušení umí na Uno jen D2 a D3. D2 zabírá Bobův motor, proto VALID jde na D3. Ve slotu Y proto **nesmí být driver**.
- Servo napájej raději z externích 5 V se společnou zemí. Proud serva umí resetovat Arduino.
- Shutter: `SERVO_OTEVRENO = 0°`, `SERVO_ZAVRENO = 90°`. Uprav konstanty v `qkd/qkd.ino` podle mechaniky.
- Detektory musí dávat logické úrovně 0/5 V. VALID jde do HIGH, až jsou výstupy detektorů platné.

---

## 6. Firmware a příkazy Arduina

Nahraj `qkd/qkd.ino` (Arduino IDE, deska *Arduino Uno*).
Komunikace: USB serial **115200 Bd**, každý příkaz končí `\n`, odpověď začíná `OK`.
Po startu Arduino vypíše `QKD`.

**Příkazy Alice**

| příkaz | co dělá | odpověď |
|---|---|---|
| `V` `H` `D` `A` | HWP Alice na 0° / 45° / −22,5° / +22,5° | `OK <poloha v krocích>` |
| `O` / `C` | otevři / zavři shutter (+500 ms na servo) | `OK` |
| `ZERO1` | aktuální natočení HWP Alice se uloží jako 0 = poloha **V** | `OK 0` |
| `k<stupně>` | pootoč HWP Alice o úhel od současné polohy, např. `k15`, `k-2.5` | `OK <poloha>` |

**Příkazy Boba**

| příkaz | co dělá | odpověď |
|---|---|---|
| `+` | HWP Boba na 0° (báze HV) | `OK <poloha>` |
| `X` | HWP Boba na +22,5° (báze DA: D → H, A → V) | `OK <poloha>` |
| `ZERO2` | aktuální natočení HWP Boba se uloží jako 0 | `OK 0` |
| `K<stupně>` | pootoč HWP Boba o úhel, např. `K15` | `OK <poloha>` |
| `d` | ladění: výpis `det0=… det1=… valid=…` | text |

**Zprávy, které Arduino pošle samo (bez příkazu)**

| zpráva | kdy | význam |
|---|---|---|
| `L<det0><det1>` | VALID skočil na 1 | stav detektorů: `L10` = bit 0, `L01` = bit 1, `L00`/`L11` = neplatné. Alice teď může zavřít shutter. |
| `W` | VALID spadl na 0 a uběhlo 100 ms | detektor je v klidu, smí se poslat další qubit |

**Jak se měří:** pin VALID má přerušení na náběžnou hranu (`attachInterrupt(..., RISING)`).
V obsluze přerušení se *okamžitě* přečtou D10 a D11. `loop()` pak pošle `L..`, ale jen když je shutter otevřený (`O`). Se zavřeným shutterem se přerušení ignoruje (šum).
Potom `loop()` hlídá, kdy VALID spadne na 0, počká 100 ms a pošle `W`.

Když `L` nebo `W` nepřijde do **15 s**, Python vypíše chybu („VALID neskočil na 1…“) a protokol se zastaví.

---

### Kamarádčin firmware (také funguje)

Python umí i variantu firmwaru, která místo `L..` a `W` posílá delší texty:

| její firmware | Python to bere jako |
|---|---|
| `COUNT=5 ALICE=H BOB=+ D0=1 D1=0` | `L10` |
| `VALIDITY = 0 - LIGHT OFF` | `W` (Python sám počká 100 ms) |
| `OK BOTH BACK_TO_ZERO` | jen informace, ignoruje se |
| `ERR …` | chyba, vypíše se ve stavovém řádku |

U téhle varianty musíš **po kalibraci poslat `ZERO1` a `ZERO2`**, jinak Arduino odmítne `V H D A + X`.
Ladicí příkaz `d` tam není, místo něj napiš do pole `STATUS`.

---

## 7. Průběh jednoho qubitu (časování)

```
Alice PC:  zvol bit+bázi → [V/H/D/A] ─ "READY" ─►
Bob PC:                    zvol bázi → [+ / X] ─ "BOB_READY" ─►
Alice:     [O] shutter otevřít ─ "OPEN" ─►
Arduino:   VALID↑ → pošle L10 / L01         (Bob čeká max 15 s)
Bob:       přečte bit ─ "MEASURED" ─►
Alice:     [C] shutter zavřít ─ "CLOSED" ─►
Arduino:   VALID↓ + 100 ms → pošle W         (Bob čeká max 15 s)
Bob:       ─ "DARK" ─►   … další qubit
```

Za jedno kolo projde 64 qubitů, pak Alice pošle `V` a Bob `+` (HWP do nuly).
Synchronizační zprávy jdou také veřejným kanálem. Nic tajného neobsahují, jen pořadové číslo qubitu, a GUI je kvůli přehlednosti skrývá.

---

## 8. Sifting, QBER a klíč

Po 64 qubitech:
1. **Bob → veřejně:** svých 64 bází a které qubity zachytil (ztracené = `-`).
2. **Alice → veřejně:** svých 64 bází.
3. Oba si **každý sám** vyberou qubity, kde je platné měření a stejná báze (v průměru ~30).
4. Prvních **16** prosátých bitů je **klíč**. Zbytek (min. 8) jsou **testovací bity**.
   Při méně než 8 testovacích bitech se kolo opakuje.
5. **Alice → veřejně:** testovací bity. **Bob** je porovná se svými a pošle **počet chyb**.
6. QBER = chyby / testovací bity.
   - **≤ 11 %** → verdikt OK, klíč se použije.
   - **> 11 %** → FAIL (pravděpodobně Eve), nové kolo.

Klíčové bity se nikdy nezveřejní. Zveřejněné testovací bity se do klíče nepoužijí.

---

## 9. Šifrování obrázku

1. Obrázek se zmenší na zvolenou velikost (8–256 px) a převede do režimu:
   - **1 bit** černobílý (nejméně dat),
   - **8 bit** odstíny šedi,
   - **24 bit** barevné RGB.
2. Data se zašifrují **XOR se 16bitovým klíčem**: každý pár bajtů se XORuje s horním a dolním bajtem klíče (`pc/qcrypt.py`, `xor16`).
   Šifrování a dešifrování je stejná operace.
3. Zašifrovaná data jdou veřejným kanálem zhruba ve 100 kouscích (aspoň 32 bajtů). Bob dešifruje průběžně, takže je vidět, jak obrázek přibývá.

> Pozn.: opakovaný 16bitový klíč není bezpečná šifra. U velkých ploch stejné barvy je obrys vidět i v zašifrované verzi.
> Pro demonstraci je to výhoda: je názorně vidět rozdíl mezi správným a špatným klíčem.
> Skutečná QKD by vyrobila tolik bitů klíče, kolik je dat (one-time pad).

---

## 10. Instalace a spuštění GUI

### Nejrychleji (Windows, jeden příkaz)

Otevři **cmd** a vlož tenhle příkaz:

```
curl -L -o qkd.zip https://github.com/tomasraketak/quantumcryptography/archive/refs/heads/claude/cool-einstein-p05cgt.zip && tar -xf qkd.zip && cd quantumcryptography-claude-cool-einstein-p05cgt && start.bat
```

Udělá tohle:
1. stáhne celý projekt jako ZIP a rozbalí ho;
2. když chybí Python, nainstaluje ho přes `winget`;
3. nainstaluje nebo aktualizuje všechny knihovny (`pyserial`, `numpy`, `Pillow`, `matplotlib`);
4. otevře GUI (`pc/qkd_gui.py`), které vše řídí.

Když už projekt staženy máš, stačí ve složce projektu spustit (dvojklikem nebo v cmd):

```
start.bat
```

`start.bat` při každém spuštění aktualizuje knihovny. Když je nainstalovaný git, stáhne i nejnovější kód (`git pull`).

> Když se Python teprve nainstaloval a GUI nenaběhne, zavři cmd a spusť `start.bat` znovu.
> Nové okno cmd už Python najde.

### Ručně (jakýkoli systém)

Potřebuješ Python 3.9+ s tkinter (Windows a macOS ho mají; na Linuxu `sudo apt install python3-tk`).

```
pip install -r pc/requirements.txt      # pyserial, numpy, Pillow, matplotlib
python pc/qkd_gui.py
```

1. Připoj Arduino USB a v GUI vyber jeho **port** (např. COM3 nebo `/dev/ttyACM0`).
2. Klikni **Připojit**. Po otevření portu se Arduino restartuje, GUI čeká ~2,5 s.
3. Bez hardwaru zaškrtni **Simulace** (volitelně **Eve poslouchá**) a klikni Připojit.
4. Klikni **START**. Běží kola, dokud nevznikne klíč s QBER ≤ 11 %.
5. Nahraj obrázek, zvol velikost a režim a klikni **Alice zašifruje a pošle**.

---

## 11. Popis GUI

- **Horní řádek:** port Arduina, Simulace, Eve poslouchá, Připojit, START, **⏭ Další kolo**, **⏻ HWP na 0 (vypnutí)**.
- **Pauza mezi koly:** když kolo nevyjde (QBER > 11 % nebo málo bitů), program se zastaví. Tabulka zůstane, takže si můžeš prohlédnout, které bity byly dobře a které špatně. Další kolo se spustí až tlačítkem **⏭ Další kolo**.
- **Ruční ovládání:** tlačítka pro Alici (`V H D A O C ZERO1`) a Boba (`+ X ZERO2 d`). Do pole se píše `k15` (Alice) nebo `K15` (Bob) a Enter. Slouží ke kalibraci a testu.
- **Žlutý pruh:** vysvětluje, co se právě děje.
- **Tabulka qubitů:** číslo, Alicina báze/bit/úhel HWP/polarizace, Bobova báze/úhel HWP/naměřená hodnota, shoda bází a použití bitu. Barvy:
  - 🟩 zelená = klíč,
  - 🟦 modrá = test,
  - 🟥 červená = chyba,
  - ⬜ šedá = zahozeno nebo ztraceno.
- **Pravý panel:** číslo kola, počet prosátých bitů, stupnice **QBER** (značky 11 % a 25 %), **klíč Alice** a **klíč Boba** (✔/✘) a **veřejný kanál**.
- **Obrázek:** 4 náhledy:
  - originál (Alice),
  - zašifrovaný u Alice,
  - zašifrovaný přijatý Bobem,
  - dešifrovaný Bobovým klíčem.

  Progress bar ukazuje přenos.

---

## 12. Kalibrace

1. Zapni laser a otevři shutter (ručně `O`).
2. Bob: ručně `+`, Alice: pootáčej HWP příkazy `k2` / `k-2` (jemněji `k0.5`), dokud nesvítí čistě detektor 1 (`d` ukáže stav). Pak dej **`ZERO1`**.
3. Stejně nastav Bobovu HWP příkazy `K…`, aby pro Alicino `V` svítil čistě detektor 1. Pak dej **`ZERO2`**.
4. Ověř:
   - Alice `H` → detektor 0;
   - Alice `D` + Bob `A` → detektor 0;
   - Alice `A` + Bob `A` → detektor 1.
5. Před vypnutím klikni na **⏻ HWP na 0 (vypnutí)** (pošle `V` Alici a `+` Bobovi), aby po zapnutí začínaly z nuly. Arduino si polohu nepamatuje, po zapnutí bere aktuální polohu jako 0.

Když nesedí směr otáčení nebo počet kroků, uprav `KROKU_NA_OTACKU = {Alice, Bob}` (200 kroků × mikrokrokování; 1/16 = 3200, 1/32 = 6400) nebo prohoď vodiče cívky.

---

## 13. Simulace a Eve

`SimOptics` v `pc/qkd_core.py` nahradí Arduino a fyziku. Při `O` pošle `L..`, při `C` pošle `W`, stejně jako skutečný hardware. Pravděpodobnost bitu 1 je cos²(2·HWP_Bob − polarizace).
Přidává 2 % šumu a 5 % ztrát.

Se zaškrtnutým **Eve poslouchá** Eve každý qubit změří v náhodné bázi a pošle dál nový.

Výsledky simulace:
- **bez Eve:** QBER ~0–5 %, klíče se shodují, obrázek se dešifruje;
- **s Eve:** QBER ~20–30 %, verdikt FAIL, kola se opakují.

---

## 14. Struktura souborů

```
qkd/qkd.ino         firmware jednoho Arduina pro Alici i Boba
pc/qkd_core.py      protokol BB84: Alice, Bob, PublicChannel, SerialDevice, SimOptics
pc/qkd_gui.py       GUI (tkinter) – jen zobrazuje události
pc/qcrypt.py        komprese obrázku a XOR šifra
pc/requirements.txt závislosti
```

---

## 15. Řešení problémů

| problém | řešení |
|---|---|
| „žádná odpověď na …“ | špatný port, nebo je otevřený Serial Monitor (port může mít jen jeden program) |
| „VALID neskočil na 1 do 15 s“ | VALID nepřichází: zkontroluj D3, slot Y bez driveru, laser a shutter, příkaz `d` |
| QBER vysoký i bez Eve | špatná kalibrace HWP (kap. 12), odrazy, okolní světlo |
| motor se netočí | EN musí být LOW, napájení shieldu 12 V, drivery ve slotech X a Z |
| servo resetuje Arduino | napájej servo zvlášť, se společnou zemí |
| „VALID nespadl na 0 do 15 s“ | detektor stále hlásí světlo: zavírá se shutter? |
| Linux: chyba přístupu k portu | `sudo usermod -a -G dialout $USER` a znovu se přihlásit |
