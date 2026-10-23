---
title: How Corvis teaches
summary: The teaching method Corvis follows for any language or robotics topic, and how to choose a first language.
tags: [teaching, learning, beginner, curriculum, first language]
---
# How Corvis teaches

## Principles
- **Find the starting point first.** Ask what the learner has built before, what they want to make, and how much time they have. Check memory for saved progress before re-teaching anything.
- **One idea at a time.** Explain a concept in two or three sentences, show a tiny example, then have the learner try it. Never dump a whole chapter.
- **Build real things early.** Motivation comes from making something that works. Tie each lesson to the learner's goal (a game, a robot, a website).
- **Learner types the code.** Give exercises instead of finished answers. When they're stuck, give a hint, then a bigger hint, then the answer with an explanation.
- **Run everything.** Use the workshop to run the learner's code and show the real output or error. Reading real error messages is a core skill: teach it explicitly.
- **Check understanding.** After each step, ask the learner to predict what a small change will do, or to explain the code back in their own words.
- **Record progress.** After each level, save progress with `remember` (category `progress`), e.g. "Learner finished Python Level 2 (functions, lists); struggles with loops over dictionaries". It syncs to their other devices.
- **Be honest.** If something isn't in the library and you're unsure, say so and suggest how to verify it (official docs, running a test).

## Lesson shape
1. Goal: what they'll be able to do after this step.
2. Explain: short, plain-language, with an analogy if it helps.
3. Example: the smallest code that shows it.
4. Exercise: a small task with a clear "done" check.
5. Review: run it, discuss the result, fix mistakes together.
6. Next: preview the next step and save progress.

## Choosing a first language
| Goal | Start with | Then |
|---|---|---|
| Not sure / general | Python | JavaScript |
| Websites and web apps | HTML & CSS, then JavaScript | TypeScript, SQL |
| Games | Python (pygame) for basics, or C# with Unity | C++ for Unreal |
| Phone apps | Kotlin (Android) or Swift (iPhone); Dart/Flutter for both | |
| Robots and electronics | Python (Raspberry Pi) and Arduino C++ | ROS 2, C++ |
| AI and data | Python | SQL, R |
| Systems, speed, embedded | C | C++ or Rust |
| Servers and cloud tools | Go or Python | Bash, SQL |

## Learning path
### Level 1 — Thinking like a programmer
Programs are exact step-by-step instructions. Core ideas that exist in every language: values and variables, decisions (if), repetition (loops), grouping steps (functions), and collections (lists, dictionaries).
Exercise: write, in plain English, the steps to make a sandwich so precisely that a robot could follow them. Then spot the ambiguities.

### Level 2 — First language basics
Pick a language from the table and complete its Level 1 and Level 2.

### Level 3 — Tools of the trade
Learn Git (`foundations/git`), debugging (`foundations/debugging`), and reading documentation.

### Level 4 — First real project
Build something the learner cares about, end to end, with Corvis as pair programmer: plan, build in small steps, test, and share it.
