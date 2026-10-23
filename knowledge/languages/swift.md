---
title: Swift
summary: Apple's language for iPhone, iPad, Mac, Apple Watch and Vision Pro apps, with SwiftUI for interfaces.
tags: [language, mobile, ios, apple, macos, ui]
---
# Swift

## Overview
Swift is the main language for Apple platforms. With SwiftUI you describe the interface declaratively and it updates when data changes. Swift is safe (optionals prevent null crashes) and fast.

## Setup and running
- Requires a Mac with Xcode (free, Mac App Store) for iOS apps. Try code in an Xcode Playground.
- Command line: `swift main.swift`. Swift also runs on Linux and Windows for non-app code.
- Running on a real iPhone needs an Apple ID; publishing to the App Store needs the Apple Developer Program.

## Core syntax
```swift
let name = "Tony"                    // constant
var power = 100                      // variable
power -= 10
var suits = ["Mark I", "Mark II"]
suits.append("Mark III")
var levels: [String: Int] = ["Mark I": 40]

if power > 50 { print("\(name) has \(power)% power") }   // string interpolation
for (i, suit) in suits.enumerated() { print(i, suit) }

func greet(_ person: String, greeting: String = "Hello") -> String {
    "\(greeting), \(person)!"
}
print(greet("Pepper"))
```

## Optionals
```swift
let level: Int? = levels["Mark II"]          // might be nil
if let level { print("Level \(level)") } else { print("unknown") }
let safe = levels["Mark II"] ?? 0            // default value
```

## Structs, classes and protocols
```swift
protocol Movable { mutating func move(by cm: Int) }

struct Rover: Movable {                       // structs are copied; preferred in Swift
    var position = 0
    mutating func move(by cm: Int) { position += cm }
}
```

## SwiftUI
```swift
import SwiftUI

struct ContentView: View {
    @State private var power = 100
    var body: some View {
        VStack(spacing: 16) {
            Text("Power: \(power)%").font(.title)
            Button("Fly") { power = max(0, power - 10) }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }
}
```

## Common mistakes
- Force-unwrapping with `!` and crashing on nil; use `if let`, `guard let` or `??`.
- Mutating a struct without `var` / `mutating`.
- Updating UI from a background thread; mark UI code `@MainActor`.
- Strong reference cycles between classes (closures capturing `self`); use `[weak self]`.

## Learning path
### Level 1 — Basics
Constants, variables, types, optionals, control flow, functions, arrays and dictionaries.
Exercise: a tip calculator in a Playground.

### Level 2 — Types
Structs vs classes, enums with associated values, protocols, extensions, error handling (`throws`, `try`).
Exercise: model a deck of cards and shuffle/deal hands.

### Level 3 — SwiftUI apps
Views, layout stacks, `@State`, `@Binding`, `@Observable`, lists and navigation, async/await networking.
Exercise: a to-do app with add/delete and persistence (SwiftData).

### Level 4 — Shipping
App architecture, testing, accessibility, widgets, Core Bluetooth (robot remotes), App Store submission.
Exercise: a Bluetooth remote-control app for a robot, or publish a small app to TestFlight.
