---
title: C#
summary: Microsoft's modern language for Unity games, Windows apps, web back ends (ASP.NET) and cross-platform apps (.NET MAUI).
tags: [language, games, unity, windows, backend, oop, dotnet]
---
# C#

## Overview
C# runs on .NET and is the scripting language of Unity, the most popular game engine for indie and mobile games. It's also used for Windows desktop apps, ASP.NET web APIs and cross-platform apps. Similar to Java, with many conveniences (properties, LINQ, async).

## Setup and running
- Install the .NET SDK from dot.net. Check: `dotnet --version`.
- New app: `dotnet new console -o MyApp && cd MyApp && dotnet run`.
- Unity: install Unity Hub; scripts are C# files attached to GameObjects. Editor: Visual Studio, VS Code or Rider.

## Core syntax
```csharp
using System;
using System.Collections.Generic;
using System.Linq;

var name = "Tony";
int power = 100;
var suits = new List<string> { "Mark I", "Mark II" };
var levels = new Dictionary<string, int> { ["Mark I"] = 40 };

if (power > 50) Console.WriteLine($"{name} is ready");   // interpolated string
foreach (var s in suits) Console.WriteLine(s);
var strong = suits.Where(s => s.EndsWith("II")).ToList();  // LINQ
```

## Classes and properties
```csharp
public class Robot
{
    public string Name { get; }               // read-only property
    public int Battery { get; private set; } = 100;

    public Robot(string name) => Name = name;

    public bool Move(int cm)
    {
        if (cm * 2 > Battery) return false;
        Battery -= cm * 2;
        return true;
    }
}
```

## Unity script
```csharp
using UnityEngine;

public class Spin : MonoBehaviour
{
    [SerializeField] float degreesPerSecond = 90f;   // editable in the Inspector

    void Update()                                     // runs every frame
    {
        transform.Rotate(0f, degreesPerSecond * Time.deltaTime, 0f);
    }
}
```

## Common mistakes
- Null reference exceptions: enable nullable reference types (`<Nullable>enable</Nullable>`) and heed warnings.
- In Unity, doing heavy work in `Update()` every frame, or using `GameObject.Find` repeatedly; cache references.
- Forgetting `Time.deltaTime`, so movement depends on frame rate.
- Blocking on async code with `.Result`; use `await`.

## Learning path
### Level 1 — Basics
Types, strings, control flow, methods, arrays and `List<T>`.
Exercise: a console dice game against the computer.

### Level 2 — Objects and collections
Classes, properties, constructors, inheritance, interfaces, `Dictionary`, exceptions, LINQ.
Exercise: a shop inventory with search and totals via LINQ.

### Level 3 — Unity or .NET apps
Unity: GameObjects, components, physics, input, prefabs, UI. Or .NET: async/await, ASP.NET minimal APIs, Entity Framework.
Exercise: a Unity rolling-ball game with score and restart, or a to-do REST API.

### Level 4 — Shipping
Unity: scenes, audio, saving, building for PC/mobile. .NET: testing (xUnit), dependency injection, deployment.
Exercise: publish a small game build or deploy the API.

## Complete example
```csharp run
using System;
using System.Linq;

var parts = new[] { ("arc reactor", 1200.0), ("repulsor", 450.5), ("servo", 35.0) };
foreach (var (name, price) in parts.OrderBy(p => p.Item2))
    Console.WriteLine($"{name}: ${price}");
Console.WriteLine($"Total: ${parts.Sum(p => p.Item2)}");
```
