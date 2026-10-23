---
title: Bash and the command line
summary: The Linux/Mac terminal and shell scripting — essential for developers, servers, Raspberry Pi and robots.
tags: [language, shell, linux, terminal, scripting, devops, raspberry-pi]
---
# Bash and the command line

## Overview
The terminal lets you control a computer by typing commands. Every developer uses it for Git, running programs, installing packages and managing servers. Robots and Raspberry Pis are usually controlled over SSH in a terminal. Bash scripts automate sequences of commands.

## Setup and running
- Linux and Mac have a terminal built in (Mac's default shell is zsh, which is nearly identical for basics).
- Windows: use WSL (Windows Subsystem for Linux) or Git Bash.
- Run a script: `bash script.sh`, or make it executable with `chmod +x script.sh` and run `./script.sh`.

## Essential commands
```bash
pwd                      # where am I?
ls -la                   # list files, including hidden ones
cd projects/corvis       # change directory (.. = up one level, ~ = home)
mkdir -p src/utils       # make folders
cp a.txt b.txt; mv b.txt c.txt; rm c.txt   # copy, move/rename, delete (no undo!)
cat file.txt; less file.txt                # show a file
grep -rn "TODO" src/     # search text in files
find . -name "*.py"      # find files
command > out.txt        # save output (>> appends)
command1 | command2      # pipe output into the next command
sudo apt install git     # install software (Debian/Ubuntu/Raspberry Pi OS)
ssh pi@192.168.1.50      # log in to another machine
```

## Scripting
```bash
#!/usr/bin/env bash
set -euo pipefail        # stop on errors, unset variables and failed pipes

name="Corvis"            # no spaces around =
count=3
echo "Hello from $name"

if [[ -f config.yaml ]]; then echo "config found"; else echo "no config"; fi
for i in $(seq 1 "$count"); do echo "step $i"; done

backup() {               # function; arguments are $1, $2...
  local src="$1"
  tar -czf "backup-$(date +%F).tar.gz" "$src"
}
```

## Common mistakes
- Spaces around `=` in assignments (`x = 1` runs a command called `x`).
- Unquoted variables breaking on spaces: always write `"$var"`.
- `rm -rf` with a wrong or empty path. Double-check; never run it on `/` or `~`.
- Forgetting `set -euo pipefail`, so scripts continue after errors.
- Running random commands with `sudo` from the internet without understanding them.

## Learning path
### Level 1 — Getting around
Navigation, files and folders, viewing files, getting help (`man`, `--help`), tab completion and history.
Exercise: create a project folder structure and move files around without a mouse.

### Level 2 — Power tools
Pipes, redirection, `grep`, `find`, permissions (`chmod`), processes (`ps`, `kill`, `top`), environment variables, package managers.
Exercise: find the 5 largest files in your home folder.

### Level 3 — Scripts
Variables, conditionals, loops, functions, arguments, exit codes, `set -euo pipefail`, cron jobs.
Exercise: a script that backs up a folder with a date-stamped archive, run daily by cron.

### Level 4 — Remote machines
SSH and keys, `scp`/`rsync`, `systemd` services, logs with `journalctl`, `tmux`.
Exercise: set up a Raspberry Pi over SSH so your robot program starts automatically on boot.

## Complete example
```bash run
#!/usr/bin/env bash
set -euo pipefail

readings="front 42
left 17
right 88"

closest=$(echo "$readings" | sort -k2 -n | head -n1)
echo "Closest obstacle: ${closest% *} at ${closest##* } cm"

count=0
while read -r sensor cm; do
  if (( cm < 50 )); then
    echo "Warning: $sensor is close"
    count=$((count + 1))
  fi
done <<< "$readings"
echo "$count sensor(s) need attention"
```
