---
title: Computer vision for robots
summary: Giving robots eyes with OpenCV — images as arrays, color tracking, contours, ArUco markers, and object detection with AI models.
tags: [robotics, vision, opencv, camera, ai, object-detection, python]
---
# Computer vision for robots

## Overview
A camera image is a grid of pixels (a NumPy array: height × width × 3 colors). OpenCV provides the tools to find colors, shapes, edges and markers. AI models (e.g. YOLO) detect objects like people, balls or cars. On a Raspberry Pi, keep resolutions small (320×240 or 640×480) for speed.

## Setup and running
`pip install opencv-python numpy` (on a Pi: `sudo apt install python3-opencv`, or `opencv-python` in a venv). Use a USB webcam with `cv2.VideoCapture(0)` or the Pi camera with `picamera2`.

## Color tracking (follow a ball)
```python
import cv2
import numpy as np

cap = cv2.VideoCapture(0)
while True:
    ok, frame = cap.read()
    if not ok:
        break
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)            # HSV separates color from brightness
    mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))   # green range
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        biggest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(biggest)
        center_x = x + w / 2
        error = center_x - frame.shape[1] / 2                # steer to make this 0 (PID!)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.imshow("view", frame)
    if cv2.waitKey(1) == ord("q"):
        break
cap.release()
cv2.destroyAllWindows()
```

## Useful techniques
- **Blur** (`cv2.GaussianBlur`) before thresholding to reduce noise.
- **Contours** for finding shapes and their sizes/positions.
- **ArUco markers** (`cv2.aruco`): printed square codes a robot can find and measure distance/angle to — great for docking and localization.
- **Calibration**: use a checkerboard to remove lens distortion before measuring things.
- **Object detection**: models like YOLO (via `ultralytics`) or MediaPipe find people, hands and objects; use small models on a Pi or an accelerator (Coral, Hailo).

## Common mistakes
- OpenCV uses BGR, not RGB, color order.
- Color thresholds that only work under one lighting; use HSV and test in different light.
- Processing full-resolution frames on a Pi; downscale first.
- Forgetting the robot moves: blur from motion, and lag between seeing and acting.

## Learning path
### Level 1 — Images
Loading images, pixels and NumPy, color spaces, drawing, the webcam loop.
Exercise: show the live camera with a crosshair and the FPS.

### Level 2 — Finding things
Thresholding, masks, blur, contours, bounding boxes.
Exercise: track a colored ball and print its position.

### Level 3 — Robot vision
Steering toward a target with PID, ArUco markers, camera calibration, running on a Pi.
Exercise: a robot that follows a colored ball.

### Level 4 — AI vision
Object detection (YOLO, MediaPipe), tracking across frames, depth cameras, ROS 2 image topics.
Exercise: a robot that follows a specific person.
