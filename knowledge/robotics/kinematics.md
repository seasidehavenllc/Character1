---
title: Robot motion and kinematics
summary: The math of how robots move — differential drive, encoders and odometry, coordinate frames, and robot arm forward/inverse kinematics.
tags: [robotics, kinematics, odometry, math, robot-arm, encoders, navigation]
---
# Robot motion and kinematics

## Differential drive (two-wheel robots)
Two independently driven wheels separated by the **wheel base** `L`. If the wheels move at `vL` and `vR`:
- forward speed `v = (vR + vL) / 2`
- turning rate `ω = (vR − vL) / L` (radians per second; positive = turning left)
Same speeds → straight. Opposite speeds → spin in place. To drive at `v` and `ω`: `vL = v − ω·L/2`, `vR = v + ω·L/2`.

## Encoders and odometry
Encoders count wheel rotation in "ticks". Distance per tick = π × wheel diameter / ticks per revolution. Adding up small movements estimates the robot's position `(x, y, θ)` — **odometry**. It drifts over time (wheel slip), so real robots correct it with an IMU, landmarks, LiDAR or cameras.

## Coordinate frames
Robots track positions in several frames: the world/map, the robot's base, each sensor. Converting between them uses rotation and translation (2D: rotate by θ, then shift by x, y). ROS 2 manages this with `tf2`.

## Robot arms
- **Forward kinematics**: joint angles → where the hand ends up. Straightforward trigonometry.
- **Inverse kinematics**: desired hand position → joint angles. Harder; may have zero, one or several solutions. For a 2-link planar arm there's a closed-form answer (law of cosines); bigger arms use numeric solvers (e.g. MoveIt).

## Learning path
### Level 1 — Moving on purpose
Wheel circumference, speed vs PWM, driving a set distance and turning a set angle.
Exercise: make the robot drive a 1 m square and measure how far off it ends.

### Level 2 — Differential drive math
`v`/`ω` ↔ wheel speeds, arcs, encoders.
Exercise: drive a circle of a chosen radius.

### Level 3 — Odometry
Integrating encoder ticks into `(x, y, θ)`, error sources, IMU fusion basics.
Exercise: display the robot's estimated position live and compare with reality.

### Level 4 — Arms and frames
2D/3D transforms, 2-link arm forward and inverse kinematics, servos, ROS 2 tf2 and MoveIt.
Exercise: a 2-servo arm that moves its pen tip to a point you click on screen.

## Complete example
```python run
import math


def odometry(ticks, wheel_diameter=0.065, ticks_per_rev=360, wheel_base=0.15):
    """Integrate (left_ticks, right_ticks) steps into an (x, y, heading) pose."""
    per_tick = math.pi * wheel_diameter / ticks_per_rev
    x = y = theta = 0.0
    for left, right in ticks:
        dl, dr = left * per_tick, right * per_tick
        d, dtheta = (dl + dr) / 2, (dr - dl) / wheel_base
        x += d * math.cos(theta + dtheta / 2)
        y += d * math.sin(theta + dtheta / 2)
        theta += dtheta
    return x, y, math.degrees(theta) % 360


def two_link_ik(x, y, l1=0.10, l2=0.08):
    """Joint angles (degrees) that put a 2-link arm's tip at (x, y), elbow-down."""
    c2 = (x * x + y * y - l1 * l1 - l2 * l2) / (2 * l1 * l2)
    if abs(c2) > 1:
        return None                                   # out of reach
    q2 = math.acos(c2)
    q1 = math.atan2(y, x) - math.atan2(l2 * math.sin(q2), l1 + l2 * math.cos(q2))
    return math.degrees(q1), math.degrees(q2)


steps = [(10, 10)] * 50 + [(-5, 5)] * 20 + [(10, 10)] * 30   # straight, turn left, straight
x, y, heading = odometry(steps)
print(f"Robot pose: x={x:.3f} m, y={y:.3f} m, heading={heading:.0f}°")
print("Arm angles to reach (0.12, 0.05):", tuple(round(a, 1) for a in two_link_ik(0.12, 0.05)))
print("Reach (0.30, 0.0)?", two_link_ik(0.30, 0.0))
```
