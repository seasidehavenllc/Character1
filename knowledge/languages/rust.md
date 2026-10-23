---
title: Rust
summary: Fast, memory-safe systems language — C/C++ speed without crashes from memory bugs; used for tools, back ends, embedded and game engines.
tags: [language, systems, performance, embedded, safety, cli]
---
# Rust

## Overview
Rust's compiler enforces memory safety through ownership and borrowing, so whole classes of bugs (use-after-free, data races) can't compile. It's as fast as C++, with excellent tooling (Cargo). The learning curve is steeper: the compiler is strict but its error messages are very helpful.

## Setup and running
- Install with rustup (rustup.rs). Check: `cargo --version`.
- New project: `cargo new app && cd app && cargo run`.
- Add a library: `cargo add serde`. Test: `cargo test`. Lint: `cargo clippy`. Format: `cargo fmt`.

## Core syntax
```rust
fn square(x: i32) -> i32 {
    x * x                          // last expression is returned (no semicolon)
}

fn main() {
    let name = "Tony";             // immutable by default
    let mut power = 100;           // mut to allow changes
    power -= 10;
    let mut suits = vec!["Mark I", "Mark II"];
    suits.push("Mark III");

    for (i, s) in suits.iter().enumerate() {
        println!("{i}: {s}");
    }
    if power > 50 {
        println!("{name} has {power}% power, {}", square(3));
    }
}
```

## Ownership and borrowing
```rust
fn length(s: &String) -> usize { s.len() }        // borrow: read without taking ownership
fn shout(s: &mut String) { s.push('!'); }        // mutable borrow: one at a time

fn demo() {
    let mut msg = String::from("hello");
    let n = length(&msg);
    shout(&mut msg);
    let moved = msg;                              // ownership moves; `msg` can't be used now
    println!("{moved} {n}");
}
```

## Enums, Option and Result
```rust
enum Command { Forward(u32), Turn(i32), Stop }

fn parse(s: &str) -> Result<u32, std::num::ParseIntError> {
    let n: u32 = s.trim().parse()?;               // ? returns the error early
    Ok(n)
}

fn run(c: Command) -> String {
    match c {                                     // match must cover every case
        Command::Forward(cm) => format!("forward {cm} cm"),
        Command::Turn(deg) => format!("turn {deg}°"),
        Command::Stop => "stop".to_string(),
    }
}
```

## Common mistakes
- Fighting the borrow checker by cloning everything; restructure so one owner holds the data and others borrow.
- `.unwrap()` everywhere; it panics on errors. Use `?`, `match`, or `.unwrap_or(...)`.
- Confusing `String` (owned) and `&str` (borrowed view).
- Indexing with the wrong integer type: indexes are `usize`.

## Learning path
### Level 1 — Basics
Variables, mutability, types, functions, `if`, loops, `Vec`, `String` vs `&str`. Read "The Rust Book" chapters 1–6.
Exercise: a guessing game with input parsing and error handling.

### Level 2 — Ownership and types
Ownership, borrowing, lifetimes basics, structs, enums, `match`, `Option`, `Result`, modules.
Exercise: a command-line to-do app storing tasks in a file.

### Level 3 — Abstraction
Traits, generics, iterators and closures, `HashMap`, error types, testing, crates (`serde`, `clap`).
Exercise: a CSV statistics tool with `clap` arguments and `serde`.

### Level 4 — Applied
Async (`tokio`, `axum` web APIs), concurrency (`Arc`, `Mutex`, channels), embedded (`embedded-hal`), WebAssembly, games (Bevy).
Exercise: a small web API with axum, or blink an LED on a microcontroller with embedded Rust.

## Complete example
```rust run
#[derive(Debug)]
enum Command {
    Forward(u32),
    Turn(i32),
    Stop,
}

fn parse(line: &str) -> Option<Command> {
    let mut parts = line.split_whitespace();
    match (parts.next()?, parts.next()) {
        ("forward", Some(n)) => n.parse().ok().map(Command::Forward),
        ("turn", Some(n)) => n.parse().ok().map(Command::Turn),
        ("stop", None) => Some(Command::Stop),
        _ => None,
    }
}

fn main() {
    let script = ["forward 50", "turn -90", "jump", "forward 20", "stop"];
    let (mut distance, mut heading) = (0u32, 0i32);
    for line in script {
        match parse(line) {
            Some(cmd) => {
                println!("{line:>12} -> {cmd:?}");
                match cmd {
                    Command::Forward(cm) => distance += cm,
                    Command::Turn(deg) => heading = (heading + deg).rem_euclid(360),
                    Command::Stop => break,
                }
            }
            None => println!("{line:>12} -> not understood"),
        }
    }
    println!("Travelled {distance} cm, now facing {heading}°");
}
```
