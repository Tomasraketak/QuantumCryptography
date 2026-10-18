// =====================================================================
//  QKD BB84 - JEDNO Arduino Uno + CNC shield pro Alici i Boba
//  Alice: laser -> shutter (servo) -> polarizator -> HWP (krokac Z)
//  Bob:   HWP (krokac X) -> polarizacni delic -> detektor 0 / detektor 1
//
//  Arduino jen poslouchá příkazy z PC (USB, 115200, konec řádku \n).
//
//  ALICE                                   odpověď
//    V H D A   HWP na 0 / 45 / -22.5 / +22.5°   OK <poloha>
//    O / C     shutter otevřít / zavřít         OK
//    ZERO1     aktuální natočení = 0 (= V)      OK 0
//    k<st>     pootoč o <st> stupňů, např. k15  OK <poloha>
//  BOB
//    +         HWP na 0° (báze HV)              OK <poloha>
//    X         HWP na +22.5° (báze DA)          OK <poloha>
//    ZERO2     aktuální natočení = 0            OK 0
//    K<st>     pootoč o <st> stupňů, např. K15  OK <poloha>
//    d         stav pinů                        det0=.. det1=.. valid=..
//
//  Arduino samo posílá:
//    L<d0><d1> VALID skočil na 1 (např. L10 = svítí detektor 0)
//    W         VALID spadl na 0 (+100 ms) - může se poslat další qubit
// =====================================================================
#include <Servo.h>

#define EN_PIN    8    // LOW = drivery zapnute
#define VALID_PIN 3    // preruseni (D3 = Y.STEP, ve slotu Y nesmi byt driver)
#define SERVO_PIN 9    // X- endstop
#define DET0_PIN  10   // Y- endstop, detektor 0 -> bit 0 (H / D)
#define DET1_PIN  11   // Z- endstop, detektor 1 -> bit 1 (V / A)

// motor 0 = Alice (slot Z), motor 1 = Bob (slot X)
const byte STEP_PIN[2] = {4, 2};
const byte DIR_PIN[2]  = {7, 5};
long poloha[2] = {0, 0};             // poloha HWP v krocich (0 = V)

const long KROKU_NA_OTACKU = 3200;   // 200 kroku * 16 mikrokroku
const int  SERVO_OTEVRENO  = 90;
const int  SERVO_ZAVRENO   = 110;    // o 20° dal = laser zakryty

Servo shutter;

// ----- preruseni: VALID prave sel do HIGH -----
volatile bool zablesk = false;
volatile byte det0, det1;
void onValid() {
  det0 = digitalRead(DET0_PIN);      // detektory cteme hned v okamziku platnosti
  det1 = digitalRead(DET1_PIN);
  zablesk = true;
}
bool sviti = false;                  // poslali jsme L a cekame na pad VALID

void krokuj(byte m, long kroky) {
  digitalWrite(DIR_PIN[m], kroky > 0 ? HIGH : LOW);
  for (long k = 0; k < abs(kroky); k++) {
    digitalWrite(STEP_PIN[m], HIGH); delayMicroseconds(600);
    digitalWrite(STEP_PIN[m], LOW);  delayMicroseconds(600);
  }
  poloha[m] += kroky;
}

void natocHWP(byte m, float stupne) {
  krokuj(m, lround(stupne * KROKU_NA_OTACKU / 360) - poloha[m]);
}

long stupneNaKroky(String s) {
  return lround(s.toFloat() * KROKU_NA_OTACKU / 360);
}

void setup() {
  for (byte m = 0; m < 2; m++) {
    pinMode(STEP_PIN[m], OUTPUT);
    pinMode(DIR_PIN[m], OUTPUT);
  }
  pinMode(EN_PIN, OUTPUT); digitalWrite(EN_PIN, LOW);
  pinMode(DET0_PIN, INPUT);
  pinMode(DET1_PIN, INPUT);
  pinMode(VALID_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(VALID_PIN), onValid, RISING);
  shutter.attach(SERVO_PIN);
  shutter.write(SERVO_ZAVRENO);
  Serial.begin(115200);
  Serial.println("QKD");
}

void loop() {
  // 1) detektor se rozsvitil -> pošli L<det0><det1>
  if (zablesk) {
    zablesk = false;
    sviti = true;
    Serial.print("L"); Serial.print(det0); Serial.println(det1);
  }
  // 2) detektor zhasl -> po 100 ms pošli W
  if (sviti && digitalRead(VALID_PIN) == LOW) {
    delay(100);
    sviti = false;
    Serial.println("W");
  }
  // 3) příkaz z PC
  if (!Serial.available()) return;
  String p = Serial.readStringUntil('\n');
  p.trim();

  if (p == "d") {
    Serial.print("det0="); Serial.print(digitalRead(DET0_PIN));
    Serial.print(" det1="); Serial.print(digitalRead(DET1_PIN));
    Serial.print(" valid="); Serial.println(digitalRead(VALID_PIN));
    return;
  }
  if (p == "O") { shutter.write(SERVO_OTEVRENO); delay(250); Serial.println("OK"); return; }
  if (p == "C") { shutter.write(SERVO_ZAVRENO);  delay(250); Serial.println("OK"); return; }

  byte m;                                       // ktery motor
  if      (p == "V") { m = 0; natocHWP(0, 0); }
  else if (p == "H") { m = 0; natocHWP(0, 45); }
  else if (p == "D") { m = 0; natocHWP(0, -22.5); }
  else if (p == "A") { m = 0; natocHWP(0, 22.5); }
  else if (p == "ZERO1") { m = 0; poloha[0] = 0; }
  else if (p.startsWith("k")) { m = 0; krokuj(0, stupneNaKroky(p.substring(1))); }
  else if (p == "+") { m = 1; natocHWP(1, 0); }
  else if (p == "X") { m = 1; natocHWP(1, 22.5); }
  else if (p == "ZERO2") { m = 1; poloha[1] = 0; }
  else if (p.startsWith("K")) { m = 1; krokuj(1, stupneNaKroky(p.substring(1))); }
  else { Serial.println("? " + p); return; }

  Serial.print("OK ");
  Serial.println(poloha[m]);
}
