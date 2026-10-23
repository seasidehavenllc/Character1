---
title: Java
summary: Mature object-oriented language for Android, large business back ends, Minecraft mods and FRC robotics (WPILib).
tags: [language, backend, android, enterprise, robotics, oop]
---
# Java

## Overview
Java runs on the JVM, so the same compiled program runs on any OS. It's used for enterprise back ends (Spring), Android (alongside Kotlin), big-data tools, Minecraft mods and FIRST Robotics Competition robots (WPILib). It's strongly typed and object-oriented.

## Setup and running
- Install a JDK (e.g. Eclipse Temurin 21). Check: `java -version`.
- Single file: `java Main.java` (Java 11+ compiles and runs it).
- Projects: Gradle or Maven, usually through IntelliJ IDEA.

## Core syntax
```java
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class Main {
    static int square(int x) { return x * x; }

    public static void main(String[] args) {
        String name = "Tony";
        int power = 100;
        var suits = new ArrayList<String>();          // var: inferred type
        suits.add("Mark I");
        Map<String, Integer> levels = new HashMap<>();
        levels.put("Mark I", 40);

        if (power > 50) System.out.println(name + " is ready");
        for (String s : suits) System.out.println(s + " -> " + levels.get(s));
        for (int i = 0; i < 3; i++) System.out.println(square(i));
    }
}
```

## Classes, interfaces and records
```java
interface Movable { void move(int cm); }

class Rover implements Movable {
    private int position = 0;
    @Override public void move(int cm) { position += cm; }
    public int getPosition() { return position; }
}

record Reading(String sensor, double value) {}   // immutable data class (Java 16+)
```

## Common mistakes
- Comparing strings with `==` (compares references); use `.equals()`.
- `NullPointerException`: check for null or use `Optional`.
- Integer division (`5 / 2 == 2`); use `5 / 2.0`.
- Catching `Exception` and ignoring it.
- Using raw types (`List` instead of `List<String>`).

## Learning path
### Level 1 — Basics
Types, strings, `if`, loops, methods, arrays, `Scanner` for input.
Exercise: a quiz program with five questions and a score.

### Level 2 — Objects
Classes, constructors, encapsulation, inheritance, interfaces, `ArrayList`, `HashMap`, exceptions.
Exercise: a library system with `Book` and `Member` classes and borrowing rules.

### Level 3 — Professional Java
Generics, records, enums, streams and lambdas, Gradle, JUnit tests, packages.
Exercise: rewrite the library with streams for searching and add JUnit tests.

### Level 4 — Applied
Pick a track: Spring Boot REST API, Android app, FRC robot code with WPILib, Minecraft mod.
Exercise: a Spring Boot API with a database, or a WPILib command-based drive subsystem.

## Complete example
```java run
import java.util.List;

public class Main {
    record Reading(String sensor, double value) {}

    public static void main(String[] args) {
        List<Reading> readings = List.of(
            new Reading("front", 42.0), new Reading("left", 17.5), new Reading("right", 88.0));
        double average = readings.stream().mapToDouble(Reading::value).average().orElse(0);
        Reading closest = readings.stream()
            .min((a, b) -> Double.compare(a.value(), b.value())).orElseThrow();
        System.out.printf("Average %.1f cm, closest: %s%n", average, closest.sensor());
    }
}
```
