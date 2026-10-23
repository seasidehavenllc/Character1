---
title: Electronics for robots
summary: Voltage, current, resistance, Ohm's law, LEDs and resistors, breadboards, digital vs analog, PWM, powering motors safely, I2C/SPI/UART.
tags: [robotics, electronics, circuits, power, wiring, beginner, ohms-law]
---
# Electronics for robots

## The three quantities
- **Voltage (V, volts)** — electrical "pressure". Arduino Uno logic is 5 V; Raspberry Pi and ESP32 are 3.3 V.
- **Current (I, amps)** — how much electricity flows. An LED needs ~10–20 mA; a small DC motor can draw 0.2–2 A (more when stalled).
- **Resistance (R, ohms Ω)** — how much a part resists current.
- **Ohm's law: V = I × R.** Power: P = V × I (watts).

## Worked example: LED resistor
A red LED drops about 2 V and wants about 15 mA. From a 5 V pin: R = (5 − 2) / 0.015 = 200 Ω → use the next standard value up, 220 Ω. Without the resistor the LED (and maybe the pin) burns out.

## Breadboards and wiring
- Breadboard rows of 5 holes are connected; the long side rails are power (+) and ground (−).
- **Every part must share a common ground** (connect all GNDs together), or signals won't make sense.
- Color convention: red = positive, black = ground. Keep wires short and tidy.

## Digital, analog and PWM
- **Digital** pins read/write HIGH or LOW (on/off): buttons, LEDs.
- **Analog inputs** read a voltage as a number (Arduino Uno: 0–1023 for 0–5 V): potentiometers, light sensors.
- **PWM** fakes analog output by switching on/off very fast; the duty cycle (0–255 on Arduino) sets LED brightness or motor speed.
- **Pull-up resistors**: a button input needs a defined state when not pressed. Use `INPUT_PULLUP`; the pin reads LOW when pressed.

## Powering motors safely
- **Never drive a motor straight from a microcontroller pin.** Pins supply ~20–40 mA; motors need hundreds or thousands. Use a motor driver (TB6612FNG, L298N, DRV8833).
- Power motors from a battery pack through the driver; power the logic from USB or a regulator; **join the grounds**.
- Motors cause voltage dips and electrical noise that reset microcontrollers. Add a 100–470 µF capacitor across the motor supply and keep motor wires away from signal wires.
- **3.3 V boards (Pi, ESP32) are not 5 V tolerant.** Use a level shifter or a voltage divider for 5 V sensor outputs (like HC-SR04 echo).
- LiPo batteries can catch fire if punctured, over-discharged or charged wrongly. Use a proper balance charger and never leave charging unattended.

## Communication buses
| Bus | Wires | Used for |
|---|---|---|
| UART (serial) | TX, RX, GND | USB serial monitor, GPS, Arduino ↔ Pi |
| I²C | SDA, SCL (+ power, GND) | Many sensors on two wires (IMUs, OLED screens); each has an address |
| SPI | MOSI, MISO, SCK, CS | Fast devices: SD cards, displays |

## Tools
A multimeter (voltage, continuity, current) is the most important tool. Then: breadboard and jumper wires, wire strippers, a soldering iron when ready, and a bench power supply with current limit for testing motors safely.

## Learning path
### Level 1 — Circuits
Voltage, current, resistance, Ohm's law; LED with resistor; using a multimeter.
Exercise: calculate and build LED circuits for 5 V and 3.3 V, and measure the current.

### Level 2 — Inputs and outputs
Buttons with pull-ups, potentiometers, analog reading, PWM dimming.
Exercise: a dimmer where a potentiometer sets LED brightness.

### Level 3 — Power and motors
Motor drivers, separate supplies, common ground, decoupling capacitors, battery choice, voltage regulators.
Exercise: wire two DC motors through a TB6612FNG and run them both directions.

### Level 4 — Buses and building
I²C and SPI sensors, level shifting, soldering, designing a simple PCB (KiCad).
Exercise: read an MPU-6050 IMU over I²C and display tilt angles.
