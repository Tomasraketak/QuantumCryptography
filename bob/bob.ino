// =====================================================================
//  BOB  - prijimac BB84 (Arduino Uno + CNC shield V3)
//
//  HWP (krokac, osa X) -> PBS -> detektor 1 (H) / detektor 2 (V)
//  Baze HV: HWP 0 stupnu,  baze DA: HWP 22.5 stupnu (D -> H)
//  Detektor 1 = bit 0 (H/D), detektor 2 = bit 1 (V/A)
//  Pin VALID rika, ze mereni je platne (detektor zaznamenal puls).
//
//  USB Serial (115200): log + prikazy, po ziskani klice prijaty obrazek
//  SoftwareSerial (A0=RX, A1=TX, 9600): klasicky kanal k Alici
// =====================================================================
#include <SoftwareSerial.h>

// ---------------- piny (CNC shield V3) ----------------
const uint8_t STEP_PIN  = 2;    // X.STEP
const uint8_t DIR_PIN   = 5;    // X.DIR
const uint8_t EN_PIN    = 8;    // EN (LOW = driver zapnut)
const uint8_t DET1_PIN  = 9;    // X-limit  : detektor 1 (H)
const uint8_t DET2_PIN  = 10;   // Y-limit  : detektor 2 (V)
const uint8_t VALID_PIN = 11;   // Z-limit  : mereni platne
const uint8_t ACTIVE    = HIGH; // uroven "svetlo dopada" / "valid"
SoftwareSerial link(A0, A1);    // RX, TX  -> krizem na Alici

// ---------------- mechanika ----------------
const long STEPS_PER_REV = 3200;
const int  STEP_DELAY_US = 600;
const bool DIR_INVERT    = false;
const int  HWP_BASIS[2]  = { 0, 225 };  // desetiny stupne: HV, DA

// ---------------- protokol ----------------
const int  N_QUBITS = 64;               // musi sedet s Alici
const int  KEY_BITS = 16;
const int  MEAS_MS  = 150;              // okno mereni po "P"
const int  SAMPLES  = 15;

long hwpPos = 0;
uint8_t bBase[N_QUBITS], bBit[N_QUBITS], bValid[N_QUBITS];
uint8_t aBase[N_QUBITS];
int sifted[N_QUBITS];
int nSifted = 0;
uint16_t key = 0;
bool bridge = false;

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

// HWP ma periodu 90 stupnu -> nejkratsi cesta v ramci ctvrt otacky
void setHWP(int angle10) {
  const long Q = STEPS_PER_REV / 4;
  long target = (long)angle10 * STEPS_PER_REV / 3600;
  long diff = (target - hwpPos) % Q;
  if (diff >  Q / 2) diff -= Q;
  if (diff < -Q / 2) diff += Q;
  stepMotor(diff);
  hwpPos = ((hwpPos + diff) % Q + Q) % Q;
}

void moveHWPAbsolute(int angle10) {
  long target = (long)angle10 * STEPS_PER_REV / 3600;
  stepMotor(target - hwpPos);
  hwpPos = target;
}

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

void seedRandom() {
  unsigned long s = micros();
  for (int i = 0; i < 32; i++)
    s = (s << 1) ^ analogRead(A2 + (i % 4)) ^ (micros() << 3);
  randomSeed(s);
}

// Mereni: vzorkuje okno MEAS_MS, vetsinove rozhodnuti.
// Vraci 0/1 = bit, 255 = neplatne (zadna detekce nebo oba detektory).
uint8_t measure() {
  int c1 = 0, c2 = 0, cv = 0;
  for (int s = 0; s < SAMPLES; s++) {
    if (digitalRead(DET1_PIN)  == ACTIVE) c1++;
    if (digitalRead(DET2_PIN)  == ACTIVE) c2++;
    if (digitalRead(VALID_PIN) == ACTIVE) cv++;
    delay(MEAS_MS / SAMPLES);
  }
  bool d1 = c1 > SAMPLES / 2, d2 = c2 > SAMPLES / 2, v = cv > SAMPLES / 2;
  if (!v || d1 == d2) return 255;
  return d1 ? 0 : 1;
}

// ================= BB84 - Bob reaguje na zpravy Alice =================
void computeSifted() {
  nSifted = 0;
  for (int i = 0; i < N_QUBITS; i++)
    if (bValid[i] && aBase[i] == bBase[i]) sifted[nSifted++] = i;
}

void handleLink(char *msg) {
  char hex[N_QUBITS / 4 + 1];

  if (msg[0] == 'R') {                       // Alice pripravila qubit i
    int i = atoi(msg + 2);
    if (i < 0 || i >= N_QUBITS) return;
    if (i == 0) Serial.println(F("--- kvantova faze ---\n  i  baze det"));
    bBase[i] = random(2);
    setHWP(HWP_BASIS[bBase[i]]);
    link.print(F("K ")); link.println(i);
  }
  else if (msg[0] == 'P') {                  // laser sviti -> merit
    int i = atoi(msg + 2);
    if (i < 0 || i >= N_QUBITS) return;
    uint8_t r = measure();
    bValid[i] = (r != 255);
    bBit[i]   = bValid[i] ? r : 0;
    link.print(F("M ")); link.println(i);
    Serial.print(F("#B ")); Serial.print(i); Serial.print(' ');
    Serial.print(bBase[i]); Serial.print(' ');
    if (r == 255) Serial.println('-'); else Serial.println(r);
    char row[32];
    snprintf(row, sizeof(row), "%3d  %s   %s", i, bBase[i] ? "DA" : "HV",
             r == 255 ? "-" : (r ? "2" : "1"));
    Serial.println(row);
  }
  else if (msg[0] == 'S') {                  // sifting: posli baze + valid
    Serial.println(F("--- sifting ---"));
    link.print(F("BB "));
    bitsToHex(bBase, N_QUBITS, hex);  link.print(hex); link.print(' ');
    bitsToHex(bValid, N_QUBITS, hex); link.println(hex);
  }
  else if (!strncmp(msg, "AB ", 3)) {        // baze Alice
    hexToBits(msg + 3, aBase, N_QUBITS);
    computeSifted();
    Serial.print(F("Shodna baze + detekce: ")); Serial.print(nSifted);
    Serial.print('/'); Serial.println(N_QUBITS);
  }
  else if (!strncmp(msg, "TB ", 3)) {        // testovaci bity Alice
    uint8_t tb[N_QUBITS];
    hexToBits(msg + 3, tb, N_QUBITS);
    int nTest = nSifted - KEY_BITS, err = 0;
    for (int k = 0; k < nTest; k++)
      if (tb[k] != bBit[sifted[KEY_BITS + k]]) err++;
    link.print(F("Q ")); link.print(err); link.print(' '); link.println(nTest);
    Serial.print(F("QBER = ")); Serial.print(err); Serial.print('/');
    Serial.print(nTest); Serial.print(F(" = "));
    Serial.print(nTest ? 100.0 * err / nTest : 0, 1); Serial.println(F(" %"));
    Serial.print(F("QBER:")); Serial.println(nTest ? (float)err / nTest : 0, 4);
  }
  else if (!strcmp(msg, "FAIL")) {
    Serial.println(F("!!! Kolo zamitnuto (QBER nad prahem / malo bitu). Novy pokus."));
  }
  else if (!strcmp(msg, "OK")) {
    key = 0;
    for (int k = 0; k < KEY_BITS; k++) key = (key << 1) | bBit[sifted[k]];
    char k[24];
    snprintf(k, sizeof(k), "KEY:%04X", key);
    Serial.println(k);
    Serial.println(F("Rezim prijmu obrazku: link -> USB"));
    Serial.flush();
    bridge = true;
  }
}

// ================= prikazy (kalibrace) =================
void printHelp() {
  Serial.println(F("Prikazy: d = cti detektory | a <deg> = HWP na uhel"));
  Serial.println(F("  j <kroky> = posun | z = nulovat | h/x = baze HV/DA | ? = napoveda"));
}

void handleCommand(char *cmd) {
  switch (cmd[0]) {
    case 'd':
      Serial.print(F("det1=")); Serial.print(digitalRead(DET1_PIN) == ACTIVE);
      Serial.print(F(" det2=")); Serial.print(digitalRead(DET2_PIN) == ACTIVE);
      Serial.print(F(" valid=")); Serial.println(digitalRead(VALID_PIN) == ACTIVE);
      break;
    case 'a': moveHWPAbsolute((int)(atof(cmd + 1) * 10)); Serial.println(hwpPos); break;
    case 'j': stepMotor(atol(cmd + 1)); hwpPos += atol(cmd + 1); Serial.println(hwpPos); break;
    case 'z': hwpPos = 0; Serial.println(F("nula")); break;
    case 'h': setHWP(HWP_BASIS[0]); break;
    case 'x': setHWP(HWP_BASIS[1]); break;
    default: printHelp();
  }
}

void setup() {
  pinMode(STEP_PIN, OUTPUT); pinMode(DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT);   digitalWrite(EN_PIN, LOW);
  pinMode(DET1_PIN, INPUT); pinMode(DET2_PIN, INPUT); pinMode(VALID_PIN, INPUT);
  Serial.begin(115200);
  link.begin(9600);
  seedRandom();
  Serial.println(F("BOB ready - cekam na Alici"));
  printHelp();
}

void loop() {
  if (bridge) {                               // obrazek: link -> PC
    while (link.available()) Serial.write(link.read());
    return;
  }
  if (link.available() && readLine(link, lineBuf, sizeof(lineBuf), 500))
    handleLink(lineBuf);
  if (Serial.available()) {
    char cmd[32];
    if (readLine(Serial, cmd, sizeof(cmd), 200)) handleCommand(cmd);
  }
}
