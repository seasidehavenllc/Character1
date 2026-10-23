---
title: PHP
summary: Server-side web language behind WordPress and much of the web; modern PHP with Laravel builds full web apps.
tags: [language, web, backend, wordpress, laravel]
---
# PHP

## Overview
PHP runs on web servers and generates pages or JSON. It powers WordPress (a large share of all websites), and the Laravel framework makes modern web apps quick to build. Modern PHP (8.x) has types, classes and good performance.

## Setup and running
- Install PHP 8 (`sudo apt install php-cli`, Homebrew `brew install php`, or XAMPP on Windows).
- Run a script: `php main.php`. Built-in dev server: `php -S localhost:8000`.
- Packages: Composer (`composer require vendor/package`). Laravel: `composer create-project laravel/laravel app`.

## Core syntax
```php
<?php
declare(strict_types=1);

$name = "Tony";                         // variables start with $
$power = 100;
$suits = ["Mark I", "Mark II"];         // array as a list
$suits[] = "Mark III";
$levels = ["Mark I" => 40];             // array as a map

if ($power > 50) {
    echo "$name has {$power}% power\n";
}
foreach ($suits as $i => $suit) {
    echo $i . ": " . $suit . "\n";      // . joins strings
}

function square(int $x): int { return $x * $x; }
$doubled = array_map(fn($n) => $n * 2, [1, 2, 3]);
```

## Handling a web form safely
```php
<?php
$name = trim($_POST["name"] ?? "");
echo "Hello, " . htmlspecialchars($name, ENT_QUOTES) . "!";   // escape output (prevents XSS)

$pdo = new PDO("sqlite:app.db");
$stmt = $pdo->prepare("SELECT * FROM users WHERE name = ?");  // parameters prevent SQL injection
$stmt->execute([$name]);
```

## Common mistakes
- Echoing user input without `htmlspecialchars` (cross-site scripting).
- Building SQL with string concatenation (SQL injection); always use prepared statements.
- Storing passwords in plain text; use `password_hash()` and `password_verify()`.
- `==` loose comparison surprises; use `===`.
- Leaving error display on in production.

## Learning path
### Level 1 — Basics
Variables, strings, arrays, `if`, loops, functions, `echo`; running scripts and the dev server.
Exercise: a page that shows a random quote from an array.

### Level 2 — Web basics
Forms, `$_GET`/`$_POST`, escaping output, sessions, including files, PDO with SQLite.
Exercise: a guestbook that saves messages to SQLite and displays them safely.

### Level 3 — Modern PHP
Classes, namespaces, Composer autoloading, exceptions, types, PHPUnit.
Exercise: refactor the guestbook into classes with tests.

### Level 4 — Frameworks
Laravel (routing, Blade, Eloquent, auth, migrations) or WordPress theme/plugin development.
Exercise: a Laravel app with user accounts and a CRUD feature.

## Complete example
```php run
<?php
declare(strict_types=1);

final class Suit
{
    public function __construct(public readonly int $mark, private int $power = 100) {}

    public function fly(int $minutes): int
    {
        $this->power = max(0, $this->power - $minutes * 5);
        return $this->power;
    }
}

$fleet = [new Suit(42), new Suit(43)];
$fleet[1]->fly(12);
foreach ($fleet as $suit) {
    printf("Mark %d power: %d%%\n", $suit->mark, $suit->fly(0));
}
```
