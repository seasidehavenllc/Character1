---
title: Dart and Flutter
summary: Dart with the Flutter framework builds one app for iPhone, Android, web and desktop from a single codebase.
tags: [language, mobile, flutter, cross-platform, ui, ios, android]
---
# Dart and Flutter

## Overview
Flutter (by Google) draws its own UI, so one Dart codebase runs on Android, iOS, web, Windows, Mac and Linux with the same look. Hot reload shows changes instantly. A strong choice when you want phone apps on both platforms without learning Swift and Kotlin.

## Setup and running
- Install the Flutter SDK (flutter.dev), then run `flutter doctor` and follow its checklist (Android Studio; Xcode on Mac for iOS).
- New app: `flutter create app && cd app && flutter run`.
- Plain Dart: `dart run main.dart`. Packages: `flutter pub add http`.

## Core syntax
```dart
void main() {
  final name = 'Tony';               // set once
  var power = 100;
  power -= 10;
  final suits = <String>['Mark I', 'Mark II'];
  suits.add('Mark III');
  final levels = {'Mark I': 40};

  if (power > 50) print('$name has $power% power');
  for (final s in suits) print('$s ${levels[s] ?? '?'}');
  final strong = suits.where((s) => s.endsWith('II')).toList();
  print(strong);
}

int square(int x) => x * x;

class Robot {
  Robot(this.name);
  final String name;
  int battery = 100;
  String? lastCommand;                // ? = may be null
}
```

## Flutter widget
```dart
import 'package:flutter/material.dart';

class PowerScreen extends StatefulWidget {
  const PowerScreen({super.key});
  @override
  State<PowerScreen> createState() => _PowerScreenState();
}

class _PowerScreenState extends State<PowerScreen> {
  int power = 100;
  @override
  Widget build(BuildContext context) {
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text('Power: $power%', style: Theme.of(context).textTheme.headlineMedium),
      FilledButton(onPressed: () => setState(() => power = (power - 10).clamp(0, 100)),
                   child: const Text('Fly')),
    ]);
  }
}
```

## Common mistakes
- Changing state without `setState` (UI doesn't update).
- Deeply nested widget trees in one build method; split into small widgets.
- Using `!` to force non-null; handle nulls instead.
- Doing slow work in `build`; use `FutureBuilder` or state management.

## Learning path
### Level 1 — Dart basics
Variables, types, null safety, functions, lists and maps, classes.
Exercise: a console expense tracker.

### Level 2 — Flutter UI
Widgets, layout (Row, Column, Stack), stateless vs stateful, buttons and forms, navigation.
Exercise: a two-screen recipe app.

### Level 3 — Real data
Async/await, HTTP and JSON, state management (Provider or Riverpod), local storage.
Exercise: a weather app using a public API.

### Level 4 — Shipping
Theming, animations, platform plugins (Bluetooth, camera), testing, publishing to Play Store and App Store.
Exercise: a Bluetooth robot remote for Android and iOS.
