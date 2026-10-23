---
title: C++
summary: High-performance language for games (Unreal), robotics (ROS 2, Arduino), simulations, graphics and performance-critical software.
tags: [language, systems, games, robotics, arduino, unreal, performance]
---
# C++

## Overview
C++ is C plus classes, templates and a large standard library. It powers game engines (Unreal), robotics (ROS 2, Arduino sketches are C++), browsers and trading systems. Modern C++ (C++17/20) avoids manual memory management with containers and smart pointers.

## Setup and running
- Compiler: `g++` or `clang++` (Linux/Mac), Visual Studio on Windows.
- `g++ -std=c++17 -Wall -Wextra main.cpp -o main && ./main`.
- Bigger projects use CMake: `cmake -B build && cmake --build build`.

## Core syntax
```cpp
#include <iostream>
#include <string>
#include <vector>

int main() {
    std::string name = "Tony";
    std::vector<int> readings = {3, 1, 4};   // growable array
    readings.push_back(1);

    for (int r : readings) std::cout << r << ' ';   // range-for
    std::cout << '\n';

    auto total = 0;                           // auto infers the type
    for (std::size_t i = 0; i < readings.size(); ++i) total += readings[i];
    std::cout << name << " total: " << total << '\n';
}
```

## Classes, references and smart pointers
```cpp
#include <memory>
#include <string>

class Motor {
public:
    explicit Motor(std::string name) : name_(std::move(name)) {}
    void set_speed(int s) { speed_ = s < -100 ? -100 : (s > 100 ? 100 : s); }
    int speed() const { return speed_; }      // const: doesn't change the object
private:
    std::string name_;
    int speed_ = 0;
};

void stop(Motor& m) { m.set_speed(0); }       // reference: no copy, can modify

auto left = std::make_unique<Motor>("left");  // freed automatically
```

## Common mistakes
- Using raw `new`/`delete`; prefer containers, `std::unique_ptr`, `std::make_unique`.
- Dangling references to objects that went out of scope.
- Copying large objects by value; pass `const T&`.
- Mixing signed and unsigned in comparisons (`int` vs `size_t`).
- Undefined behavior (out-of-bounds, uninitialized values) that "works" until it doesn't. Use `-fsanitize=address,undefined` while developing.

## Learning path
### Level 1 — Basics
Types, `iostream`, `std::string`, control flow, functions, `std::vector`.
Exercise: a grade calculator that reads scores and prints average and letter grade.

### Level 2 — Classes and the standard library
Classes, constructors, references, `const`, `std::map`, `std::unordered_map`, algorithms (`std::sort`, `std::find_if`), lambdas.
Exercise: an inventory system with a `Part` class and sorting by price.

### Level 3 — Modern C++ and tooling
RAII, smart pointers, move semantics, templates basics, CMake, unit tests (GoogleTest/Catch2), debugging.
Exercise: a multi-file project built with CMake, with tests.

### Level 4 — Applied
Pick a track: robotics (ROS 2 `rclcpp`, Arduino), games (Unreal, SFML), performance (profiling, multithreading).
Exercise: a ROS 2 node or an SFML mini-game.

## Complete example
```cpp run
#include <algorithm>
#include <iostream>
#include <string>
#include <vector>

struct Part {
    std::string name;
    double price;
};

int main() {
    std::vector<Part> parts = {{"arc reactor", 1200.0}, {"repulsor", 450.5}, {"servo", 35.0}};
    std::sort(parts.begin(), parts.end(), [](const Part& a, const Part& b) { return a.price < b.price; });

    double total = 0;
    for (const auto& p : parts) {
        std::cout << p.name << ": $" << p.price << '\n';
        total += p.price;
    }
    std::cout << "Total: $" << total << '\n';
    return 0;
}
```
