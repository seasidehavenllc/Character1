---
title: JavaScript
summary: The language of the web — runs in every browser and on servers (Node.js); used for websites, web apps, mobile (React Native) and desktop (Electron).
tags: [language, web, frontend, backend, node, beginner]
---
# JavaScript

## Overview
JavaScript makes web pages interactive and, with Node.js, runs servers and tools. Every browser has it built in, so there's nothing to install to start. Its huge package registry is npm. TypeScript (JavaScript with types) is the usual choice for bigger projects.

## Setup and running
- In a browser: open DevTools (F12) → Console, or add `<script src="app.js"></script>` to an HTML page.
- On a computer: install Node.js (LTS) from nodejs.org, then `node app.js`.
- Projects: `npm init -y`, `npm install <package>`, scripts in `package.json`.

## Core syntax
```javascript
const name = "Tony";           // const: can't be reassigned (use by default)
let power = 100;               // let: can change
power -= 10;

if (power > 50 && name !== "") {      // use === and !== (strict equality)
  console.log(`${name} has ${power}% power`);   // template string
}

for (let i = 0; i < 3; i++) console.log(i);
const suits = ["Mark I", "Mark II"];
for (const suit of suits) console.log(suit);    // of = values

const armor = { color: "red", power: 100 };     // object
armor.flight = true;
const { color } = armor;                        // destructuring

function add(a, b) { return a + b; }
const double = (n) => n * 2;                    // arrow function
const powered = [1, 2, 3].map(double).filter((n) => n > 2);
```

## Asynchronous code
Network requests, timers and file access don't block; they return Promises. Use `async`/`await`.
```javascript
async function getUser(id) {
  const res = await fetch(`https://api.example.com/users/${id}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

getUser(1).then((user) => console.log(user)).catch((err) => console.error(err));
```

## The DOM (web pages)
```javascript
const button = document.querySelector("#launch");
button.addEventListener("click", () => {
  document.querySelector("#status").textContent = "Launched!";
});
```

## Common mistakes
- `==` converts types (`"0" == 0` is true); always use `===`.
- Forgetting `await`, so you get a Promise instead of the value.
- `this` inside regular functions changes with how they're called; arrow functions keep the outer `this`.
- Modifying arrays/objects you thought were copies: use `[...arr]` / `{...obj}` for shallow copies.
- Floating-point: `0.1 + 0.2 !== 0.3`. Round for display; use integers (cents) for money.

## Learning path
### Level 1 — Basics
Variables, types, operators, `if`, loops, functions, arrays, objects; run code in the browser console and Node.
Exercise: a function that takes an array of scores and returns the average, highest and lowest.

### Level 2 — The web page
HTML + CSS basics, the DOM, events, forms, `localStorage`.
Exercise: a to-do list web page that saves tasks in `localStorage`.

### Level 3 — Async and modules
Promises, `async/await`, `fetch`, ES modules (`import`/`export`), npm, error handling.
Exercise: a weather page that fetches from a free public API and shows a loading state and errors.

### Level 4 — Real projects
Front end: React, Vue or Svelte. Back end: Node with Express or Fastify, a database. Then TypeScript.
Exercise: a full-stack notes app with a small Node API.

## Complete example
```javascript run
class Suit {
  constructor(mark, power = 100) {
    this.mark = mark;
    this.power = power;
  }
  fly(minutes) {
    this.power = Math.max(0, this.power - minutes * 5);
    return this.power;
  }
}

const fleet = [new Suit(42), new Suit(43, 60)];
fleet.forEach((s) => s.fly(4));
const ready = fleet.filter((s) => s.power >= 50).map((s) => `Mark ${s.mark}`);
console.log(`Ready to launch: ${ready.join(", ") || "none"}`);
```
