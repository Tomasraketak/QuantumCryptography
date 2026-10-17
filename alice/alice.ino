// =====================================================================
//  ALICE  - vysilac BB84 (Arduino Uno + CNC shield V3)
//
//  Laser -> shutter (servo) -> polarizer (H) -> HWP (krokac, osa X)
//
//  Kodovani:  bit 0 = H (baze HV) / D (baze DA)
//             bit 1 = V (baze HV) / A (baze DA)
//  HWP otoci polarizaci o 2*theta:  H=0, V=45, D=22.5, A=67.5 stupnu
//
//  USB Serial (115200): log + prikazy (viz printHelp)
//  SoftwareSerial (A0=RX, A1=TX, 9600): klasicky kanal k Bobovi
// =====================================================================
#include <SoftwareSerial.h>
#include <Servo.h>

// ---------------- piny (CNC shield V3) ----------------
const uint8_t STEP_PIN  = 2;   // X.STEP
const uint8_t DIR_PIN   = 5;   // X.DIR
const uint8_t EN_PIN    = 8;   // EN (LOW = driver zapnut)
const uint8_t SERVO_PIN = 9;   // X-limit header (D9)
SoftwareSerial link(A0, A1);   // RX, TX  -> krizem na Boba

// ---------------- mechanika ----------------
const long STEPS_PER_REV = 3200;      // 200 kroku * 16 mikrokroku (dle jumperu)
const int  STEP_DELAY_US = 600;       // rychlost krokace
const bool DIR_INVERT    = false;
const int  SHUTTER_OPEN   = 90;       // uhel serva - laser sviti
const int  SHUTTER_CLOSED = 110;      // +20 stupnu - laser zastinen
const int  SHUTTER_MS     = 250;      // cas na pohyb serva

// uhly HWP v desetinach stupne [baze][bit]; doladit kalibraci!
// baze 0 = HV, baze 1 = DA
const int HWP_ANGLE[2][2] = { {0, 450}, {225, 675} };

// ---------------- protokol ----------------
const int   N_QUBITS   = 64;    // poslanych qubitu v jednom kole (nasobek 4)
const int   KEY_BITS   = 16;    // delka klice
const int   MIN_TEST   = 8;     // minimum bitu pro odhad QBER
const float QBER_LIMIT = 0.11;  // nad timto prahem -> Eve
const unsigned long LINK_TIMEOUT = 10000;

Servo shutter;
long hwpPos = 0;                // aktualni poloha v krocich (0 = nula pri zapnuti)

uint8_t aBit[N_QUBITS], aBase[N_QUBITS];
uint8_t bBase[N_QUBITS], bValid[N_QUBITS];
int sifted[N_QUBITS];
int nSifted = 0;
uint16_t key = 0;
bool bridge = false;            // po ziskani klice: USB -> link (obrazek)

char lineBuf[96];

// ================= pomocne funkce =================
void stepMotor(long steps) {
  digitalWrite(DIR_PIN, (steps > 0) ^ DIR_INVERT ? HIGH : LOW);
  if (steps < 0) steps = -steps;
  for (long i = 0; i < steps; i++) {
    digitalWrite(STEP_PIN, HIGH); delayMicroseconds(STEP_DELAY_US);
    digitalWrite(STEP_PIN, LOW);  delayMicroseconds(STEP_DELAY_US);
  }
}

// HWP ma periodu 90 stupnu (theta a theta+90 dava stejnou polarizaci),
// proto jedeme vzdy nejkratsi cestou v ramci ctvrt otacky.
void setHWP(int angle10) {
  const long Q = STEPS_PER_REV / 4;
  long target = (long)angle10 * STEPS_PER_REV / 3600;
  long diff = (target - hwpPos) % Q;
  if (diff >  Q / 2) diff -= Q;
  if (diff < -Q / 2) diff += Q;
  stepMotor(diff);
  hwpPos = ((hwpPos + diff) % Q + Q) % Q;
}

void moveHWPAbsolute(int angle10) {       // pro kalibraci - bez zkracovani
  long target = (long)angle10 * STEPS_PER_REV / 3600;
  stepMotor(target - hwpPos);
  hwpPos = target;
}

void laserOn()  { shutter.write(SHUTTER_OPEN);   delay(SHUTTER_MS); }
void laserOff() { shutter.write(SHUTTER_CLOSED); delay(SHUTTER_MS); }

bool readLine(Stream &s, char *buf, int len, unsigned long timeout) {
  unsigned long t0 = millis();
  int n = 0;
  while (millis() - t0 < timeout) {
    while (s.available()) {
      char c = s.read();
      if (c == '\r') continue;
      if (c == '\n') { buf[n] = 0; if (n) return true; continue; }
      if (n < len - 1) buf[n++] = c;
    }
  }
  buf[n] = 0;
  return false;
}

// cekej na radek zacinajici prefixem (ostatni zahodi)
bool expect(const char *prefix, unsigned long timeout) {
  unsigned long t0 = millis();
  while (millis() - t0 < timeout) {
    if (readLine(link, lineBuf, sizeof(lineBuf), timeout - (millis() - t0)) &&
        strncmp(lineBuf, prefix, strlen(prefix)) == 0) return true;
  }
  Serial.print(F("! timeout, cekam na ")); Serial.println(prefix);
  return false;
}

void bitsToHex(const uint8_t *b, int n, char *out) {
  const char *H = "0123456789ABCDEF";
  for (int i = 0; i < n / 4; i++) {
    uint8_t v = (b[4*i] << 3) | (b[4*i+1] << 2) | (b[4*i+2] << 1) | b[4*i+3];
    out[i] = H[v];
  }
  out[n / 4] = 0;
}

void hexToBits(const char *h, uint8_t *b, int n) {
  for (int i = 0; i < n / 4; i++) {
    char c = h[i];
    uint8_t v = (c >= 'A') ? (c - 'A' + 10) : (c - '0');
    for (int k = 0; k < 4; k++) b[4*i+k] = (v >> (3 - k)) & 1;
  }
}

const char *stateName(uint8_t base, uint8_t bit) {
  static const char *N[2][2] = { {"H", "V"}, {"D", "A"} };
  return N[base][bit];
}

void seedRandom() {
  unsigned long s = micros();
  for (int i = 0; i < 32; i++)
    s = (s << 1) ^ analogRead(A2 + (i % 4)) ^ (micros() << 3);
  randomSeed(s);
}

// ================= BB84 =================
bool quantumPhase() {
  Serial.println(F("--- kvantova faze ---"));
  Serial.println(F("  i  baze bit stav"));
  for (int i = 0; i < N_QUBITS; i++) {
    aBit[i]  = random(2);
    aBase[i] = random(2);
    setHWP(HWP_ANGLE[aBase[i]][aBit[i]]);

    link.print(F("R ")); link.println(i);          // Alice pripravena
    if (!expect("K", LINK_TIMEOUT)) return false;  // Bob nastavil bazi
    laserOn();
    link.print(F("P ")); link.println(i);          // puls sviti
    if (!expect("M", LINK_TIMEOUT)) return false;  // Bob zmeril
    laserOff();

    char row[32];
    snprintf(row, sizeof(row), "%3d  %s   %d   %s", i,
             aBase[i] ? "DA" : "HV", aBit[i], stateName(aBase[i], aBit[i]));
    Serial.println(row);
  }
  return true;
}

void computeSifted() {
  nSifted = 0;
  for (int i = 0; i < N_QUBITS; i++)
    if (bValid[i] && aBase[i] == bBase[i]) sifted[nSifted++] = i;
}

// vraci: 1 = klic OK, 0 = Eve/chyba -> opakovat
int classicalPhase() {
  char hex[N_QUBITS / 4 + 1];
  char hex2[N_QUBITS / 4 + 1];

  Serial.println(F("--- sifting (verejny kanal) ---"));
  link.println(F("S"));
  if (!expect("BB ", LINK_TIMEOUT)) return 0;       // "BB <baze> <valid>"
  hexToBits(lineBuf + 3, bBase, N_QUBITS);
  hexToBits(lineBuf + 4 + N_QUBITS / 4, bValid, N_QUBITS);

  bitsToHex(aBase, N_QUBITS, hex);
  link.print(F("AB ")); link.println(hex);

  computeSifted();
  Serial.print(F("Shodna baze + detekce: ")); Serial.print(nSifted);
  Serial.print('/'); Serial.println(N_QUBITS);

  int nTest = nSifted - KEY_BITS;
  if (nTest < MIN_TEST) {
    Serial.println(F("Malo bitu, opakuji kolo."));
    link.println(F("FAIL"));
    return 0;
  }

  // odhaleni testovacich bitu (vsech prosetych za klicem)
  uint8_t tb[N_QUBITS];
  memset(tb, 0, sizeof(tb));
  for (int k = 0; k < nTest; k++) tb[k] = aBit[sifted[KEY_BITS + k]];
  bitsToHex(tb, N_QUBITS, hex2);
  link.print(F("TB ")); link.println(hex2);

  if (!expect("Q ", LINK_TIMEOUT)) return 0;        // "Q <chyby> <pocet>"
  int err = atoi(lineBuf + 2);
  float qber = (float)err / nTest;
  Serial.print(F("QBER = ")); Serial.print(err); Serial.print('/');
  Serial.print(nTest); Serial.print(F(" = "));
  Serial.print(qber * 100, 1); Serial.println(F(" %"));
  Serial.print(F("QBER:")); Serial.println(qber, 4);

  if (qber > QBER_LIMIT) {
    Serial.println(F("!!! QBER nad prahem - mozny odposlech (EVE). Klic zahozen."));
    link.println(F("FAIL"));
    return 0;
  }

  key = 0;
  for (int k = 0; k < KEY_BITS; k++) key = (key << 1) | aBit[sifted[k]];
  link.println(F("OK"));
  return 1;
}

void runQKD() {
  for (int round = 1; ; round++) {
    Serial.print(F("===== KOLO ")); Serial.print(round); Serial.println(F(" ====="));
    while (link.available()) link.read();
    if (quantumPhase() && classicalPhase() == 1) break;
    delay(1000);
  }
  char k[24];
  snprintf(k, sizeof(k), "KEY:%04X", key);
  Serial.println(k);
  Serial.println(F("Rezim prenosu obrazku: USB -> Bob"));
  bridge = true;
}

// ================= prikazy (kalibrace) =================
void printHelp() {
  Serial.println(F("Prikazy: g = start QKD | o/c = shutter otevrit/zavrit"));
  Serial.println(F("  a <deg> = HWP na uhel | j <kroky> = posun | z = nulovat"));
  Serial.println(F("  H V D A = nastav stav | ? = napoveda"));
}

void handleCommand(char *cmd) {
  switch (cmd[0]) {
    case 'g': runQKD(); break;
    case 'o': laserOn();  Serial.println(F("shutter open")); break;
    case 'c': laserOff(); Serial.println(F("shutter closed")); break;
    case 'a': moveHWPAbsolute((int)(atof(cmd + 1) * 10)); Serial.println(hwpPos); break;
    case 'j': stepMotor(atol(cmd + 1)); hwpPos += atol(cmd + 1); Serial.println(hwpPos); break;
    case 'z': hwpPos = 0; Serial.println(F("nula")); break;
    case 'H': setHWP(HWP_ANGLE[0][0]); break;
    case 'V': setHWP(HWP_ANGLE[0][1]); break;
    case 'D': setHWP(HWP_ANGLE[1][0]); break;
    case 'A': setHWP(HWP_ANGLE[1][1]); break;
    default: printHelp();
  }
}

void setup() {
  pinMode(STEP_PIN, OUTPUT); pinMode(DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT);   digitalWrite(EN_PIN, LOW);
  shutter.attach(SERVO_PIN);
  shutter.write(SHUTTER_CLOSED);
  Serial.begin(115200);
  link.begin(9600);
  seedRandom();
  Serial.println(F("ALICE ready"));
  printHelp();
}

void loop() {
  if (bridge) {
    // PC posle max 32 B, Alice je preposle a potvrdi '.' (rizeni toku -
    // SoftwareSerial pri vysilani blokuje preruseni a USB by ztracel data)
    uint8_t buf[32];
    int n = 0;
    unsigned long t0 = millis();
    while (n < 32 && millis() - t0 < 20) {
      if (Serial.available()) { buf[n++] = Serial.read(); t0 = millis(); }
    }
    if (n) { link.write(buf, n); Serial.write('.'); }
    return;
  }
  if (Serial.available()) {
    char cmd[32];
    if (readLine(Serial, cmd, sizeof(cmd), 200)) handleCommand(cmd);
  }
}
