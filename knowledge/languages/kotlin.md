---
title: Kotlin
summary: Modern language for Android apps (Jetpack Compose), also used on servers and for cross-platform apps; works with all Java code.
tags: [language, mobile, android, backend, jvm]
---
# Kotlin

## Overview
Kotlin is Google's recommended language for Android. It runs on the JVM, works with any Java library, and is more concise and null-safe than Java. Jetpack Compose builds Android interfaces in Kotlin; Kotlin Multiplatform shares code with iOS.

## Setup and running
- Android apps: install Android Studio, create an "Empty Activity" (Compose) project, run on an emulator or phone.
- Try code online at play.kotlinlang.org, or install the compiler (`kotlinc`).
- Projects build with Gradle (`./gradlew build`).

## Core syntax
```kotlin
fun square(x: Int) = x * x

fun main() {
    val name = "Tony"                  // val: read-only
    var power = 100                    // var: changeable
    power -= 10
    val suits = mutableListOf("Mark I", "Mark II")
    suits += "Mark III"
    val levels = mapOf("Mark I" to 40)

    if (power > 50) println("$name has $power% power")
    for ((i, s) in suits.withIndex()) println("$i $s ${levels[s] ?: "?"}")
    val strong = suits.filter { it.endsWith("II") }
    println(strong + square(4))
}
```

## Null safety and classes
```kotlin
data class Reading(val sensor: String, val cm: Double)   // equals/toString/copy for free

fun describe(r: Reading?): String =
    r?.let { "${it.sensor}: ${it.cm} cm" } ?: "no reading"   // ?. safe call, ?: default

sealed interface Command {
    data class Forward(val cm: Int) : Command
    data object Stop : Command
}
```

## Jetpack Compose
```kotlin
@Composable
fun PowerScreen() {
    var power by remember { mutableIntStateOf(100) }
    Column(Modifier.padding(16.dp)) {
        Text("Power: $power%", style = MaterialTheme.typography.headlineMedium)
        Button(onClick = { power = maxOf(0, power - 10) }) { Text("Fly") }
    }
}
```

## Common mistakes
- Using `!!` to force non-null; it crashes on null. Prefer `?.`, `?:` and `let`.
- Doing network work on the main thread; use coroutines (`viewModelScope.launch`).
- Storing UI state in the Activity instead of a ViewModel, losing it on rotation.
- `var` everywhere; prefer `val`.

## Learning path
### Level 1 — Basics
`val`/`var`, types, strings, `if`/`when`, loops, functions, lists and maps.
Exercise: a grade calculator using `when`.

### Level 2 — Kotlin style
Null safety, data classes, sealed classes, extension functions, lambdas and collection operations.
Exercise: a contact list with search, sorting and grouping.

### Level 3 — Android with Compose
Composables, state, layouts, navigation, ViewModel, coroutines, Retrofit for networking, Room database.
Exercise: a notes app with a list screen, an edit screen and local storage.

### Level 4 — Shipping
Architecture (MVVM), dependency injection (Hilt), testing, Bluetooth (robot remotes), Play Store publishing, Kotlin Multiplatform.
Exercise: a Bluetooth controller app for a robot.
