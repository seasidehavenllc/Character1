# Corvis in the cloud (v1.0)

After this, Corvis lives on a small cloud server and thinks with a cloud model, so he works
from your phone **with your PC off**. When your PC is on, it lends him its hands: your files,
apps and games. He can still edit his own code, on the server.

```
 Phone ─┐                          ┌─ OpenRouter (his brain: a cloud model)
        ├── Tailscale (private) ── Corvis hub (cloud server, always on)
 PC  ───┘   your devices only      └─ his code, chats, memory, self-edits
 (Corvis Node, only when it's on: files, apps, games, installs)
```

Nothing is opened to the public internet. Only devices signed in to your Tailscale account
can reach Corvis, and every device still signs in with your owner password.

What you need: about 45 minutes, a card for two small bills, and the Corvis v1.0 zip.

---

## Step 1: His brain (OpenRouter, 5 minutes)

1. Make an account at **openrouter.ai**.
2. **Credits**: add a little to start, like $10. You only pay for what Corvis uses.
3. **Keys**: create a key and copy it (it starts with `sk-or-`). Keep it somewhere safe for Step 3.
4. Optional but recommended: in your OpenRouter privacy settings, turn off providers that may
   train on your prompts.
5. Optional: set a **credit limit** on the key, so it can never spend more than you choose.

The installer suggests a coding model that can use tools (Corvis needs that), usually
`qwen/qwen3-coder`. At the time of writing that is about $0.30 per million tokens in and $1.00
per million out, so a typical coding task costs a few cents. Prices change, so check the
model's page on OpenRouter. You can switch models any time by running the installer again.

## Step 2: The server (10 minutes)

Any cloud provider works. Create a server with:

- **Ubuntu 24.04** (22.04 also works)
- **2 GB RAM** (the bots' web browser needs it; 1 GB works if you never use the Computer); about 20 GB disk
- Any region close to you

Small servers cost roughly $5 to $25 a month depending on the provider (prices rose at several
providers in 2026, so compare). Corvis's hub is light: the heavy thinking happens at OpenRouter.

Write down the server's **IP address** and its **root password** (or set up an SSH key, if
the provider offers it).

## Step 3: Install Corvis on the server (15 minutes)

On your PC, open **PowerShell** in the folder with the zip (for example Downloads).

**1. Send Corvis up**, with your chats, memory, password and settings:

```powershell
scp Corvis-v1.0.zip root@YOUR.SERVER.IP:~/
ssh root@YOUR.SERVER.IP "mkdir -p ~/Corvis"
scp -r C:\Corvis\data root@YOUR.SERVER.IP:~/Corvis/
scp C:\Corvis\config.yaml root@YOUR.SERVER.IP:~/Corvis/
```

(The first time, type `yes` to trust the server, then its password.)

**2. Log in to the server and run the installer:**

```powershell
ssh root@YOUR.SERVER.IP
```

Then, on the server:

```bash
python3 -m zipfile -e Corvis-v1.0.zip .
sudo bash Corvis/deploy/install_hub.sh
```

Your settings from the PC (name, personality, memory) come along; the server-specific parts
are set for you. The installer asks for three things:

| It asks | You do |
|---|---|
| A Tailscale link | Open it and sign in with the **same account** as your PC and phone |
| Your OpenRouter key | Paste it (it won't show as you paste) and press Enter |
| A model | Press Enter for the suggested one, or paste another id from openrouter.ai |

If it shows a link to **enable HTTPS** for Tailscale, open it, turn it on, and the installer
carries on.

At the end it prints the **address** (like `https://corvis-hub.tail1234.ts.net`) and a
**pairing code** for your PC (it starts with `cvn_`). Copy both. The code is shown once.

## Step 4: Your phone

1. Make sure the Tailscale app is on and signed in.
2. Open the address from Step 3 and sign in with your owner password (the same one as before:
   it came with your chats).
3. Add it to your home screen again: **Safari → Share → Add to Home Screen**, or
   **Chrome → ⋮ → Install app**. Remove the old icon that pointed at your PC.

Corvis now answers with your PC off.

## Step 5: Your PC (the node)

1. Unzip the new version over `C:\Corvis` (replace files when asked). Your `config.yaml`,
   chats and `.venv` are kept: the zip doesn't contain them.
2. Double-click **`Link_PC_To_Hub.bat`**. Paste the address and the pairing code from Step 3.
3. Double-click **`Start_Corvis_Node.bat`**. It says *Connected*. While that window is open,
   Corvis can use this PC: files, apps, games, installs, with all the same approvals.
4. To have it start automatically when you log in: **`Add_Node_To_Startup.bat`**
   (undo with `Remove_Node_From_Startup.bat`).

In Corvis's menu, the line above the model shows your PC's name with **connected** or
**offline**.
When the PC is off, Corvis tells you he can't reach it and everything else keeps working.

`Start_Corvis.bat` still runs the old all-on-your-PC Corvis (with Ollama) if you ever want it.

---

## Good to know

**Approvals still come to you.** When Corvis wants to move, delete or install something on your
PC, the PC asks the hub, and the **Allow / Deny** card appears in your chat, on your phone too.
The PC's own rules (private folders, Recycle Bin, protected paths) are checked on the PC.

**He edits himself on the server.** Self-edits happen on a branch, run the tests, show you the
change, and only merge when you approve. If an update stops him from starting, the server undoes
it automatically within 90 seconds and he tells you next time you open the app. The change is kept
on its branch for you to look at.

**Updating later.** Send the new zip up and run the installer again, as in Step 3 (skip the
`data` copy). It keeps your key, model, password, chats and PC link. If Corvis changed his own
code on the server since then, the installer saves that version to `/opt/corvis-backup-<date>`
first and tells you.

**Useful commands on the server** (log in with `ssh root@YOUR.SERVER.IP`):

| Command | What it does |
|---|---|
| `systemctl status corvis` | Is he running? |
| `journalctl -u corvis -f` | His log, live (Ctrl+C to stop watching) |
| `systemctl restart corvis` | Restart him |
| `corvis pair-pc --name "Laptop"` | Pairing code for another computer |
| `corvis set-password` | Choose a new owner password (signs out every device) |

**Costs at a glance.** The server bill is fixed each month; OpenRouter is pay-as-you-go.

**Photos and screenshots.** The installer also picks a cloud model that can see images (usually
a Gemini Flash model), since coding models are blind. It uses the same OpenRouter key.

**Where things are on the server.** Corvis's code: `/opt/corvis` (a Git repo). Chats and memory:
`/opt/corvis/data`. The OpenRouter key: `/etc/corvis.env`, readable only by the system, never in
`config.yaml` or Git. New projects: `/home/corvis/projects`.

**Troubleshooting**

- *Phone says it can't reach Corvis*: is Tailscale on, on the phone? On the server, check
  `systemctl status corvis`.
- *PC shows offline*: is the `Start_Corvis_Node` window open? If it says *Stopped: ... link it
  again*, make a new code on the server (command above) and run `Link_PC_To_Hub.bat` again.
- *Corvis answers with an OpenRouter error*: check your credit at openrouter.ai.
