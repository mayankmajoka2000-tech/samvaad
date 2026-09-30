// Samvaad Beacon, microcontroller side of the Arduino UNO Q (STM32U585).
// The Linux side calls alert(pattern) over the Router Bridge; this sketch plays
// the pattern on a vibration motor and an LED without blocking the Bridge.
//
// Wiring (see beacon/README.md):
//   D3  -> 1 kOhm -> NPN transistor base; motor between 3V3 and collector; diode across motor
//   D5  -> 220 Ohm -> LED -> GND

#include "Arduino_RouterBridge.h"

const int MOTOR_PIN = 3;
const int LED_PIN = 5;

// Each pattern is a list of on/off durations in milliseconds, ending with 0.
const unsigned int PATTERN_NAME[]  = {200, 120, 200, 120, 200, 0};              // three short buzzes
const unsigned int PATTERN_ALARM[] = {90, 90, 90, 90, 90, 90, 90, 90, 90, 90,
                                      90, 90, 90, 90, 90, 90, 90, 90, 90, 0};    // fast pulsing
const unsigned int PATTERN_TEST[]  = {700, 0};                                  // one long buzz

const unsigned int* current = nullptr;
int step = 0;
unsigned long stepStarted = 0;

void output(bool on) {
  digitalWrite(MOTOR_PIN, on ? HIGH : LOW);
  digitalWrite(LED_PIN, on ? HIGH : LOW);
}

void alert(int pattern) {
  if (pattern == 1) current = PATTERN_NAME;
  else if (pattern == 2) current = PATTERN_ALARM;
  else current = PATTERN_TEST;
  step = 0;
  stepStarted = millis();
  output(true);
}

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  output(false);
  Bridge.begin();
  Bridge.provide("alert", alert);
}

void loop() {
  if (current == nullptr) return;
  if (millis() - stepStarted < current[step]) return;
  step++;
  stepStarted = millis();
  if (current[step] == 0) {
    current = nullptr;
    output(false);
    return;
  }
  output(step % 2 == 0);  // even steps on, odd steps off
}
