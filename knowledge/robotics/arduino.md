---
title: Arduino
summary: Programming microcontrollers in Arduino C++ — pins, sensors, motors, timing without delay(), and a complete obstacle-avoiding robot.
tags: [robotics, arduino, microcontroller, cpp, embedded, esp32, motors, sensors]
---
# Arduino

## Overview
An Arduino is a small microcontroller board that runs one program (a "sketch") forever. Sketches are C++ with helper functions (`digitalWrite`, `analogRead`...). Boards: Uno (classic, 5 V), Nano (small), ESP32 (Wi-Fi + Bluetooth, 3.3 V), Raspberry Pi Pico (also runs MicroPython).

## Setup and running
- Install the Arduino IDE (arduino.cc). Plug in the board, pick it under Tools → Board and Port, click Upload.
- Open Tools → Serial Monitor (set the baud rate to match `Serial.begin`) to see `Serial.println` output.
- ESP32: add the ESP32 board package in Boards Manager first.

## Sketch structure
```cpp
const int LED_PIN = 13;

void setup() {                 // runs once at power-on
  pinMode(LED_PIN, OUTPUT);
  Serial.begin(9600);
}

void loop() {                  // runs forever
  digitalWrite(LED_PIN, HIGH);
  delay(500);
  digitalWrite(LED_PIN, LOW);
  delay(500);
}
```

## Inputs
```cpp
pinMode(2, INPUT_PULLUP);                  // button between pin 2 and GND
bool pressed = digitalRead(2) == LOW;      // LOW = pressed with a pull-up
int pot = analogRead(A0);                  // 0..1023
int brightness = map(pot, 0, 1023, 0, 255);
analogWrite(9, brightness);                // PWM on a ~ pin
```

## Ultrasonic distance (HC-SR04)
```cpp
long readDistanceCm(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH); delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  unsigned long us = pulseIn(echoPin, HIGH, 30000);   // timeout ≈ 5 m
  if (us == 0) return -1;                             // no echo
  return us / 58;                                     // sound: ~58 µs per cm round trip
}
```

## Timing without delay()
`delay()` freezes the whole board, so it can't read sensors meanwhile. Use `millis()`:
```cpp
unsigned long lastBlink = 0;
void loop() {
  if (millis() - lastBlink >= 500) {      // subtraction handles millis() wrap-around
    lastBlink = millis();
    digitalWrite(13, !digitalRead(13));
  }
  // other work keeps running here
}
```

## Common mistakes
- Powering motors from the Arduino's 5 V pin; use a driver and a battery, with a common ground.
- Using `delay()` in robots, making them slow to react.
- Wrong baud rate in the Serial Monitor (garbage text).
- Forgetting a resistor on LEDs, or `INPUT_PULLUP` on buttons (random readings).
- 5 V sensor signals into 3.3 V boards (ESP32, Pico) without level shifting.
- `int` overflow on Uno (it's 16-bit: max 32767); use `long` or `unsigned long` for time.

## Learning path
### Level 1 — Pins
Blink, buttons, potentiometers, Serial Monitor, PWM.
Exercise: a reaction-time game — LED lights at a random time, measure how fast the button is pressed.

### Level 2 — Sensors and motors
Ultrasonic sensor, servo library, DC motors through a driver, `millis()` timing.
Exercise: a servo "radar" that sweeps and prints distances.

### Level 3 — A real robot
Differential drive, obstacle avoidance, line following with IR sensors, state machines, PID.
Exercise: the obstacle-avoiding robot below, then add line following.

### Level 4 — Connected and advanced
ESP32 Wi-Fi/Bluetooth control from a phone, encoders with interrupts, I²C IMU, talking to a Raspberry Pi over serial.
Exercise: control the robot from a phone over Bluetooth.

## Complete example
```arduino run
// Obstacle-avoiding robot: TB6612FNG motor driver + HC-SR04 sensor.
const int TRIG = 7, ECHO = 8;
const int L_PWM = 5, L_DIR = 4, R_PWM = 6, R_DIR = 3;

void drive(int left, int right) {            // -255..255 per wheel
  left = constrain(left, -255, 255);
  right = constrain(right, -255, 255);
  digitalWrite(L_DIR, left >= 0 ? HIGH : LOW);
  digitalWrite(R_DIR, right >= 0 ? HIGH : LOW);
  analogWrite(L_PWM, left >= 0 ? left : -left);
  analogWrite(R_PWM, right >= 0 ? right : -right);
}

long distanceCm() {
  digitalWrite(TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  unsigned long us = pulseIn(ECHO, HIGH, 30000);
  return us == 0 ? 999 : (long)(us / 58);
}

void setup() {
  int outputs[] = {TRIG, L_PWM, L_DIR, R_PWM, R_DIR};
  for (int pin : outputs) pinMode(pin, OUTPUT);
  pinMode(ECHO, INPUT);
  Serial.begin(115200);
}

void loop() {
  long cm = distanceCm();
  Serial.print("distance cm: ");
  Serial.println(cm);
  if (cm < 25) {
    drive(-150, 150);      // obstacle: spin in place
    delay(300);
  } else {
    drive(180, 180);       // clear: go forward
  }
  delay(50);
}
```
