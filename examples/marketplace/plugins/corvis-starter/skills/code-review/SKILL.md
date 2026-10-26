---
name: code-review
description: Review code like a senior engineer — correctness, security, clarity, tests. Use when asked to review, check or improve code.
---
# Code review

Work through the code in this order, and report findings most serious first.

1. **Correctness.** Trace real inputs through the code. Look for off-by-one errors, unhandled
   None/null, wrong conditions, missing awaits, race conditions, and resources never closed.
2. **Security.** Untrusted input reaching SQL, shell commands, file paths or HTML; secrets in code;
   missing permission checks.
3. **Failure handling.** What happens when the network, disk or a dependency fails?
4. **Clarity.** Names that say what things are, functions that do one job, no dead code.
5. **Tests.** Is the change covered? Suggest the one test that would have caught each bug.

For each finding give: where (file:line), what goes wrong with a concrete example, and the fix.
If the code is good, say so briefly; don't invent problems. Run the tests if you can.
