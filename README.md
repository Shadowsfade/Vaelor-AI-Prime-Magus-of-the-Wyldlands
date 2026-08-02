# Vaelor (Vay-lore)

Free, **local** AI companion — Arcane Archivist of the Wyldlands.  
You are the **Apprentice**. No subscription required.

## Quick start (new users)

1. Read **[INSTALL.md](INSTALL.md)** (full guide)  
2. Or just open **[READ ME FIRST.txt](READ%20ME%20FIRST.txt)** and double-click **`INSTALL.bat`**

## What you get

- Arcane **tome** WebUI / desktop window  
- Wizard voice TTS (`edge-tts`, default `en-GB-RyanNeural`) + browser mic calling  
- Local LLM via **Ollama** or **LM Studio**  
- Tools: files, web research, git, shell (OS-safe admin policy)  
- Per-machine auto config (paths + free local port; no foreign PC settings)

## Developers

```powershell
.\Start-Vaelor.bat
# http://localhost:<auto-or-dev-port>
```

- `CODER_BRIEFING.md` — architecture for teammates  
- `CHANGELOG.md` — version history  
- `installer/` — beginner installer + package builders  

## License / privacy

Intended as a **private** project unless you choose otherwise.  
Do not commit secrets, model weights (`.gguf`), or personal `memory/` dumps.
