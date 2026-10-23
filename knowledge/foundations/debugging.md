---
title: Debugging
summary: A reliable method for finding and fixing bugs in any language or robot — reading errors, isolating problems, using debuggers.
tags: [tools, debugging, errors, testing, troubleshooting]
---
# Debugging

## The method
1. **Reproduce it.** Find the exact steps that make the bug happen every time.
2. **Read the error.** The last lines of a traceback / compiler message usually name the file, line and problem. Read all of it.
3. **Form a guess.** "I think `speed` is negative when the robot turns left."
4. **Test the guess.** Print values, use a debugger, or write a tiny test that shows it.
5. **Shrink the problem.** Remove code until the bug disappears; the last thing removed is involved.
6. **Fix the cause, not the symptom.** Then re-run the reproduction and the tests.
7. **Prevent it.** Add a test, a check, or a clearer name, and save the lesson.

## Reading common errors
| Message (examples) | Usually means |
|---|---|
| `NameError` / `ReferenceError` / "cannot find symbol" | Misspelled name, or used before it was defined/imported |
| `TypeError` / "incompatible types" | Wrong kind of value (string vs number, None/null) |
| `IndexError` / out of bounds | Index past the end; off-by-one in a loop |
| `KeyError` / undefined property | Missing key in a dict/object |
| Segmentation fault (C/C++) | Bad pointer, out-of-bounds array, use after free |
| `ModuleNotFoundError` / cannot find module | Package not installed in this environment, or wrong path |
| Works on my machine | Different versions, environment variables, files, or OS |

## Tools
- **Print debugging:** print the values you think you know. Fast and universal.
- **Debuggers:** breakpoints and stepping (VS Code, `pdb`/`breakpoint()` in Python, `gdb`, browser DevTools).
- **Logging:** keep timestamped logs for programs that run long, like robots.
- **Tests:** a failing test that reproduces the bug proves the fix.
- **Rubber duck:** explain the code line by line out loud; the mistake often appears.
- **Git:** `git diff` and `git bisect` find what change introduced a bug.

## Robots and hardware
Separate software from hardware problems: test the code with the motors unplugged (print commands instead), test the hardware with the simplest known-good sketch, check power (batteries are the #1 cause), wiring, common ground, and loose connectors.

## Learning path
### Level 1 — Reading errors
Practice reading tracebacks and compiler errors; fix 10 small broken programs.
Exercise: Corvis writes five buggy snippets; find and fix each one, explaining the cause.

### Level 2 — Systematic method
Reproduce, hypothesize, test, shrink. Print debugging and logging.
Exercise: find a bug in a 100-line program using only prints and halving the code.

### Level 3 — Debuggers and tests
Breakpoints, stepping, watching variables, call stacks; writing a failing test first.
Exercise: use a debugger to find why a loop produces the wrong total.

### Level 4 — Hard bugs
Intermittent bugs, race conditions, memory errors (sanitizers, valgrind), performance profiling, hardware faults.
Exercise: diagnose a robot that "randomly" resets (hint: check power draw when motors start).
