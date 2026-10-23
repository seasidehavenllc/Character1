"""Robot body: Corvis inside a physical machine.

The RobotBody enforces safety limits and exposes motion/sensor tools to the brain.
The actual hardware is behind a RobotDriver, so the same Corvis can drive:
  - SimulatedDriver  : no hardware, logs what would happen (default, safe for testing)
  - Ros2Driver       : publishes geometry_msgs/Twist on /cmd_vel (needs ROS 2 + rclpy)
Write your own driver (serial to an Arduino, a Raspberry Pi GPIO rover, etc.) by
subclassing RobotDriver.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from .base import Body


class RobotDriver(ABC):
    @abstractmethod
    def drive(self, linear_mps: float, angular_dps: float, duration_s: float) -> None: ...

    @abstractmethod
    def look(self, pan_deg: float, tilt_deg: float) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    def sensors(self) -> dict[str, Any]:
        return {}


class SimulatedDriver(RobotDriver):
    def __init__(self) -> None:
        self.log: list[str] = []
        self.x = self.y = self.heading = 0.0

    def drive(self, linear_mps: float, angular_dps: float, duration_s: float) -> None:
        import math

        self.heading = (self.heading + angular_dps * duration_s) % 360
        self.x += linear_mps * duration_s * math.cos(math.radians(self.heading))
        self.y += linear_mps * duration_s * math.sin(math.radians(self.heading))
        self.log.append(f"drive {linear_mps:+.2f} m/s, {angular_dps:+.0f} deg/s for {duration_s:.1f}s")

    def look(self, pan_deg: float, tilt_deg: float) -> None:
        self.log.append(f"look pan={pan_deg:.0f} tilt={tilt_deg:.0f}")

    def stop(self) -> None:
        self.log.append("stop")

    def sensors(self) -> dict[str, Any]:
        return {
            "simulated": True,
            "pose": {"x_m": round(self.x, 2), "y_m": round(self.y, 2), "heading_deg": round(self.heading)},
            "battery_pct": 100,
        }


class Ros2Driver(RobotDriver):
    """Minimal ROS 2 bridge. Requires a sourced ROS 2 install (rclpy, geometry_msgs)."""

    def __init__(self, cmd_vel_topic: str = "/cmd_vel") -> None:
        import rclpy
        from geometry_msgs.msg import Twist

        rclpy.init()
        self._rclpy = rclpy
        self._Twist = Twist
        self.node = rclpy.create_node("corvis")
        self.pub = self.node.create_publisher(Twist, cmd_vel_topic, 10)

    def drive(self, linear_mps: float, angular_dps: float, duration_s: float) -> None:
        import math

        msg = self._Twist()
        msg.linear.x = float(linear_mps)
        msg.angular.z = math.radians(angular_dps)
        end = time.monotonic() + duration_s
        while time.monotonic() < end:
            self.pub.publish(msg)
            time.sleep(0.1)
        self.stop()

    def look(self, pan_deg: float, tilt_deg: float) -> None:
        pass  # wire to your pan/tilt servo topic

    def stop(self) -> None:
        self.pub.publish(self._Twist())


class RobotBody(Body):
    name = "robot"

    def __init__(self, driver: RobotDriver, max_speed_mps: float = 0.5,
                 max_turn_dps: float = 90.0, max_duration_s: float = 5.0):
        self.driver = driver
        self.max_speed = float(max_speed_mps)
        self.max_turn = float(max_turn_dps)
        self.max_duration = float(max_duration_s)

    def describe(self) -> str:
        kind = "a SIMULATED robot (no real hardware)" if isinstance(self.driver, SimulatedDriver) else "a physical robot"
        return (
            f"You are inside {kind}. You can drive, turn, look around and read sensors with "
            f"your tools. Hard limits: {self.max_speed} m/s, {self.max_turn} deg/s, "
            f"{self.max_duration}s per command — requests beyond them are clamped. "
            "Only report a movement as done after the tool confirms it."
        )

    def tools(self) -> list[dict[str, Any]]:
        num = {"type": "number"}
        return [
            {
                "name": "drive",
                "description": "Move the robot. Positive linear = forward; positive angular = turn left. "
                "Use angular only (linear 0) to rotate in place.",
                "input_schema": {
                    "type": "object",
                    "properties": {"linear_mps": num, "angular_dps": num, "duration_s": num},
                    "required": ["linear_mps", "angular_dps", "duration_s"],
                },
            },
            {
                "name": "look",
                "description": "Point the head/camera. 0,0 is straight ahead.",
                "input_schema": {
                    "type": "object",
                    "properties": {"pan_deg": num, "tilt_deg": num},
                    "required": ["pan_deg", "tilt_deg"],
                },
            },
            {
                "name": "stop",
                "description": "Stop all motion immediately.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "read_sensors",
                "description": "Read the robot's current sensor values (pose, battery, distance, etc.).",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    @staticmethod
    def _clamp(v: float, limit: float) -> float:
        return max(-limit, min(limit, float(v)))

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "drive":
            lin = self._clamp(tool_input["linear_mps"], self.max_speed)
            ang = self._clamp(tool_input["angular_dps"], self.max_turn)
            dur = max(0.0, min(self.max_duration, float(tool_input["duration_s"])))
            self.driver.drive(lin, ang, dur)
            return f"Drove at {lin} m/s, {ang} deg/s for {dur}s. Now stopped."
        if tool_name == "look":
            self.driver.look(self._clamp(tool_input["pan_deg"], 90), self._clamp(tool_input["tilt_deg"], 45))
            return "Head moved."
        if tool_name == "stop":
            self.emergency_stop()
            return "All motion stopped."
        if tool_name == "read_sensors":
            return str(self.driver.sensors())
        return super().execute(tool_name, tool_input)

    def emergency_stop(self) -> None:
        self.driver.stop()
