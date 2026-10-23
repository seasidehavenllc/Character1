---
title: C
summary: Small, fast, close-to-the-hardware language behind operating systems, microcontrollers, drivers and embedded robotics.
tags: [language, systems, embedded, robotics, performance, memory]
---
# C

## Overview
C gives direct control over memory and hardware with almost no overhead. Operating systems, firmware and most microcontroller code are written in C (Arduino uses C++, which builds on it). The trade-off: you manage memory yourself, and mistakes can crash programs or create security bugs.

## Setup and running
- Linux: `sudo apt install build-essential`. Mac: `xcode-select --install`. Windows: MSYS2 (gcc) or Visual Studio.
- Compile and run: `gcc -Wall -Wextra -std=c11 main.c -o main && ./main`.
- Turn on warnings always; add `-g -fsanitize=address,undefined` while learning to catch memory bugs.

## Core syntax
```c
#include <stdio.h>

int square(int x) { return x * x; }       // functions declare their types

int main(void) {
    int power = 100;
    double voltage = 11.1;
    char grade = 'A';
    const char *name = "Tony";            // a string is a pointer to chars ending in '\0'

    if (power > 50) {
        printf("%s: %d%% power, %.1f V, grade %c\n", name, power, voltage, grade);
    }
    for (int i = 0; i < 3; i++) {
        printf("%d squared is %d\n", i, square(i));
    }
    int readings[5] = {3, 1, 4, 1, 5};    // fixed-size array
    printf("first reading: %d\n", readings[0]);
    return 0;                             // 0 = success
}
```

## Pointers and memory
```c
#include <stdlib.h>

void reset(int *value) { *value = 0; }   // pointer lets a function change the caller's variable

int *make_buffer(size_t n) {
    int *buf = malloc(n * sizeof *buf);  // heap memory: you must free it
    if (buf == NULL) return NULL;        // malloc can fail
    for (size_t i = 0; i < n; i++) buf[i] = 0;
    return buf;
}
// caller: int *b = make_buffer(10); ... free(b);
```

## Structs
```c
typedef struct {
    int left_speed;
    int right_speed;
} Motors;

void stop(Motors *m) { m->left_speed = 0; m->right_speed = 0; }   // -> accesses through a pointer
```

## Common mistakes
- Reading or writing past the end of an array (no bounds checking).
- Forgetting `free` (leak) or using memory after `free` (crash).
- Uninitialized variables contain garbage.
- `scanf`/`gets` buffer overflows: use `fgets` and check sizes.
- Integer overflow and integer division (`5 / 2 == 2`).
- Comparing strings with `==`; use `strcmp`.

## Learning path
### Level 1 — Basics
Types, `printf`, `if`, loops, functions, arrays, compiling with warnings.
Exercise: a temperature converter table from -20 °C to 40 °C in steps of 5.

### Level 2 — Pointers and strings
Pointers, addresses, passing by pointer, strings and `string.h`, `fgets`, structs.
Exercise: a program that reads a line and counts vowels, words and digits.

### Level 3 — Memory and files
`malloc/free`, dynamic arrays, linked lists, file I/O, header files and multi-file programs, Makefiles, sanitizers and `gdb`.
Exercise: a contact book saved to a file, with a dynamic array that grows.

### Level 4 — Embedded and systems
Bitwise operations, registers, interrupts, fixed-point math; microcontrollers (Arduino, STM32, Raspberry Pi Pico C SDK); or Linux system calls.
Exercise: blink an LED and read a button on a microcontroller using direct register access.

## Complete example
```c run
#include <stdio.h>

typedef struct {
    const char *name;
    int distance_cm;
} Sensor;

static int closest(const Sensor *sensors, int count) {
    int best = 0;
    for (int i = 1; i < count; i++) {
        if (sensors[i].distance_cm < sensors[best].distance_cm) best = i;
    }
    return best;
}

int main(void) {
    Sensor sensors[] = {{"front", 42}, {"left", 17}, {"right", 88}};
    int n = (int)(sizeof sensors / sizeof sensors[0]);
    int i = closest(sensors, n);
    printf("Closest obstacle: %s at %d cm\n", sensors[i].name, sensors[i].distance_cm);
    return 0;
}
```
