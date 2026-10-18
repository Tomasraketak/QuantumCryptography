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
6. [Firmware a příkazy Arduin](#6-firmware-a-příkazy-arduin)
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
- **báze HV:** HWP 0° (`V`). H jde na detektor 0, V na detektor 1.
- **báze DA:** HWP +22,5° (`A`). Otočí D na H (detektor 0) a A na V (detektor 1).
  H a V se otočí na diagonálu, takže PBS je rozdělí náhodně 50 : 50.

Pravidlo: **detektor 0 = bit 0, detektor 1 = bit 1.**

Když laser není potřeba (konec kola, před vypnutím), obě HWP jdou do **nuly** (vertikální polarizace).

---

## 3. Architektura: kdo co dělá

```
            USB                                      USB
 ┌────────────────┐   ┌─────────────── PC (Python) ───────────────┐   ┌────────────────┐
 │ Arduino ALICE  │◄──┤  Alice (vlákno)  ◄─ PublicChannel ─►  Bob  ├──►│ Arduino BOB    │
 │ servo + HWP    │   │  soukromé:         (vše se vypisuje  soukr.│   │ HWP + detektory│
 └───────┬────────┘   │  bity, báze,       v GUI)            báze, │   └───────▲────────┘
         │            │  klíč, obrázek                      měření,│           │
         │            │                                     klíč   │           │
         │            └────────────────────────────────────────────┘           │
         └──────────────────────── laser (kvantový kanál) ─────────────────────┘
```

- **PC** dělá všechno chytré: náhodu, sifting, QBER, klíč, šifrování a GUI.
- **Arduina** jsou „hloupá“. Dostávají jednoduché textové příkazy (natoč HWP, otevři shutter, změř) a odpovídají `OK …`.
- Mezi Arduiny **není žádný drát**. Jediné, co jde od Alice k Bobovi fyzicky, je laserový paprsek.

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
- **Klíč ani nezašifrovaný obrázek kanálem nikdy nejdou.** Bob si klíč skládá jen z odpovědí svého Arduina (detektorů).
- GUI ukazuje **klíč Alice a klíč Boba zvlášť** a označí, zda se shodují (✔/✘).
- Bob dešifruje **svým** klíčem. Když optika nefunguje, obrázek u Boba zůstane šum. Je tak hned vidět, jestli kvantový kanál opravdu funguje.

---

## 5. Hardware a zapojení

Obě Arduina: **Arduino Uno + CNC shield V3**. Krokový motor je na ose **X** (driver A4988/DRV8825, 1/16 mikrokrok → 3200 kroků/otáčku).

| | Alice | Bob |
|---|---|---|
| Krokáč HWP | STEP D2, DIR D5, EN D8 (LOW = zapnuto) | STEP D2, DIR D5, EN D8 |
| Servo shutteru | D9 (na shieldu pin X limit/endstop) | – |
| Detektor 0 (bit 0, H/D) | – | **D7** |
| Detektor 1 (bit 1, V/A) | – | **D6** |
| VALID (měření platné) | – | **D3** – přerušení |

Poznámky:
- **D3 je na CNC shieldu Y.STEP.** V Y slotu proto **nesmí být driver**. Přerušení umí na Uno jen D2 a D3, a D2 už používá osa X.
- Servo napájej raději z externích 5 V se společnou zemí. Proud serva umí resetovat Arduino.
- Shutter: `SERVO_OTEVRENO = 90°`, `SERVO_ZAVRENO = 110°` (o 20° dál). Uprav konstanty v `alice/alice.ino` podle mechaniky.
- Detektory musí dávat logické úrovně 0/5 V. VALID jde do HIGH, až jsou výstupy detektorů platné.

---

## 6. Firmware a příkazy Arduin

Nahraj `alice/alice.ino` do Alice a `bob/bob.ino` do Boba (Arduino IDE, deska *Arduino Uno*).
Komunikace: USB serial **115200 Bd**, každý příkaz končí `\n`, odpověď začíná `OK`.
Po startu Arduino vypíše `ALICE` nebo `BOB`.

| příkaz | Alice | Bob | odpověď |
|---|---|---|---|
| `V` `H` `D` `A` | HWP na 0° / 45° / −22,5° / +22,5° | stejné (báze HV = `V`, báze DA = `A`) | `OK <poloha v krocích>` |
| `O` / `C` | otevři / zavři shutter (+250 ms na servo) | – | `OK …` |
| `M` | – | čeká na VALID↑ (max 2 s) a přečte detektory | `OK 0`, `OK 1`, nebo `OK -` (nic / oba / timeout) |
| `W` | – | čeká, až VALID = 0, pak ještě 100 ms | `OK` |
| `0` | HWP do nuly (vertikála), třeba před vypnutím | stejné | `OK 0` |
| `ZERO` | aktuální poloha se prohlásí za nulu | stejné | `OK 0` |
| `a <stupně>` | natoč HWP na úhel, např. `a 22.5` | stejné | `OK <poloha>` |
| `j <kroky>` | posuň o kroky, např. `j -10` | stejné | `OK <poloha>` |
| `d` | – | výpis `det0=… det1=… valid=…` | text |
| jiné | – | – | `? <příkaz>` |

Příkazy lze zkoušet i ručně v Serial Monitoru (115200, „Newline“).

**Jak Bob měří:** pin VALID má přerušení na náběžnou hranu (`attachInterrupt(..., RISING)`).
V obsluze přerušení se *okamžitě* přečtou D7 a D6 a nastaví se příznak `zmereno`.
Příkaz `M` jen počká na příznak. Platné měření je, když svítí **právě jeden** detektor.

---

## 7. Průběh jednoho qubitu (časování)

```
Alice PC:  zvol bit+bázi → [V/H/D/A] ─ "READY" ─►
Bob PC:                    zvol bázi → [V/A] ─ "BOB_READY" ─►
Alice:     [O] shutter otevřít ─ "OPEN" ─►
Bob:       [M] čekej VALID↑ → přečti D7/D6 ─ "MEASURED" ─►
Alice:     [C] shutter zavřít ─ "CLOSED" ─►
Bob:       [W] čekej VALID↓ + 100 ms ─ "DARK" ─►   … další qubit
```

Za jedno kolo projde 64 qubitů, pak obě strany pošlou `0` (HWP do nuly).
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

1. Obrázek se zmenší na zvolenou velikost (8–64 px) a převede do režimu:
   - **1 bit** černobílý (nejméně dat),
   - **8 bit** odstíny šedi,
   - **24 bit** barevné RGB.
2. Data se zašifrují **XOR se 16bitovým klíčem**: každý pár bajtů se XORuje s horním a dolním bajtem klíče (`pc/qcrypt.py`, `xor16`).
   Šifrování a dešifrování je stejná operace.
3. Zašifrovaná data jdou veřejným kanálem po 32 bajtech. Bob dešifruje průběžně, takže je vidět, jak obrázek přibývá.

> Pozn.: opakovaný 16bitový klíč není bezpečná šifra. U velkých ploch stejné barvy je obrys vidět i v zašifrované verzi.
> Pro demonstraci je to výhoda: je názorně vidět rozdíl mezi správným a špatným klíčem.
> Skutečná QKD by vyrobila tolik bitů klíče, kolik je dat (one-time pad).

---

## 10. Instalace a spuštění GUI

Potřebuješ Python 3.9+ s tkinter (Windows a macOS ho mají; na Linuxu `sudo apt install python3-tk`).

```
pip install -r pc/requirements.txt      # pyserial, numpy, Pillow, matplotlib
python pc/qkd_gui.py
```

1. Připoj obě Arduina USB. V GUI vyber port **Alice** a port **Boba** (např. COM3 / COM4, `/dev/ttyACM0`, `/dev/ttyACM1`).
2. Klikni **Připojit**. Po otevření portu se Arduino restartuje, GUI čeká ~2,5 s.
3. Bez hardwaru zaškrtni **Simulace** (volitelně **Eve poslouchá**) a klikni Připojit.
4. Klikni **START**. Běží kola, dokud nevznikne klíč s QBER ≤ 11 %.
5. Nahraj obrázek, zvol velikost a režim a klikni **Alice zašifruje a pošle**.

---

## 11. Popis GUI

- **Horní řádek:** porty, Simulace, Eve poslouchá, Připojit, START.
- **Ruční ovládání:** tlačítka pro Alici (`V H D A O C 0 ZERO`) a Boba (`V H D A M 0 ZERO d`) a pole pro `a …` / `j …` (Enter). Slouží ke kalibraci a testu.
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
2. Bob: ručně `V`, Alice: posouvej HWP příkazy `j 5` / `j -5`, dokud detektor 1 nesvítí nejsilněji (`d` ukáže stav). Pak dej Alici **`ZERO`**.
3. Stejně nastav Bobovu HWP, aby pro Alicino `V` svítil čistě detektor 1. Pak dej Bobovi **`ZERO`**.
4. Ověř:
   - Alice `H` → detektor 0;
   - Alice `D` + Bob `A` → detektor 0;
   - Alice `A` + Bob `A` → detektor 1.
5. Před vypnutím pošli oběma **`0`**, aby po zapnutí začínaly z nuly. Arduino si polohu nepamatuje, po zapnutí bere aktuální polohu jako 0.

Když nesedí směr otáčení nebo počet kroků, uprav `KROKU_NA_OTACKU` (3200 = 200 kroků × 16 mikrokroků) nebo prohoď vodiče cívky.

---

## 13. Simulace a Eve

`SimOptics` v `pc/qkd_core.py` nahradí obě Arduina a fyziku. Pravděpodobnost bitu 1 je cos²(2·HWP_Bob − polarizace).
Přidává 2 % šumu a 5 % ztrát.

Se zaškrtnutým **Eve poslouchá** Eve každý qubit změří v náhodné bázi a pošle dál nový.

Výsledky simulace:
- **bez Eve:** QBER ~0–5 %, klíče se shodují, obrázek se dešifruje;
- **s Eve:** QBER ~20–30 %, verdikt FAIL, kola se opakují.

---

## 14. Struktura souborů

```
alice/alice.ino     firmware Alice (servo + HWP, příkazový interpret)
bob/bob.ino         firmware Boba (HWP + detektory s přerušením)
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
| Bob vrací stále `OK -` | VALID nepřichází: zkontroluj D3, Y slot bez driveru, příkaz `d` |
| QBER vysoký i bez Eve | špatná kalibrace HWP (kap. 12), odrazy, okolní světlo |
| motor se netočí | EN musí být LOW, napájení shieldu 12 V, driver v X slotu |
| servo resetuje Arduino | napájej servo zvlášť, se společnou zemí |
| `W` se zasekne | VALID zůstává HIGH: detektor stále hlásí světlo, zkontroluj shutter |
| Linux: chyba přístupu k portu | `sudo usermod -a -G dialout $USER` a znovu se přihlásit |
