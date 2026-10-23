# Corvis knowledge library

Courses Corvis teaches from, on every device, online or offline.

- `foundations/` — how to learn, how computers run code, Git, algorithms, debugging
- `languages/` — one course per programming language
- `robotics/` — electronics, Arduino, Raspberry Pi, motors, sensors, control, ROS 2, vision, safety

## Course format

```markdown
---
title: Python
summary: One line on what it's for.
tags: [language, beginner]
---
# Python
## Overview
## Setup and running
## Core syntax
## Common mistakes
## Learning path
### Level 1 — ...
### Level 2 — ...
## Complete example
```

Code blocks whose info string ends in ` run` (for example ```` ```python run ````) are complete
programs. `python tools/check_knowledge.py` compiles and runs every one of them with the
toolchains installed on your machine, so examples stay correct when you edit the library.

To add a course, drop a new `.md` file in the right folder. Corvis indexes it on the next start.
