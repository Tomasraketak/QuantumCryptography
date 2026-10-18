# QKD demonstrátor (BB84) – Arduino Uno + PC

PC (Python) řídí celý protokol: náhodně volí bity a báze, dělá sifting, počítá QBER, skládá klíč a šifruje obrázek. Obě Arduina (Alice, Bob) jsou připojená USB do jednoho PC a jen vykonávají jednoduché příkazy. Mezi Arduiny žádná linka není.

**Bez podvádění:** v Pythonu jsou Alice a Bob oddělené objekty (`pc/qkd_core.py`, třídy `Alice` a `Bob`), každý ve svém vlákně a se svými soukromými daty. Spojuje je jen `PublicChannel`, jehož obsah GUI vypisuje („vidí i Eve“): báze, které měření se zachytila, testovací bity, počet chyb a šifrovaný obrázek. Bob si klíč skládá jen ze svých detektorů. Když kvantový kanál nefunguje, Bob má jiný klíč a obrázek se mu nerozšifruje.

## Zapojení (CNC shield, osa X)
| | Alice | Bob |
|---|---|---|
| Krokáč HWP | STEP D2, DIR D5, EN D8 | STEP D2, DIR D5, EN D8 |
| Servo shutter | D9 | – |
| Detektory | – | D7 detektor 0 (H/D = bit 0), D6 detektor 1 (V/A = bit 1), D3 VALID (přerušení; pin Y.STEP, v Y slotu nesmí být driver) |

## Příkazy Arduin (USB 115200, konec řádku `\n`, odpověď `OK …`)
| příkaz | Alice | Bob |
|---|---|---|
| `V` `H` `D` `A` | HWP na 0° / 45° / −22,5° / +22,5° | stejné (báze HV = `V`, báze DA = `A`) |
| `O` / `C` | shutter otevřít / zavřít | – |
| `M` | – | čeká na VALID↑ (přerušení, max 2 s), přečte detektory → `OK 0` / `OK 1` / `OK -` |
| `W` | – | čeká, až VALID = 0, pak 100 ms → `OK` |
| `0` | HWP do nuly (vertikální), i před vypnutím | stejné |
| `ZERO` | aktuální poloha = nula | stejné |
| `a 22.5`, `j -10` | kalibrace: úhel / posun o kroky | stejné |
| `d` | – | stav det0, det1, VALID |

## Jeden qubit
1. Alice zvolí náhodně bit a bázi a natočí HWP. Pošle veřejně „připraveno“.
2. Bob zvolí náhodně bázi a natočí HWP.
3. Alice `O`, Bob `M` (čeká na VALID, přečte detektory), Alice `C`, Bob `W` (VALID = 0 + 100 ms).

Po 64 qubitech jdou obě HWP na 0. Následuje sifting přes veřejný kanál: Bob → báze a platnost, Alice → báze, Alice → testovací bity, Bob → počet chyb. QBER > 11 % ⇒ odposlech (Eve ≈ 25 %), kolo se opakuje. Prvních 16 prosetých bitů je klíč, každý si ho složí sám.

## GUI
```
pip install -r pc/requirements.txt
python pc/qkd_gui.py
```
1. Vyber porty → **Připojit** (nebo zaškrtni **Simulace**, případně **Eve poslouchá**).
2. Řádek **Ručně Alice/Bob**: tlačítka V H D A O C M 0 ZERO d, pole pro `a …` / `j …` (kalibrace).
3. **START** – tabulka qubitů, veřejný kanál, QBER, klíč Alice a klíč Boba vedle sebe.
4. **Nahrát obrázek**, zvol rozlišení a barevnou hloubku, **Alice zašifruje a pošle**. Bob dešifruje svým klíčem.

Soubory: `pc/qkd_gui.py` (okno), `pc/qkd_core.py` (Alice, Bob, veřejný kanál, Arduina, simulace), `pc/qcrypt.py` (komprese, XOR šifrování).
