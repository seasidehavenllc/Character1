---
title: TypeScript
summary: JavaScript with static types — catches bugs before running; the standard for large web, Node and React projects.
tags: [language, web, frontend, backend, types, node]
---
# TypeScript

## Overview
TypeScript adds type annotations to JavaScript. The compiler (`tsc`) checks them and outputs plain JavaScript. Learn JavaScript basics first; TypeScript then mostly means describing the shape of your data.

## Setup and running
- `npm install -D typescript`, then `npx tsc --init` to create `tsconfig.json` (turn on `"strict": true`).
- Compile: `npx tsc`, then run the output with `node`. Or run directly with `npx tsx app.ts`.
- Most frameworks (Vite, Next.js) support TypeScript out of the box.

## Core syntax
```typescript
let count: number = 0;
const name = "Tony";              // type inferred as string
const tags: string[] = ["ai", "robot"];

interface Suit {
  mark: number;
  color: string;
  flight?: boolean;               // optional
}

type Status = "idle" | "flying" | "damaged";   // union of literal types

function describe(s: Suit, status: Status): string {
  return `Mark ${s.mark} (${s.color}) is ${status}`;
}

function first<T>(items: T[]): T | undefined {  // generic
  return items[0];
}
```

## Narrowing
TypeScript tracks checks you make, so a value's type gets more specific inside `if` blocks.
```typescript
function len(x: string | string[] | null): number {
  if (x === null) return 0;
  if (typeof x === "string") return x.length;
  return x.length;               // here x is string[]
}
```

## Common mistakes
- Using `any` to silence errors — it switches checking off. Prefer `unknown` and narrow it.
- Forgetting `strict` mode, which hides most of the useful checks.
- Thinking types exist at runtime: they're erased; validate external data (API responses) with a library like Zod.
- Over-engineering types early. Start simple; add precision where bugs appear.

## Learning path
### Level 1 — Typing JavaScript
Basic types, arrays, objects, function parameter and return types, `interface` vs `type`.
Exercise: convert a small JavaScript to-do app to TypeScript with `strict` on and zero errors.

### Level 2 — Expressive types
Unions, literal types, narrowing, optional and readonly properties, enums vs unions, generics.
Exercise: model a robot's state machine as a union of states and write a function that handles every case.

### Level 3 — Real projects
`tsconfig`, modules, typing third-party packages, React with TypeScript, Node APIs, runtime validation.
Exercise: a typed REST API client with validated responses.

### Level 4 — Advanced
Mapped and conditional types, utility types (`Partial`, `Pick`, `Record`), declaration files, monorepos.
Exercise: build a typed event emitter where listeners get the right payload type per event.

## Complete example
```typescript run
type State =
  | { kind: "idle" }
  | { kind: "flying"; altitude: number }
  | { kind: "damaged"; damage: number };

function report(s: State): string {
  switch (s.kind) {
    case "idle":
      return "Standing by.";
    case "flying":
      return `Flying at ${s.altitude} m.`;
    case "damaged":
      return `Damage at ${s.damage}%.`;
  }
}

const log: State[] = [{ kind: "idle" }, { kind: "flying", altitude: 1200 }, { kind: "damaged", damage: 35 }];
log.forEach((s) => console.log(report(s)));
```
