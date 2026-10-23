---
title: PID control
summary: Making robots move smoothly and accurately — feedback control, the P, I and D terms, tuning, and common pitfalls.
tags: [robotics, control, pid, feedback, line-follower, motors]
---
# PID control

## The idea
A controller compares where you are with where you want to be (the **error**) and adjusts the output to shrink it, many times per second. Used for line following, wheel speed, balancing robots, drone stabilization, robot arm joints, heating.

- **P (proportional)**: output ∝ current error. Bigger error → bigger correction. Too much P → oscillation.
- **I (integral)**: adds up past error. Removes steady offsets (a robot that always drifts slightly). Too much I → overshoot and slow wobbles.
- **D (derivative)**: reacts to how fast the error changes. Dampens overshoot. Sensitive to noise.

output = Kp·error + Ki·∑error·dt + Kd·(Δerror/dt)

## Tuning by hand
1. Set Ki = Kd = 0. Increase Kp until the system responds quickly but starts to oscillate; back off ~30–50%.
2. Increase Kd to calm the overshoot.
3. Add a small Ki only if there's a steady error left.
4. Change one gain at a time and log the error so you can see the effect.

## Pitfalls
- **Integral windup**: when the output is saturated (motor at max), the integral keeps growing and causes a big overshoot later. Clamp the integral.
- **Noisy derivative**: filter the measurement, or take the derivative of the measurement instead of the error.
- **Inconsistent timing**: compute `dt` each loop, or run the loop at a fixed rate.
- **Wrong sign**: if the robot steers *into* the error, flip the output sign.

## Learning path
### Level 1 — Feedback
Open-loop vs closed-loop; bang-bang control (on/off thermostat).
Exercise: a line follower with simple left/right rules; note how it wobbles.

### Level 2 — P and PD
Proportional steering, then add D.
Exercise: replace the rules with a PD controller on the line position.

### Level 3 — Full PID
Integral with anti-windup, fixed loop rate, logging and plotting the error.
Exercise: hold a wheel at a target RPM using an encoder, under different loads.

### Level 4 — Beyond PID
Cascaded loops (position → velocity), feedforward, state-space control, Kalman filters, balancing robots.
Exercise: a self-balancing two-wheel robot.

## Complete example
```python run
class PID:
    def __init__(self, kp, ki, kd, limit):
        self.kp, self.ki, self.kd, self.limit = kp, ki, kd, limit
        self.integral = 0.0
        self.prev_error = None

    def update(self, target, measured, dt):
        error = target - measured
        self.integral = max(-self.limit, min(self.limit, self.integral + error * dt))  # anti-windup
        derivative = 0.0 if self.prev_error is None else (error - self.prev_error) / dt
        self.prev_error = error
        out = self.kp * error + self.ki * self.integral + self.kd * derivative
        return max(-self.limit, min(self.limit, out))


# Simulated wheel: speed responds to motor power with lag and friction.
pid, speed, dt = PID(kp=0.8, ki=2.0, kd=0.02, limit=100), 0.0, 0.05
for step in range(61):
    power = pid.update(target=60, measured=speed, dt=dt)
    speed += (power * 1.5 - speed * 0.5 - 5) * dt * 2      # simple physics
    if step % 10 == 0:
        print(f"t={step * dt:4.1f}s power={power:6.1f} speed={speed:5.1f} rpm")
```
