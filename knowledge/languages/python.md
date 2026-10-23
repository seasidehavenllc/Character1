---
title: Python
summary: Readable general-purpose language for automation, AI and data, web back ends, robotics (Raspberry Pi, ROS 2) and learning to code.
tags: [language, beginner, scripting, ai, data, robotics, backend]
---
# Python

## Overview
Python is easy to read and has a huge library ecosystem (`pip`). It's the main language of AI and data science, a common choice for robots (Raspberry Pi, ROS 2), web back ends (Django, FastAPI) and scripting. It's slower than compiled languages, which rarely matters for learning or glue code.

## Setup and running
- Install from python.org (Windows/Mac) or your package manager. Check with `python3 --version`.
- Run a file: `python3 hello.py`. Interactive shell: `python3`.
- Per-project packages: `python3 -m venv .venv`, activate it (`source .venv/bin/activate`, or `.venv\Scripts\activate` on Windows), then `pip install requests`.

## Core syntax
```python
name = "Tony"                     # variables need no type
age = 30
pi = 3.14
is_ready = True

if age >= 18:                     # indentation defines blocks
    print(f"{name} is an adult")  # f-strings insert values
elif age > 12:
    print("teen")
else:
    print("child")

for i in range(3):                # 0, 1, 2
    print(i)

count = 0
while count < 3:
    count += 1

def greet(person, greeting="Hello"):   # default argument
    return f"{greeting}, {person}!"

suits = ["Mark I", "Mark II"]     # list (ordered, changeable)
suits.append("Mark III")
armor = {"color": "red", "power": 100}  # dict (key -> value)
armor["power"] -= 10
squares = [n * n for n in range(5)]     # list comprehension
```

## Classes and errors
```python
class Robot:
    def __init__(self, name):
        self.name = name
        self.battery = 100

    def move(self, distance):
        if distance * 2 > self.battery:
            raise ValueError("not enough battery")
        self.battery -= distance * 2

bot = Robot("Dummy")
try:
    bot.move(80)
except ValueError as err:
    print("Can't move:", err)
```

## Files and modules
```python
from pathlib import Path
import json

Path("notes.txt").write_text("hello\n")
data = json.loads('{"x": 1}')
with open("notes.txt") as f:      # 'with' closes the file automatically
    for line in f:
        print(line.strip())
```

## Common mistakes
- Mixing tabs and spaces, or wrong indentation: use 4 spaces.
- `=` assigns, `==` compares.
- Lists are copied by reference: `b = a` doesn't copy; use `b = a.copy()`.
- Mutable default arguments (`def f(items=[])`) are shared between calls; use `None` and create the list inside.
- `input()` always returns a string: convert with `int(...)`.
- Installing packages globally instead of in a virtual environment.

## Learning path
### Level 1 — Basics
Variables, numbers, strings, `print`, `input`, `if/elif/else`, `for` and `while` loops.
Exercise: a number-guessing game (`import random`, `random.randint(1, 100)`) that says "higher" or "lower".

### Level 2 — Functions and collections
Functions, return values, lists, dicts, sets, tuples, comprehensions, reading/writing files.
Exercise: a to-do list program that saves tasks to a JSON file and loads them on start.

### Level 3 — Programs that scale
Classes, modules and packages, exceptions, virtual environments and `pip`, testing with `pytest`, type hints.
Exercise: turn the to-do app into a module with a `Task` class and three pytest tests.

### Level 4 — Real projects
Pick a track: web API (FastAPI), game (pygame), data/AI (pandas, scikit-learn), automation (requests, scheduling), robotics (Raspberry Pi GPIO, ROS 2 `rclpy`).
Exercise: build and ship one small project in the chosen track.

## Complete example
```python run
from dataclasses import dataclass


@dataclass
class Task:
    title: str
    done: bool = False


def summary(tasks: list[Task]) -> str:
    done = sum(t.done for t in tasks)
    return f"{done}/{len(tasks)} tasks done"


tasks = [Task("Build arc reactor"), Task("Test thrusters", done=True)]
tasks[0].done = True
print(summary(tasks))
for t in tasks:
    print(("[x] " if t.done else "[ ] ") + t.title)
```
