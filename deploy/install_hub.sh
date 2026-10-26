#!/usr/bin/env bash
# Installs the Corvis hub on a fresh Ubuntu 22.04 / 24.04 server.
#
#   sudo bash corvis/deploy/install_hub.sh
#
# Safe to run again (for example after uploading a newer Corvis): it keeps your
# settings, chats, password and key.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/corvis
ENV_FILE=/etc/corvis.env
PY="$DEST/.venv/bin/python"

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
as_corvis() { sudo -u corvis -H "$@"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run this with sudo:  sudo bash $0"
  exit 1
fi

cd /   # commands run as the corvis user can't enter your (private) home folder
step "1/7  Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates rsync >/dev/null

step "2/7  Setting up the corvis user and copying Corvis to $DEST"
id corvis &>/dev/null || useradd --create-home --shell /bin/bash corvis
mkdir -p "$DEST" /home/corvis/projects
if [ "$SRC" != "$DEST" ] && [ -d "$DEST/.git" ] && [ -d "$SRC/.git" ]; then
  # Did Corvis change himself on the hub since this upload was made? Keep a copy first.
  HUB_HEAD="$(git -c safe.directory='*' -C "$DEST" rev-parse HEAD 2>/dev/null || true)"
  if [ -n "$HUB_HEAD" ] && ! git -c safe.directory='*' -C "$SRC" cat-file -e "$HUB_HEAD^{commit}" 2>/dev/null; then
    BACKUP="/opt/corvis-backup-$(date +%Y%m%d-%H%M%S)"
    echo "   Corvis has changed his own code on this server since your upload was made."
    echo "   Saving that version to $BACKUP before replacing it."
    rsync -a --exclude '.venv/' "$DEST"/ "$BACKUP"/
  fi
fi
if [ "$SRC" != "$DEST" ]; then
  # Code only: an existing config.yaml, data/ and .venv on the server are kept as they are.
  rsync -a --delete --exclude '.venv/' --exclude '.browsers/' --exclude 'data/' --exclude 'config.yaml' --exclude 'config.yaml.bak' \
        "$SRC"/ "$DEST"/
  if [ -d "$SRC/data" ] && [ ! -d "$DEST/data" ]; then
    echo "   Bringing your chats, memory and password from the upload."
    cp -a "$SRC/data" "$DEST/data"
    rm -f "$DEST/data/node_token"   # that file belongs to a PC, not the hub
  fi
  if [ -f "$SRC/config.yaml" ] && [ ! -f "$DEST/config.yaml" ]; then
    echo "   Keeping your settings (name, personality, memory) from your PC's config.yaml."
    cp "$SRC/config.yaml" "$DEST/config.yaml"   # the server-specific parts are rewritten in step 5
  fi
fi
mkdir -p "$DEST/data"
chown -R corvis:corvis "$DEST" /home/corvis/projects
as_corvis git config --global user.name "Corvis"
as_corvis git config --global user.email "corvis@hub.local"
as_corvis git config --global --add safe.directory "$DEST"

# A short command for later:  sudo corvis pair-pc / set-password / check
printf '#!/bin/sh\ncd %s && exec sudo -u corvis -H %s -m corvis "$@"\n' "$DEST" "$PY" > /usr/local/bin/corvis
chmod 755 /usr/local/bin/corvis

step "3/7  Python environment (a few minutes the first time)"
[ -x "$PY" ] || as_corvis python3 -m venv "$DEST/.venv"
as_corvis "$DEST/.venv/bin/pip" install -q --upgrade pip
as_corvis "$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"
as_corvis "$DEST/.venv/bin/pip" install -q -r "$DEST/deploy/requirements-hub.txt"
echo "   Installing the bots' computer (a Chromium browser, about 300 MB)."
mkdir -p "$DEST/.browsers"
PLAYWRIGHT_BROWSERS_PATH="$DEST/.browsers" "$PY" -m playwright install --with-deps chromium >/dev/null
chown -R corvis:corvis "$DEST/.browsers"

step "4/7  Tailscale: your private network (phone, PC and this server)"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "   Open the link below and sign in with the SAME account as your PC and phone."
  tailscale up --hostname corvis-hub
fi
HOST="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "   This server is $HOST on your Tailscale network."

step "5/7  Corvis's brain (OpenRouter), settings and owner password"
cd "$DEST"   # Corvis runs from his own folder
"$PY" -m corvis --config "$DEST/config.yaml" hub-setup --host "$HOST" --env-file "$ENV_FILE"
chown -R corvis:corvis "$DEST/config.yaml" "$DEST/data"

step "6/7  Running Corvis as a service (starts on boot, restarts if needed)"
cat > /etc/systemd/system/corvis.service <<EOF
[Unit]
Description=Corvis hub
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=corvis
WorkingDirectory=$DEST
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
Environment=PLAYWRIGHT_BROWSERS_PATH=$DEST/.browsers
ExecStart=$PY -m corvis serve --no-browser
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable corvis >/dev/null 2>&1
systemctl restart corvis
sleep 3
systemctl is-active --quiet corvis && echo "   Corvis is running." || {
  echo "   Corvis didn't start. Recent log:"; journalctl -u corvis -n 30 --no-pager; exit 1; }

echo "   Serving Corvis privately over HTTPS on your Tailscale network."
echo "   (If it shows a link to turn on HTTPS, open it, turn it on, and this continues.)"
tailscale serve --bg 8765

step "7/7  Pairing code for your PC"
as_corvis "$PY" -m corvis --config "$DEST/config.yaml" pair-pc --name "My PC" --if-none

cat <<EOF

All done. Corvis now lives on this server.

  Phone:  open  https://$HOST  and sign in with your owner password,
          then add it to your home screen.
  PC:     double-click Link_PC_To_Hub.bat, paste  https://$HOST  and the pairing code above
          (first time only), then start Start_Corvis_Node.bat (or Add_Node_To_Startup.bat).

Useful later:
  sudo systemctl status corvis        is he running?
  sudo journalctl -u corvis -f        his log, live
  sudo corvis pair-pc --name "Laptop"  a pairing code for another computer
  sudo corvis set-password            choose a new owner password
EOF
