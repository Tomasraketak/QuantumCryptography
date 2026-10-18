// =====================================================================
//  BOB - prijimac BB84  (Arduino Uno + CNC shield)
//
//  HWP (krokac na ose X) -> polarizacni delic -> detektor 0 / detektor 1
//  baze HV: HWP 0°,  baze DA: HWP 22.5° (otoci D na H a A na V)
//  detektor 0 = bit 0 (H/D),  detektor 1 = bit 1 (V/A)
//  Kdyz se nemeri, stoji HWP na 0°.
//  VALID = detektor ma platne mereni -> preruseni na D3
//
//  USB (115200): vypisy pro cloveka i pro GUI, prikazy viz loop()
//  Linka k Alici: SoftwareSerial A0 = RX, A1 = TX (zapojit krizem!)
// =====================================================================
#include <SoftwareSerial.h>

// ----- piny -----
#define STEP_PIN  2    // krokac X - krok
#define DIR_PIN   5    // krokac X - smer
#define EN_PIN    8    // LOW = driver zapnuty
#define VALID_PIN 3    // Y.STEP (bez Y driveru) - jen D2/D3 umi preruseni
#define DET0_PIN  7    // detektor 0 (H) -> bit 0
#define DET1_PIN  6    // detektor 1 (V) -> bit 1
SoftwareSerial link(A0, A1);

// ----- nastaveni -----
const long KROKU_NA_OTACKU = 3200;
const float UHEL_BAZE[2] = { 0, 22.5 };   // HV, DA
const int N = 64, KLIC = 16;
const unsigned long MAX_CEKANI = 2000;    // ms; kdyz VALID neprijde = ztrata

// ----- data jednoho kola -----
byte baze[N], bit[N], platne[N];
byte aliceBaze[N];
long poloha = 0;
char radek[80];

// ----- preruseni: VALID prave sel do HIGH -----
volatile bool mereniHotovo = false;
volatile byte det0, det1;
void onValid() {
  det0 = digitalRead(DET0_PIN);   // detektory cteme hned v okamziku platnosti
  det1 = digitalRead(DET1_PIN);
  mereniHotovo = true;
}

// ================= pomocne funkce =================
// Otoci krokacem o dany pocet kroku (zaporne = opacnym smerem).
void krokuj(long kroky) {
  digitalWrite(DIR_PIN, kroky > 0 ? HIGH : LOW);
  for (long k = 0; k < abs(kroky); k++) {
    digitalWrite(STEP_PIN, HIGH); delayMicroseconds(600);
    digitalWrite(STEP_PIN, LOW);  delayMicroseconds(600);
  }
  poloha += kroky;
}

// Natoci HWP na uhel ve stupnich vuci nule.
void natocHWP(float stupne) {
  krokuj(lround(stupne * KROKU_NA_OTACKU / 360) - poloha);
}

// Precte jeden radek z linky (ceka libovolne dlouho).
void prectiRadek() {
  int n = 0;
  while (true) {
    if (!link.available()) continue;
    char c = link.read();
    if (c == '\n') { radek[n] = 0; if (n > 0) return; }
    else if (c != '\r' && n < 79) radek[n++] = c;
  }
}

void posliBity(const char *nazev, byte *b) {
  link.print(nazev); link.print(' ');
  for (int i = 0; i < N; i++) link.print(b[i]);
  link.println();
}

// ================= kalibrace (prikazy z USB) =================
//   a <stupne>  natoc HWP na uhel (napr. a 22.5 nebo a -22.5)
//   j <kroky>   posun o kroky (napr. j 10 nebo j -10)
//   z           aktualni poloha = nula (ZERO)
//   0           HWP do nuly (priprava na vypnuti)
void kalibrace(String cmd) {
  if (cmd.startsWith("a")) natocHWP(cmd.substring(1).toFloat());
  if (cmd.startsWith("j")) krokuj(cmd.substring(1).toInt());
  if (cmd == "z") poloha = 0;
  if (cmd == "0") natocHWP(0);
  Serial.print(F("HWP poloha: ")); Serial.print(poloha); Serial.print(F(" kroku = "));
  Serial.print(poloha * 360.0 / KROKU_NA_OTACKU); Serial.println(F(" st."));
}

// ================= mereni jednoho qubitu =================
// Alice uz otevrela shutter. Cekame na preruseni od VALID.
void zmer(int i) {
  unsigned long start = millis();
  while (!mereniHotovo && millis() - start < MAX_CEKANI) { }

  platne[i] = mereniHotovo && (det0 != det1);   // svitit ma prave jeden detektor
  bit[i] = (det1 == HIGH) ? 1 : 0;
  mereniHotovo = false;

  Serial.print(F("#B ")); Serial.print(i); Serial.print(' ');
  Serial.print(baze[i]); Serial.print(' ');
  if (platne[i]) Serial.println(bit[i]); else Serial.println('-');
}

// ================= protokol: Bob jen odpovida Alici =================
void zpracujZpravu() {
  static int i = 0;          // cislo aktualniho qubitu
  static int pocetProsetych = 0;

  if (radek[0] == 'R') {                        // novy qubit
    i = atoi(radek + 2);
    baze[i] = random(2);
    natocHWP(UHEL_BAZE[baze[i]]);
    mereniHotovo = false;
    link.println(F("K"));
  }
  else if (radek[0] == 'P') {                   // laser sviti -> merit
    zmer(i);
    link.println(F("M"));
  }
  else if (radek[0] == 'Z') {                   // shutter zavreny
    while (digitalRead(VALID_PIN) == HIGH) { }  // pockej, az detektor zhasne
    delay(100);
    mereniHotovo = false;
    link.println(F("D"));
  }
  else if (radek[0] == 'S') {                   // sifting: posli sve baze
    natocHWP(0);                                // merit uz nebudeme -> HWP do nuly
    posliBity("BB", baze);
    posliBity("BV", platne);
  }
  else if (strncmp(radek, "AB", 2) == 0) {      // baze Alice -> prosivani
    for (int k = 0; k < N; k++) aliceBaze[k] = radek[3 + k] - '0';
    pocetProsetych = 0;
    for (int k = 0; k < N; k++)
      if (platne[k] && baze[k] == aliceBaze[k]) bit[pocetProsetych++] = bit[k];
  }
  else if (strncmp(radek, "TB", 2) == 0) {      // testovaci bity Alice
    int test = pocetProsetych - KLIC, chyby = 0;
    for (int k = 0; k < test; k++)
      if (radek[3 + k] - '0' != bit[KLIC + k]) chyby++;
    link.print(F("Q ")); link.println(chyby);
    Serial.print(F("QBER:")); Serial.println(chyby / (float)test, 4);
  }
  else if (strcmp(radek, "OK") == 0) {          // klic plati
    uint16_t klic = 0;
    for (int k = 0; k < KLIC; k++) klic = klic * 2 + bit[k];
    Serial.print(F("KEY:"));
    if (klic < 0x1000) Serial.print('0');
    if (klic < 0x100)  Serial.print('0');
    if (klic < 0x10)   Serial.print('0');
    Serial.println(klic, HEX);
    while (true)                                // prenos obrazku: linka -> PC
      if (link.available()) Serial.write(link.read());
  }
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
  link.begin(9600);
  randomSeed(analogRead(A2) * 31 + analogRead(A3) + micros());
  Serial.println(F("BOB pripraven, cekam na Alici. d = stav detektoru,"));
  Serial.println(F("  a <st> / j <kroky> / z = nula / 0 = HWP do nuly, h/x = baze HV/DA"));
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "d") {
      Serial.print(F("det0=")); Serial.print(digitalRead(DET0_PIN));
      Serial.print(F(" det1=")); Serial.print(digitalRead(DET1_PIN));
      Serial.print(F(" valid=")); Serial.println(digitalRead(VALID_PIN));
    }
    else if (cmd == "h") natocHWP(UHEL_BAZE[0]);
    else if (cmd == "x") natocHWP(UHEL_BAZE[1]);
    else kalibrace(cmd);
  }
  if (link.available()) {
    prectiRadek();
    zpracujZpravu();
  }
}
