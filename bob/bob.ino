// =====================================================================
//  BOB - prijimac BB84  (Arduino Uno + CNC shield)
//
//  HWP (krokac na ose X) -> polarizacni delic -> detektor 1 / detektor 2
//  baze HV: HWP 0°,  baze DA: HWP 22.5° (otoci D na H)
//  detektor 1 = bit 0 (H/D),  detektor 2 = bit 1 (V/A)
//  VALID = detektor ma platne mereni -> preruseni na D3
//
//  USB (115200): vypisy pro cloveka i pro GUI, prikaz d = stav detektoru
//  Linka k Alici: SoftwareSerial A0 = RX, A1 = TX (zapojit krizem!)
// =====================================================================
#include <SoftwareSerial.h>

// ----- piny -----
#define STEP_PIN  2    // krokac X - krok
#define DIR_PIN   5    // krokac X - smer
#define EN_PIN    8    // LOW = driver zapnuty
#define VALID_PIN 3    // Y.STEP (bez Y driveru) - jen D2/D3 umi preruseni
#define DET1_PIN  9    // X-limit
#define DET2_PIN  10   // Y-limit
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
volatile byte det1, det2;
void onValid() {
  det1 = digitalRead(DET1_PIN);   // detektory cteme hned v okamziku platnosti
  det2 = digitalRead(DET2_PIN);
  mereniHotovo = true;
}

// ================= pomocne funkce =================
void natocHWP(float stupne) {
  long cil = stupne * KROKU_NA_OTACKU / 360;
  long kroky = cil - poloha;
  digitalWrite(DIR_PIN, kroky > 0 ? HIGH : LOW);
  for (long k = 0; k < abs(kroky); k++) {
    digitalWrite(STEP_PIN, HIGH); delayMicroseconds(600);
    digitalWrite(STEP_PIN, LOW);  delayMicroseconds(600);
  }
  poloha = cil;
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

// ================= mereni jednoho qubitu =================
// Alice uz otevrela shutter. Cekame na preruseni od VALID.
void zmer(int i) {
  unsigned long start = millis();
  while (!mereniHotovo && millis() - start < MAX_CEKANI) { }

  platne[i] = mereniHotovo && (det1 != det2);   // svitit ma prave jeden detektor
  bit[i] = (det2 == HIGH) ? 1 : 0;
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
  pinMode(DET1_PIN, INPUT);
  pinMode(DET2_PIN, INPUT);
  pinMode(VALID_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(VALID_PIN), onValid, RISING);
  Serial.begin(115200);
  link.begin(9600);
  randomSeed(analogRead(A2) * 31 + analogRead(A3) + micros());
  Serial.println(F("BOB pripraven, cekam na Alici. d = stav detektoru"));
}

void loop() {
  if (Serial.available() && Serial.read() == 'd') {
    Serial.print(F("det1=")); Serial.print(digitalRead(DET1_PIN));
    Serial.print(F(" det2=")); Serial.print(digitalRead(DET2_PIN));
    Serial.print(F(" valid=")); Serial.println(digitalRead(VALID_PIN));
  }
  if (link.available()) {
    prectiRadek();
    zpracujZpravu();
  }
}
