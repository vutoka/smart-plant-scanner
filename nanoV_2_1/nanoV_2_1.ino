// ===== Arduino Nano firmware v2.1 =====
// Stepper + DHT11 + Soil + LED na D3 (PWM) sa BLINK-om preko millis()
// Povezivanje: IN1=D8, IN2=D9, IN3=D10, IN4=D11 (28BYJ-48 + ULN2003)
//              DHT11=D2, SOIL=A0, LED=D3 (preko MOSFET-a za LED traku)
#include <DHT.h>

#define IN1 8
#define IN2 9
#define IN3 10
#define IN4 11

#define DHTPIN 2
#define DHTTYPE DHT11
#define SOIL_PIN A0

#define LED_PIN 3  // PWM

DHT dht(DHTPIN, DHTTYPE);

// --- Stepper (half-step) ---
const uint8_t SEQ[8][4] = {
  {1,0,0,0},{1,1,0,0},{0,1,0,0},{0,1,1,0},
  {0,0,1,0},{0,0,1,1},{0,0,0,1},{1,0,0,1}
};
const long STEPS_PER_REV = 4096;
int STEP_DELAY_MS = 3;
volatile long currentPos = 0;
int seqIndex = 0;

void coilsWrite(uint8_t a, uint8_t b, uint8_t c, uint8_t d){
  digitalWrite(IN1,a); digitalWrite(IN2,b);
  digitalWrite(IN3,c); digitalWrite(IN4,d);
}
void applySeqIndex(int idx){ coilsWrite(SEQ[idx][0],SEQ[idx][1],SEQ[idx][2],SEQ[idx][3]); }
void powerDownCoils(){ coilsWrite(0,0,0,0); }

void stepOnce(int dir){
  seqIndex = (seqIndex + (dir>0?1:7)) & 0x07;
  applySeqIndex(seqIndex);
  delay(STEP_DELAY_MS);
  currentPos += (dir>0?1:-1);
  if (currentPos >= STEPS_PER_REV) currentPos -= STEPS_PER_REV;
  if (currentPos < 0) currentPos += STEPS_PER_REV;
  // update blink timing each step to keep LED blinking during long moves
  ledBlinkService();
}

void moveSteps(long steps){
  int dir = (steps>=0)?+1:-1;
  long cnt = labs(steps);
  while (cnt--) stepOnce(dir);
  powerDownCoils();
}
void moveAbs(long target){
  while (target >= STEPS_PER_REV) target -= STEPS_PER_REV;
  while (target < 0) target += STEPS_PER_REV;
  long delta = target - currentPos;
  if (delta >  (STEPS_PER_REV/2))  delta -= STEPS_PER_REV;
  if (delta <= -(STEPS_PER_REV/2)) delta += STEPS_PER_REV;
  moveSteps(delta);
}

// --- LED control (PWM + BLINK by millis) ---
enum LedMode { LEDMODE_OFF, LEDMODE_CONST, LEDMODE_BLINK };
LedMode ledMode = LEDMODE_OFF;
uint8_t ledPWM = 0;          // 0-255 for CONST / blink "on" level
unsigned long blinkPeriod = 1000; // ms
uint8_t blinkDuty = 50;      // %
unsigned long blinkT0 = 0;
bool blinkOnPhase = false;

void ledApply(uint8_t pwm){
  analogWrite(LED_PIN, pwm); // hardware PWM
}
void ledOff(){
  ledMode = LEDMODE_OFF; ledPWM = 0; ledApply(0);
}
void ledConst(uint8_t pwm){
  ledMode = LEDMODE_CONST; ledPWM = pwm; ledApply(pwm);
}
void ledBlink(uint16_t period_ms, uint8_t duty_percent, uint8_t pwm_on=255){
  if (duty_percent>100) duty_percent=100;
  if (period_ms<100) period_ms=100;
  ledMode = LEDMODE_BLINK; blinkPeriod = period_ms; blinkDuty = duty_percent;
  ledPWM = pwm_on;
  blinkT0 = millis();
  blinkOnPhase = true;
  ledApply(ledPWM);
}
void ledBlinkService(){
  if (ledMode != LEDMODE_BLINK) return;
  unsigned long now = millis();
  unsigned long onDur = (unsigned long)((blinkPeriod * (unsigned long)blinkDuty)/100UL);
  unsigned long offDur = blinkPeriod - onDur;
  if (blinkOnPhase){
    if (now - blinkT0 >= onDur){
      blinkOnPhase = false;
      blinkT0 = now;
      ledApply(0);
    }
  } else {
    if (now - blinkT0 >= offDur){
      blinkOnPhase = true;
      blinkT0 = now;
      ledApply(ledPWM);
    }
  }
}

// --- Serial helpers ---
String readLine(){
  if (!Serial.available()) return "";
  String s = Serial.readStringUntil('\n'); s.trim(); return s;
}

void handleCommand(const String& line){
  if (line.length()==0) return;

  Serial.print("ACK ");
  Serial.println(line);

  if (line.equalsIgnoreCase("HOME")){
    currentPos = 0;
    Serial.println("DONE HOME");
    return;
  }
  if (line.equalsIgnoreCase("SET_ZERO")){
    currentPos = 0;
    Serial.println("DONE SET_ZERO");
    return;
  }
  if (line.startsWith("STEP")){
    long n = line.substring(4).toInt();
    moveSteps(n);
    Serial.println("DONE STEP");
    return;
  }
  if (line.startsWith("MOVE_ABS")){
    long tgt = line.substring(8).toInt();
    moveAbs(tgt);
    Serial.println("DONE MOVE_ABS");
    return;
  }
  if (line.equalsIgnoreCase("GET_POS")){
    Serial.print("POS "); Serial.println(currentPos);
    return;
  }
  if (line.equalsIgnoreCase("GET_SENSORS")){
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    int soil = analogRead(SOIL_PIN);
    Serial.print("SENS T=");
    if (isnan(t)) Serial.print("NaN"); else Serial.print(t,1);
    Serial.print(" RH=");
    if (isnan(h)) Serial.print("NaN"); else Serial.print(h,1);
    Serial.print(" SOIL="); Serial.println(soil);
    return;
  }
  // --- LED commands ---
  if (line.equalsIgnoreCase("LED OFF")){
    ledOff();
    Serial.println("DONE LED_OFF");
    return;
  }
  if (line.startsWith("LED ON")){
    // form: "LED ON" ili "LED ON <0-255>"
    int space = line.indexOf(' ', 6);
    int pwm = 255;
    if (space>0){ pwm = constrain(line.substring(space+1).toInt(), 0, 255); }
    ledConst((uint8_t)pwm);
    Serial.println("DONE LED_ON");
    return;
  }
  if (line.startsWith("LED BLINK")){
    // form: "LED BLINK <period_ms> <duty%> [pwm]"
    // primer: LED BLINK 1000 50 255
    int p1 = line.indexOf(' ', 9);
    int p2 = (p1>0) ? line.indexOf(' ', p1+1) : -1;
    int p3 = (p2>0) ? line.indexOf(' ', p2+1) : -1;
    uint16_t period = 1000;
    uint8_t duty = 50;
    uint8_t pwm = 255;
    if (p1>0) period = (uint16_t)max(100, line.substring(10, p1).toInt());
    if (p2>0) duty   = (uint8_t)constrain(line.substring(p1+1, p2).toInt(), 0, 100);
    if (p3>0) pwm    = (uint8_t)constrain(line.substring(p2+1).toInt(), 0, 255);
    ledBlink(period, duty, pwm);
    Serial.println("DONE LED_BLINK");
    return;
  }

  Serial.println("ERR UNKNOWN_CMD");
}

void setup(){
  pinMode(IN1,OUTPUT); pinMode(IN2,OUTPUT);
  pinMode(IN3,OUTPUT); pinMode(IN4,OUTPUT);
  powerDownCoils();
  pinMode(LED_PIN, OUTPUT);
  ledOff();

  dht.begin();
  Serial.begin(115200);
  Serial.setTimeout(2000);
  Serial.println("READY");
}

void loop(){
  // servisiraj blink i dok miruje
  ledBlinkService();
  String line = readLine();
  if (line.length()) handleCommand(line);
}
