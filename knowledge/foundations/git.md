---
title: Git and GitHub
summary: Version control — save checkpoints of your code, undo mistakes, work on features safely and collaborate on GitHub.
tags: [tools, git, github, version-control, collaboration]
---
# Git and GitHub

## Overview
Git records snapshots ("commits") of a project so you can see what changed, go back in time, and work on several features at once using branches. GitHub hosts Git repositories online for backup, sharing and teamwork (pull requests, issues).

## Setup
```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
```

## Daily workflow
```bash
git init                         # start tracking a folder (or: git clone <url>)
git status                       # what changed?
git add app.py                   # stage a file for the next commit (git add . = everything)
git commit -m "Add login form"   # save a snapshot with a message
git log --oneline                # history
git diff                         # unstaged changes

git switch -c feature/sensors    # new branch for a feature
# ...edit, add, commit...
git switch main
git merge feature/sensors        # bring the feature in

git remote add origin https://github.com/you/project.git
git push -u origin main          # upload; later just: git push
git pull                         # download others' changes
```

## Undoing things
```bash
git restore app.py               # discard uncommitted changes to a file
git restore --staged app.py      # unstage
git commit --amend               # fix the last commit message (before pushing)
git revert <commit>              # new commit that undoes an old one (safe after pushing)
```

## Common mistakes
- Committing secrets (API keys, passwords). Add them to `.gitignore` and use environment variables. If one was pushed, revoke it — history keeps it.
- Huge commits with vague messages. Commit small, focused changes: "Fix motor speed clamp", not "stuff".
- Working directly on `main` for everything; use branches.
- `git push --force` on shared branches, erasing others' work.
- Committing build output, `node_modules`, `.venv`: use `.gitignore`.

## Learning path
### Level 1 — Solo snapshots
`init`, `status`, `add`, `commit`, `log`, `diff`, `.gitignore`.
Exercise: put an existing project under Git with at least 5 meaningful commits.

### Level 2 — Branches and GitHub
Branches, merging, resolving a merge conflict, remotes, push/pull, README files.
Exercise: publish the project on GitHub and add a feature via a branch.

### Level 3 — Teamwork
Pull requests, code review, issues, forks, rebasing basics, tags and releases.
Exercise: open a pull request against a friend's repo (or your own second account) and merge it after review.

### Level 4 — Automation
GitHub Actions for tests on every push, branch protection, semantic versioning.
Exercise: add a workflow that runs your tests automatically.
