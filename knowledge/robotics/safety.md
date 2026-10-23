---
title: Robot safety
summary: Building and testing robots without hurting people or hardware — emergency stops, batteries, speed limits, failsafes and safe testing habits.
tags: [robotics, safety, batteries, emergency-stop, failsafe, testing]
---
# Robot safety

## Rules that always apply
- **Emergency stop first.** Every moving robot needs a way to cut motor power instantly: a physical switch on the battery line for anything bigger than a toy, plus a software stop command.
- **Fail safe.** If communication is lost (Wi-Fi drops, the controlling program crashes), motors must stop. Use a watchdog: stop if no command has arrived in, say, 500 ms.
- **Limit speed and force** in code, especially while testing. Raise limits only after behavior is proven.
- **Test with wheels off the ground** (robot on a box) the first time new motor code runs.
- **Keep hands, hair and loose clothing away** from moving parts; power off before adjusting.
- **Never point lasers at eyes**; check LiDAR safety class.

## Batteries
- LiPo and Li-ion packs store a lot of energy. Use a proper balance charger, never charge unattended, charge on a non-flammable surface (a LiPo bag), and never use a puffy or damaged pack.
- Don't over-discharge: use a low-voltage cutoff or monitor.
- Fuse the main battery line, and make sure wires are thick enough for the current.

## Software safety patterns
```python run
import time


class MotorSafety:
    """Clamps commands and stops the motors if commands stop arriving (watchdog)."""

    def __init__(self, max_speed=0.5, timeout_s=0.5):
        self.max_speed, self.timeout_s = max_speed, timeout_s
        self.last_command = time.monotonic()
        self.stopped = False

    def command(self, speed):
        self.last_command = time.monotonic()
        self.stopped = False
        return max(-self.max_speed, min(self.max_speed, speed))

    def check(self):
        if time.monotonic() - self.last_command > self.timeout_s:
            self.stopped = True
        return 0.0 if self.stopped else None


safety = MotorSafety(timeout_s=0.05)
print("requested 2.0 m/s ->", safety.command(2.0), "m/s")
time.sleep(0.1)                                    # controller went silent
print("after silence, motor output:", safety.check(), "(stopped:", safety.stopped, ")")
```

## Learning path
### Level 1 — Habits
E-stop switch, wheels-off-the-ground testing, safe battery charging and storage.
Exercise: add a physical power switch and a software stop command to your first robot.

### Level 2 — Failsafes
Speed limits in code, communication watchdogs, sensor sanity checks.
Exercise: make the robot stop automatically when the Bluetooth remote disconnects.

### Level 3 — Bigger robots
Fuses and wiring gauge, current limits, bumpers and limit switches, safe arm workspaces.
Exercise: add limit switches so an arm can't move past its safe range.

### Level 4 — Robots near people
Risk assessment, standards awareness (ISO 10218 / ISO 13482), redundant stops, logging incidents.
Exercise: write a one-page risk assessment for your robot.
