# Vaelor — Installation & Setup Guide

**Vaelor** (“Vay-lore”) is a free, local AI companion.  
It runs on **your computer**. No subscription is required.

---

## What you need

| Requirement | Notes |
|-------------|--------|
| Windows 10 or 11 | Primary supported platform |
| Internet (first install) | Downloads Python packages / optional tools |
| Optional: free brain app | [Ollama](https://ollama.com/download) (recommended) or [LM Studio](https://lmstudio.ai/) |
| Chrome or Edge | Best for microphone voice calling |

You do **not** need to know coding.

---

## Easiest install (recommended)

1. Unzip the Vaelor folder (if you received a zip).
2. Double-click **`INSTALL.bat`**  
   (or **`Install-Vaelor-Alpha.bat`** — same thing).
3. If Windows shows **“Windows protected your PC”**:
   - Click **More info**
   - Click **Run anyway**
4. Wait until the window says **ALL DONE**.
5. Double-click the desktop icon **Vaelor**.
6. Click the **closed book (tome)** to open the archive.

That’s it for basic install.

### What the installer does for you

- Installs **Python** automatically if missing (free, official)
- Copies Vaelor to `%LOCALAPPDATA%\Vaelor` (your user folder)
- Creates a private workspace and installs dependencies
- Builds **settings for this PC only** (paths + free local port)
- Puts a **Vaelor** shortcut on Desktop and Start Menu
- Writes **HOW-TO-USE.txt** next to the install

Your install does **not** use someone else’s machine paths, ports, or memory.

---

## First-time setup (make Vaelor smarter)

Vaelor can chat without a local model, but answers are much better with a free local LLM.

### Option A — Ollama (recommended)

1. Install: https://ollama.com/download  
2. Open Ollama once so it is running.  
3. In Vaelor, click **Setup**.  
4. Choose **Ollama** and follow the steps (or pull a model the wizard suggests).  
5. Hardware tip: on ~6GB VRAM GPUs, start with **7B–9B Q4** class models.

### Option B — LM Studio

1. Install: https://lmstudio.ai/  
2. Download a chat model in the app.  
3. Start the **local server** (default port **1234**).  
4. In Vaelor **Setup**, choose **LM Studio**.

---

## How to use Vaelor day to day

### Start

- Double-click desktop **Vaelor**, **or**
- Run `Start-Vaelor.bat` from the install folder, **or**
- Developers: from the source tree, `Start-Vaelor.bat`

A window opens (desktop app) or your browser opens the tome UI.

### Open the archive

Click the **leather tome cover** on the splash screen.

### Chat

Type in the parchment box and click **Cast** (or press Enter).

### Voice calling

1. Prefer **Chrome** or **Edge**.  
2. Click **Summon Call**.  
3. Allow the microphone when asked.  
4. Speak; Vaelor replies with wizard TTS (**en-GB-RyanNeural** by default).  
5. Name pronunciation: **Vay-lore**.

### Useful commands in chat

| Command | What it does |
|---------|----------------|
| `remember: …` | Store a fact |
| `tools` | List tools |
| `tool: describe_sandbox` | Show safety / access policy |
| `search: …` | Free web research |
| `code: …` | Code help |
| `shell: …` | Run a command (OS-safe limits apply) |
| `git: status` | Git status |

---

## Desktop app (Vaelor.exe)

If you have the desktop package:

1. Open the `Vaelor` folder from the desktop zip, **or** build with:
   ```powershell
   powershell -ExecutionPolicy Bypass -File installer\Build-Vaelor-Exe.ps1
   ```
2. Double-click **`Vaelor.exe`**.
3. You get a native window (arcane splash → tome UI), not a plain browser tab as the app shell.
4. A free **local port** is chosen automatically and saved in `config/network.json` **on that PC only**.

---

## Privacy & safety (plain English)

- Runs **locally**. No paid cloud required.
- Each install generates **its own** folders, free port, and empty memory.
- Installer packages do **not** ship another person’s user path, port, or chat memory.
- Vaelor may help with installs/dev work, but is blocked from wiping core OS folders (Windows/System32, etc.).
- Details: `config/SANDBOX_GOD_MODE.md`

---

## Troubleshooting

| Problem | Try this |
|---------|----------|
| Install fails | Need internet the first time; re-run `INSTALL.bat` |
| Python missing after failed auto-install | Install from https://www.python.org/downloads/ and check **Add python.exe to PATH**, then re-run install |
| Window opens but AI is weak | Install Ollama and complete **Setup** |
| Mic / call doesn’t work | Use Chrome or Edge; allow microphone; use localhost/desktop app |
| Port already in use | Delete `config/network.json` and restart — Vaelor picks another free port |
| Want logs for help | Temp folder files named `Vaelor-Install-....log` |

---

## For developers / coders

```powershell
cd <Vaelor-Core>
.\.venv\Scripts\python.exe -m uvicorn api.server:app --host localhost --port 8000
# or
.\Start-Vaelor.bat
```

- Teammate overview: `CODER_BRIEFING.md`
- Changelog: `CHANGELOG.md`
- Package zip: `installer\Build-AlphaPackage.ps1` → `dist\Vaelor-Alpha-*.zip`
- Desktop exe: `installer\Build-Vaelor-Exe.ps1` → `dist\Vaelor\Vaelor.exe`

Local machine files (not for git): `config/network.json`, `config/setup_complete.json`, live `memory/` (including tasks, preferences, and schedules), `.venv/`, `dist/`, `build/`.

## Optional authenticated remote API

Vaelor remains bound to loopback by default. To prepare a token for an intentional remote
API deployment, run:

```powershell
.\.venv\Scripts\python.exe .\installer\Configure-Remote-API.py
```

The token is shown by the setup command and stored in ignored local `config/api_access.json`. Existing
tokens are not replaced unless you deliberately rerun with `--force`, which invalidates
clients using the old token.

Non-loopback API requests must send either `Authorization: Bearer <token>` or
`X-Vaelor-Token: <token>`. Only expose the API over Tailscale/a trusted VPN or HTTPS;
plain HTTP on an untrusted network exposes bearer credentials. Token generation does not
change Vaelor's loopback binding or firewall.

To deliberately launch on a chosen Tailscale/VPN address:

```powershell
.\.venv\Scripts\python.exe .\installer\start_remote_api.py --host YOUR_TRUSTED_IP --port 8765
```

Open `http://YOUR_TRUSTED_IP:8765/` and enter the private token when the Tome asks. The
token is exchanged for a strict HttpOnly browser session and is not saved to browser
storage. Default Vaelor launchers remain local-only. Prefer HTTPS whenever the transport
is not already protected by a trusted encrypted VPN.

---

## Version

Alpha **1.1.4-alpha** — local-first companion with durable autonomous tasks, exact-action
approval, project-aware tools, installer, tome UI, and wizard voice.
