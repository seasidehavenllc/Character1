---
title: ROS 2
summary: The Robot Operating System — nodes, topics, services, actions, launch files, tf2, simulation (Gazebo) and navigation (Nav2) for serious robots.
tags: [robotics, ros2, middleware, navigation, simulation, python, cpp]
---
# ROS 2

## Overview
ROS 2 is a framework (not an OS) for building robot software from many small programs called **nodes** that exchange messages. It gives you drivers, visualization (RViz), simulation (Gazebo), mapping and navigation (Nav2), arm planning (MoveIt) and a huge community. Write nodes in Python (`rclpy`) or C++ (`rclcpp`).

## Setup and running
- Use the Ubuntu version that matches a ROS 2 LTS release (e.g. ROS 2 Jazzy on Ubuntu 24.04). Install per docs.ros.org; on other OSes use Docker or a VM.
- Every terminal: `source /opt/ros/jazzy/setup.bash`.
- Workspace: `mkdir -p ~/ros2_ws/src && cd ~/ros2_ws`, create packages in `src/`, build with `colcon build`, then `source install/setup.bash`.

## Core concepts
| Concept | What it is | Example |
|---|---|---|
| Node | One process with one job | camera driver, motor controller, planner |
| Topic | Many-to-many stream of messages | `/cmd_vel` (velocity commands), `/scan` (LiDAR) |
| Service | Request → response | "reset odometry" |
| Action | Long task with feedback and cancel | "navigate to the kitchen" |
| Parameter | Node setting changeable at runtime | max speed |
| tf2 | Coordinate frame tree | map → odom → base_link → laser |
| Launch file | Starts many nodes with settings | `ros2 launch my_robot bringup.launch.py` |

## A Python node
```python
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Range


class Avoider(Node):
    def __init__(self):
        super().__init__("avoider")
        self.declare_parameter("stop_distance", 0.3)
        self.cmd = self.create_publisher(Twist, "/cmd_vel", 10)
        self.create_subscription(Range, "/front_range", self.on_range, 10)

    def on_range(self, msg: Range):
        twist = Twist()
        if msg.range < self.get_parameter("stop_distance").value:
            twist.angular.z = 1.0          # turn left (rad/s)
        else:
            twist.linear.x = 0.2           # forward (m/s)
        self.cmd.publish(twist)


def main():
    rclpy.init()
    rclpy.spin(Avoider())
    rclpy.shutdown()
```

## Command-line tools
```bash
ros2 node list
ros2 topic list
ros2 topic echo /cmd_vel
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}" --once
ros2 run turtlesim turtlesim_node        # a friendly practice robot
ros2 run teleop_twist_keyboard teleop_twist_keyboard
rviz2                                     # visualize sensors, maps, frames
```

## Common mistakes
- Forgetting to `source` the setup files in a new terminal ("package not found").
- Mismatched message types between publisher and subscriber.
- Mixing ROS 2 distributions (Humble vs Jazzy) on one robot.
- Blocking inside callbacks (sleeps, long loops), freezing the node; use timers.
- Wrong frame IDs / missing transforms so RViz shows nothing.
- Units: ROS uses metres, radians and seconds everywhere.

## Learning path
### Level 1 — Concepts with turtlesim
Install, nodes, topics, services, the CLI tools, turtlesim and teleop.
Exercise: draw a square with turtlesim by publishing `/turtle1/cmd_vel`.

### Level 2 — Your own nodes
Packages, publishers, subscribers, timers, parameters, custom messages, launch files.
Exercise: an obstacle-avoider node (above) tested in simulation.

### Level 3 — Simulation and the robot model
URDF robot descriptions, tf2, Gazebo simulation, RViz, `ros2_control`.
Exercise: model your 2-wheel robot in URDF and drive it in Gazebo.

### Level 4 — Autonomy
SLAM mapping (slam_toolbox), Nav2 navigation, MoveIt for arms, running on a Pi/Jetson with real sensors.
Exercise: map a room and send the robot to points on the map.
