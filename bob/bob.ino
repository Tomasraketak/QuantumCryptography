// =====================================================================
//  BOB - prijimac BB84 (Arduino Uno + CNC shield)
//  HWP (krokac na ose X) -> polarizacni delic -> detektor 0 / detektor 1
//
//  Arduino jen poslouchá příkazy z PC (USB, 115200, konec řádku \n).
//
//  Příkazy:                               odpověď
//    V H D A   natoč HWP (jako u Alice)    OK
//              báze HV = V (0°), báze DA = A (+22.5°: D -> H, A -> V)
//    M         změř: čeká na VALID (přerušení), přečte detektory
//                                          OK 0 / OK 1 / OK - (nic)
//    W         počkej, až VALID = 0, pak 100 ms   OK
//    ZERO      aktuální natočení = 0 (= poloha V)   OK
//    k<st>     pootoč HWP o <st> stupňů vůči
//              současné poloze, např. k15, k-2.5 (kalibrace)   OK <poloha>
//    d         stav pinů                   det0=.. det1=.. valid=..
// =====================================================================
#define STEP_PIN  2    // krokac X - krok
#define DIR_PIN   5    // krokac X - smer
#define EN_PIN    8    // LOW = driver zapnuty
#define VALID_PIN 3    // jen D2 a D3 umi preruseni (D3 = Y.STEP, bez Y driveru)
#define DET0_PIN  7    // detektor 0 -> bit 0 (H / D)
#define DET1_PIN  6    // detektor 1 -> bit 1 (V / A)

const long KROKU_NA_OTACKU = 3200;
const unsigned long MAX_CEKANI = 2000;   // ms, kdyz VALID neprijde = ztrata

long poloha = 0;

// ----- preruseni: VALID prave sel do HIGH -----
volatile bool zmereno = false;
volatile byte det0, det1;
void onValid() {
  det0 = digitalRead(DET0_PIN);   // detektory cteme hned v okamziku platnosti
  det1 = digitalRead(DET1_PIN);
  zmereno = true;
}

void krokuj(long kroky) {
  digitalWrite(DIR_PIN, kroky > 0 ? HIGH : LOW);
  for (long k = 0; k < abs(kroky); k++) {
    digitalWrite(STEP_PIN, HIGH); delayMicroseconds(600);
    digitalWrite(STEP_PIN, LOW);  delayMicroseconds(600);
  }
  poloha += kroky;
}

void natocHWP(float stupne) {
  krokuj(lround(stupne * KROKU_NA_OTACKU / 360) - poloha);
}

void zmer() {
  unsigned long start = millis();
  while (!zmereno && millis() - start < MAX_CEKANI) { }   // cekame na preruseni
  if (zmereno && det0 != det1)          // svitit ma prave jeden detektor
    Serial.println(det1 ? "OK 1" : "OK 0");
  else
    Serial.println("OK -");
}

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT); digitalWrite(EN_PIN, LOW);
  pinMode(DET0_PIN, INPUT);
  pinMode(DET1_PIN, INPUT);
  pinMode(VALID_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(VALID_PIN), onValid, RISING);
  Serial.begin(115200);
  Serial.println("BOB");
}

void loop() {
  if (!Serial.available()) return;
  String p = Serial.readStringUntil('\n');
  p.trim();

  if (p == "M") { zmer(); return; }
  if (p == "W") {
    while (digitalRead(VALID_PIN) == HIGH) { }   // detektor jeste sviti
    delay(100);
    zmereno = false;                             // pripraveno na dalsi qubit
    Serial.println("OK");
    return;
  }
  if (p == "d") {
    Serial.print("det0="); Serial.print(digitalRead(DET0_PIN));
    Serial.print(" det1="); Serial.print(digitalRead(DET1_PIN));
    Serial.print(" valid="); Serial.println(digitalRead(VALID_PIN));
    return;
  }

  if      (p == "V") natocHWP(0);
  else if (p == "H") natocHWP(45);
  else if (p == "D") natocHWP(-22.5);
  else if (p == "A") natocHWP(22.5);
  else if (p == "ZERO") poloha = 0;
  else if (p.startsWith("k")) krokuj(lround(p.substring(1).toFloat() * KROKU_NA_OTACKU / 360));
  else { Serial.println("? " + p); return; }

  zmereno = false;      // po natoceni zahodime stary zablesk
  Serial.print("OK ");
  Serial.println(poloha);
}
