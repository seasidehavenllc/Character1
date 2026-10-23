---
title: Robotics fundamentals
summary: How every robot works — sense, think, act; the parts of a robot; choosing a platform; a roadmap from first blinking LED to autonomous robots.
tags: [robotics, beginner, sensors, actuators, roadmap, hardware]
---
# Robotics fundamentals

## Sense, think, act
Every robot runs the same loop many times per second:
1. **Sense** — read sensors (distance, light, buttons, encoders, camera, IMU).
2. **Think** — decide what to do (rules, state machines, control loops like PID, path planning, AI).
3. **Act** — drive actuators (motors, servos, LEDs, speakers).
Robots fail mostly at the boundaries: noisy sensors, weak power, slipping wheels. Good robot code expects imperfect data.

## Parts of a robot
| Part | Examples | Notes |
|---|---|---|
| Brain | Arduino (microcontroller), Raspberry Pi (computer), ESP32 (Wi-Fi/Bluetooth microcontroller), Jetson (AI) | Microcontrollers are simple and real-time; computers run Linux, Python, cameras, AI |
| Sensors | Ultrasonic (HC-SR04), IR line sensors, buttons, potentiometers, encoders, IMU (MPU-6050), camera, LiDAR | Each has range, accuracy and noise limits |
| Actuators | DC motors, servos, steppers, LEDs, buzzers | Motors need a driver board; never power them from a logic pin |
| Motor driver | L298N, TB6612FNG, DRV8833, ESCs for brushless | Takes small control signals, switches big currents |
| Power | Li-ion/LiPo packs, AA packs, buck converters | Separate (or well-filtered) power for motors; common ground |
| Chassis | 2-wheel differential drive kit, tracks, robot arm kit | Start with a 2-wheel kit |
| Communication | USB serial, I²C, SPI, UART, Bluetooth, Wi-Fi | How the brain talks to sensors and other computers |

## Choosing a platform
- **First robot:** Arduino Uno + 2-wheel chassis kit + L298N or TB6612 driver + HC-SR04 + line sensors. Cheap and forgiving.
- **Wireless / phone control:** ESP32 (Arduino-compatible, Wi-Fi and Bluetooth).
- **Camera, Python, AI:** Raspberry Pi 4/5 with a motor HAT; often paired with an Arduino for real-time motor control.
- **Research-grade / ROS 2:** Raspberry Pi 5 or Jetson running ROS 2, with LiDAR and encoders.

## Learning path
### Level 1 — First circuits
Blink an LED, read a button, read a potentiometer, print values over serial. (see `robotics/electronics`, `robotics/arduino`)
Exercise: a "traffic light" with three LEDs and a pedestrian button.

### Level 2 — Moving robot
Motor driver wiring, PWM speed control, differential drive (left/right wheels), a distance sensor.
Exercise: a robot that drives forward and turns away from obstacles.

### Level 3 — Smarter behavior
State machines, line following, PID control (`robotics/control-pid`), encoders and odometry (`robotics/kinematics`), Bluetooth remote control.
Exercise: a PID line follower that runs a full track smoothly.

### Level 4 — Autonomous robots
Raspberry Pi + camera (`robotics/computer-vision`), ROS 2 (`robotics/ros2`), mapping and path planning (`foundations/algorithms`), robot arms.
Exercise: a robot that follows a colored ball, or a ROS 2 robot that navigates a room.

## Complete example
```python run
# A sense-think-act loop with a simulated distance sensor and a simple state machine.
readings = [120, 90, 45, 25, 18, 60, 110]   # cm, as if read from an ultrasonic sensor

state = "cruise"
for distance in readings:                     # sense
    if distance < 20:                         # think
        state = "reverse"
    elif distance < 50:
        state = "turn"
    elif state != "cruise" and distance > 80:
        state = "cruise"
    left, right = {"cruise": (70, 70), "turn": (60, -60), "reverse": (-50, -50)}[state]   # act
    print(f"{distance:4d} cm -> {state:8s} motors L={left:+d} R={right:+d}")
```
