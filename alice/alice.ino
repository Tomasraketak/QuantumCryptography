// =====================================================================
//  ALICE - vysilac BB84 (Arduino Uno + CNC shield)
//  laser -> shutter (servo) -> polarizator -> HWP (krokac na ose X)
//
//  Arduino jen poslouchá příkazy z PC (USB, 115200, konec řádku \n).
//  Náhodu, klíč i šifrování dělá PC.
//
//  Příkazy:                               odpověď
//    V H D A   natoč HWP na stav           OK
//              (V = 0°, H = 45°, D = -22.5°, A = +22.5°)
//    O / C     shutter otevřít / zavřít    OK
//    0         HWP do nuly (V)             OK
//    ZERO      aktuální poloha = nula      OK
//    a <st>    HWP na úhel (kalibrace)     OK <poloha>
//    j <kroky> posun o kroky (kalibrace)   OK <poloha>
// =====================================================================
#include <Servo.h>

#define STEP_PIN  2    // krokac X - krok
#define DIR_PIN   5    // krokac X - smer
#define EN_PIN    8    // LOW = driver zapnuty
#define SERVO_PIN 9    // servo shutteru

const long KROKU_NA_OTACKU = 3200;   // 200 kroku * 16 mikrokroku
const int  SERVO_OTEVRENO  = 90;
const int  SERVO_ZAVRENO   = 110;    // o 20° dal = laser zakryty

Servo shutter;
long poloha = 0;                     // poloha HWP v krocich (0 = nula)

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

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT); digitalWrite(EN_PIN, LOW);
  shutter.attach(SERVO_PIN);
  shutter.write(SERVO_ZAVRENO);
  Serial.begin(115200);
  Serial.println("ALICE");
}

void loop() {
  if (!Serial.available()) return;
  String p = Serial.readStringUntil('\n');
  p.trim();

  if      (p == "V") natocHWP(0);
  else if (p == "H") natocHWP(45);
  else if (p == "D") natocHWP(-22.5);
  else if (p == "A") natocHWP(22.5);
  else if (p == "0") natocHWP(0);
  else if (p == "O") { shutter.write(SERVO_OTEVRENO); delay(250); }  // pockej na servo
  else if (p == "C") { shutter.write(SERVO_ZAVRENO);  delay(250); }
  else if (p == "ZERO") poloha = 0;
  else if (p.startsWith("a ")) natocHWP(p.substring(2).toFloat());
  else if (p.startsWith("j ")) krokuj(p.substring(2).toInt());
  else { Serial.println("? " + p); return; }

  Serial.print("OK ");
  Serial.println(poloha);
}
