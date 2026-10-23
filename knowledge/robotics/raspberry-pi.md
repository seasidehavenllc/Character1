---
title: Raspberry Pi for robots
summary: Using a Raspberry Pi as a robot's brain — setup, SSH, GPIO in Python with gpiozero, motors, cameras, talking to an Arduino, auto-start.
tags: [robotics, raspberry-pi, python, linux, gpio, camera]
---
# Raspberry Pi for robots

## Overview
A Raspberry Pi is a small Linux computer. Compared with an Arduino it can run Python, cameras, AI models, Wi-Fi and ROS 2, but it isn't real-time and its pins are 3.3 V only. A common design: Pi for "thinking" (vision, planning), Arduino or a motor HAT for precise motor control.

## Setup and running
- Flash Raspberry Pi OS with **Raspberry Pi Imager**; in its settings, enable SSH, set a username/password and Wi-Fi.
- Connect: `ssh pi@raspberrypi.local` (or the Pi's IP address). Edit code with VS Code's "Remote - SSH".
- Update: `sudo apt update && sudo apt full-upgrade`. Python libraries: create a venv with `python3 -m venv --system-site-packages .venv`.

## GPIO with gpiozero
Pin numbers below are BCM GPIO numbers (not physical pin positions).
```python
from gpiozero import LED, Button, DistanceSensor, Robot
from signal import pause

led = LED(17)
button = Button(2)                              # wired between GPIO2 and GND
button.when_pressed = led.toggle

sensor = DistanceSensor(echo=24, trigger=23)    # HC-SR04: echo needs a voltage divider to 3.3 V!
robot = Robot(left=(4, 14), right=(17, 18))     # two motors via a driver board

def check():
    if sensor.distance < 0.25:                  # metres
        robot.right(0.6)
    else:
        robot.forward(0.7)
pause()
```

## Camera
```python
from picamera2 import Picamera2
cam = Picamera2()
cam.start()
frame = cam.capture_array()                     # a NumPy image for OpenCV
```

## Talking to an Arduino
```python
import serial                                   # pip install pyserial
arduino = serial.Serial("/dev/ttyACM0", 115200, timeout=1)
arduino.write(b"drive 150 150\n")
reply = arduino.readline().decode().strip()
```

## Start the robot program on boot (systemd)
```ini
# /etc/systemd/system/robot.service
[Unit]
Description=Robot program
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/robot
ExecStart=/home/pi/robot/.venv/bin/python main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
Enable it: `sudo systemctl enable --now robot`. Logs: `journalctl -u robot -f`.

## Common mistakes
- Feeding 5 V into GPIO pins (permanent damage). Use voltage dividers or level shifters.
- Weak power supply: use the official supply; under-voltage causes random crashes. Power motors separately.
- Pulling the power without shutting down, corrupting the SD card: `sudo shutdown now`.
- Confusing BCM numbers with physical pin numbers.
- Expecting precise microsecond timing from Python on Linux; offload that to a microcontroller.

## Learning path
### Level 1 — The Pi as a computer
Imaging, SSH, the terminal (`languages/bash`), Python on the Pi.
Exercise: set up a headless Pi and run a Python script over SSH.

### Level 2 — GPIO
LEDs, buttons, gpiozero, PWM, a distance sensor with a voltage divider.
Exercise: a parking sensor that beeps faster as an object gets closer.

### Level 3 — Robot brain
Motor driver HAT or Arduino over serial, camera with OpenCV, systemd auto-start, a web or Bluetooth remote.
Exercise: a camera robot you drive from a phone browser with a live video feed.

### Level 4 — Autonomy
ROS 2 on the Pi, LiDAR, mapping, on-device AI (object detection).
Exercise: a robot that follows a person using object detection.
