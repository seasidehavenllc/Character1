---
name: debug-like-a-pro
description: A step-by-step method for finding the real cause of a bug. Use for errors, crashes, wrong results or "it doesn't work".
---
# Debugging method

1. **Reproduce** the problem reliably. Get the exact error message and steps.
2. **Read the whole error**, including the stack trace: the last lines usually name the file and line.
3. **Form one hypothesis** about the cause, and test it with the smallest possible check
   (a print, a debugger breakpoint, a tiny test).
4. **Shrink** the problem: remove code until the bug disappears; the last thing removed is involved.
5. **Fix the cause, not the symptom.** Then re-run the reproduction and the tests.
6. **Prevent it:** add a test, and record the lesson with record_experience.

Explain each step to the owner in plain words as you go.
