// =====================================================================
//  ALICE - vysilac BB84  (Arduino Uno + CNC shield)
//
//  laser -> shutter (servo) -> polarizator H -> HWP (krokac na ose X)
//
//  bit 0 = H nebo D,  bit 1 = V nebo A
//  HWP otoci polarizaci o dvojnasobek sveho uhlu:
//     H = 0°,  V = 45°,  D = 22.5°,  A = 67.5°
//
//  USB (115200): vypisy pro cloveka i pro GUI, prikazy g / o / c
//  Linka k Bobovi: SoftwareSerial A0 = RX, A1 = TX (zapojit krizem!)
// =====================================================================
#include <SoftwareSerial.h>
#include <Servo.h>

// ----- piny -----
#define STEP_PIN  2    // krokac X - krok
#define DIR_PIN   5    // krokac X - smer
#define EN_PIN    8    // LOW = driver zapnuty
#define SERVO_PIN 9    // servo shutteru
SoftwareSerial link(A0, A1);
Servo shutter;

// ----- nastaveni (doladit podle sestavy) -----
const long KROKU_NA_OTACKU = 3200;  // 200 kroku * 16 mikrokroku
const int  SERVO_OTEVRENO  = 90;
const int  SERVO_ZAVRENO   = 110;   // o 20° dal = laser zakryty
const float UHEL[2][2] = { {0, 45}, {22.5, 67.5} };  // [baze][bit], baze 0 = HV, 1 = DA

const int N   = 64;     // pocet qubitu v jednom kole
const int KLIC = 16;    // delka klice v bitech
const float PRAH_QBER = 0.11;

// ----- data jednoho kola -----
byte bit[N], baze[N];    // co poslala Alice
byte bobBaze[N];         // co rekl Bob (verejne)
byte bobPlatne[N];       // 1 = Bob neco zmeril
long poloha = 0;         // poloha krokace v krocich
char radek[80];          // prijata zprava z linky

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

// Precte jeden radek z linky. Vraci false, kdyz do 'ms' nic neprijde.
bool prectiRadek(unsigned long ms) {
  unsigned long start = millis();
  int n = 0;
  while (millis() - start < ms) {
    if (!link.available()) continue;
    char c = link.read();
    if (c == '\n') { radek[n] = 0; if (n > 0) return true; }
    else if (c != '\r' && n < 79) radek[n++] = c;
  }
  return false;
}

// Ceka na zpravu, ktera zacina textem 'zacatek' (jine zpravy preskoci).
bool cekejNa(const char *zacatek) {
  while (prectiRadek(10000))
    if (strncmp(radek, zacatek, strlen(zacatek)) == 0) return true;
  Serial.print(F("! Bob neodpovida, cekal jsem na ")); Serial.println(zacatek);
  return false;
}

// Posle pole nul a jednicek jako text, napr. "AB 0110..."
void posliBity(const char *nazev, byte *b, int pocet) {
  link.print(nazev); link.print(' ');
  for (int i = 0; i < pocet; i++) link.print(b[i]);
  link.println();
}

void nactiBity(const char *text, byte *b) {   // opak posliBity
  for (int i = 0; i < N; i++) b[i] = text[i] - '0';
}

// ================= 1. kvantova faze =================
bool kvantovaFaze() {
  for (int i = 0; i < N; i++) {
    bit[i]  = random(2);
    baze[i] = random(2);
    natocHWP(UHEL[baze[i]][bit[i]]);
    Serial.print(F("#A ")); Serial.print(i); Serial.print(' ');
    Serial.print(baze[i]); Serial.print(' '); Serial.println(bit[i]);

    link.print(F("R ")); link.println(i);       // "mam pripraveno"
    if (!cekejNa("K")) return false;            // Bob nastavil bazi
    shutter.write(SERVO_OTEVRENO);              // laser sviti
    link.println(F("P"));
    if (!cekejNa("M")) return false;            // Bob zmeril (VALID byl HIGH)
    shutter.write(SERVO_ZAVRENO);               // laser zakryt
    link.println(F("Z"));
    if (!cekejNa("D")) return false;            // detektor zhasl + 100 ms
  }
  return true;
}

// ================= 2. sifting a QBER =================
// vraci true, kdyz je klic v poradku
bool sifting(uint16_t &klic) {
  link.println(F("S"));                          // Bobe, rekni sve baze
  if (!cekejNa("BB")) return false;  nactiBity(radek + 3, bobBaze);
  if (!cekejNa("BV")) return false;  nactiBity(radek + 3, bobPlatne);
  posliBity("AB", baze, N);                      // moje baze (ne bity!)

  // ponechame jen qubity se stejnou bazi, ktere Bob zachytil
  byte prosete[N]; int n = 0;
  for (int i = 0; i < N; i++)
    if (bobPlatne[i] && baze[i] == bobBaze[i]) prosete[n++] = bit[i];

  int test = n - KLIC;                           // zbytek za klicem = test
  if (test < 8) {
    Serial.println(F("Malo bitu, opakuji."));
    Serial.println(F("#RESULT FEW"));
    link.println(F("FAIL"));
    return false;
  }
  posliBity("TB", prosete + KLIC, test);         // testovaci bity verejne
  if (!cekejNa("Q")) return false;               // Bob: "Q <pocet chyb>"
  float qber = atoi(radek + 2) / (float)test;
  Serial.print(F("QBER:")); Serial.println(qber, 4);

  if (qber > PRAH_QBER) {
    Serial.println(F("!!! Prilis chyb - nekdo posloucha (Eve). Klic zahazuji."));
    Serial.println(F("#RESULT FAIL"));
    link.println(F("FAIL"));
    return false;
  }
  klic = 0;
  for (int k = 0; k < KLIC; k++) klic = klic * 2 + prosete[k];
  Serial.println(F("#RESULT OK"));
  link.println(F("OK"));
  return true;
}

// ================= cely protokol =================
void spustQKD() {
  uint16_t klic;
  for (int kolo = 1; ; kolo++) {
    Serial.print(F("#ROUND ")); Serial.println(kolo);
    if (kvantovaFaze() && sifting(klic)) break;
    delay(1000);
  }
  Serial.print(F("KEY:"));
  if (klic < 0x1000) Serial.print('0');
  if (klic < 0x100)  Serial.print('0');
  if (klic < 0x10)   Serial.print('0');
  Serial.println(klic, HEX);

  // 3. prenos obrazku: co prijde z PC, posli Bobovi.
  // Po 32 bajtech potvrdime '.', aby PC necpalo data rychleji nez linka stihne.
  while (true) {
    byte buf[32]; int n = 0;
    unsigned long t = millis();
    while (n < 32 && millis() - t < 20)
      if (Serial.available()) { buf[n++] = Serial.read(); t = millis(); }
    if (n > 0) { link.write(buf, n); Serial.write('.'); }
  }
}

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT); digitalWrite(EN_PIN, LOW);
  shutter.attach(SERVO_PIN);
  shutter.write(SERVO_ZAVRENO);
  Serial.begin(115200);
  link.begin(9600);
  randomSeed(analogRead(A2) * 31 + analogRead(A3) + micros());
  Serial.println(F("ALICE pripravena. g = start, o/c = shutter otevrit/zavrit"));
}

void loop() {
  if (!Serial.available()) return;
  char c = Serial.read();
  if (c == 'g') spustQKD();
  if (c == 'o') shutter.write(SERVO_OTEVRENO);
  if (c == 'c') shutter.write(SERVO_ZAVRENO);
}
