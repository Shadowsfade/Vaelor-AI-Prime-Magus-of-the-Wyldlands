# Vaelor

**Vaelor** (pronounced *Vay-lore*) is the **Prime Magus of the Wyldlands** and a
local-first AI assistant for Windows. He
combines private local language models, durable autonomous tasks, guarded file and shell
tools, project awareness, memory, voice, and an arcane tome interface.

Vaelor is currently an alpha. He can complete supervised development tasks, recover from
tool errors, verify changes, preserve task history, and pause for exact one-action
approval. He is not yet a complete terminal emulator or a replacement for every feature
in Warp Agent CLI; see [ROADMAP.md](ROADMAP.md) for the remaining work.

## Install on Windows

Requirements:

- Windows 10 or 11.
- Internet access during the first installation.
- Ollama or LM Studio with a local model for useful AI responses.
- Chrome or Edge if you want browser microphone input.

Installation:

1. Download the repository ZIP from GitHub and extract it.
2. Double-click `INSTALL.bat`.
3. If Windows SmartScreen appears, choose **More info**, then **Run anyway**.
4. Wait for the installer to report **ALL DONE**.
5. Start Vaelor from the new Desktop or Start Menu shortcut.
6. Complete the setup grimoire and select your Ollama or LM Studio model.

The installer creates a private installation under `%LOCALAPPDATA%\Vaelor`, chooses an
available local port, creates an isolated Python environment, and does not package the
developer's paths, conversations, or memories.

For detailed installation and troubleshooting, read [INSTALL.md](INSTALL.md).

## Use Vaelor

Open the tome, type a request into the parchment box, and press Enter or select **Cast**.
Useful commands include:

- `remember: <fact>` — save an explicit memory.
- `tools` — list available tools.
- `search: <question>` — perform web research.
- `agent: <task>` — run a multi-step autonomous task.
- `shell: <command>` — run a shell command under the configured safety policy.
- `git: status` — inspect the current Git repository.
- `tool: describe_sandbox` — explain Vaelor's current access policy.

When a task reaches a protected operation, it appears under **Action Approvals** in the
left sidebar. Review the exact tool, arguments, and risk, then choose **Approve Once** or
**Reject**. Approval applies only to that exact action and cannot be replayed.

Use **Task Center** to launch work that should continue as a durable background task. Its
cards show current status and provide View, Cancel, Resume, or Clarify controls when those
actions are valid. Select **View** to open a live console showing timestamped progress,
status changes, incremental persistent-terminal output, tool completion details, and the
final result. Quiet tasks emit a durable activity heartbeat every 30 seconds so extended
model or tool operations do not appear silently hung. Tasks default to a
15-minute runtime budget and cannot exceed 20 minutes.

Use **Summon Call** for voice conversation. Browser microphone input works best in Chrome
or Edge on localhost; spoken output uses the configured Edge TTS voice.

## Run from source

```powershell
git clone https://github.com/Shadowsfade/Vaelor-AI-Prime-Magus-of-the-Wyldlands.git
cd Vaelor-AI-Prime-Magus-of-the-Wyldlands
.\Start-Vaelor.bat
```

The launcher creates or repairs `.venv`, installs required packages, starts the API, and
opens Vaelor using the machine-local port configuration.

Developers may start the API directly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.server:app --host localhost --port 8000
```

The native CLI also supports one-shot prompts and persistent terminal state:

```powershell
python vaelor.py --version
python vaelor.py "Explain this repository"
python vaelor.py --json "Summarize the current project"
python vaelor.py --terminal --cwd C:\Projects\MyProject
```

Inside interactive CLI mode, prefix a shell command with `!`. Working-directory and
environment changes persist until `/close` or exit. Use `/terminal <path>` to restart the
session and `/help` for the command list. Existing shell safety and approval policy applies.

## Current capabilities

- Ollama and LM Studio local inference.
- Structured multi-step agent actions with verification and self-correction.
- Guarded file, shell, Git, web, diagnostic, and project tools.
- Durable tasks with progress events, cancellation, clarification, deadlines, and resume.
- Proactive, system-aware task guidance that gathers context and recommends useful
  alternatives or tradeoffs instead of blindly following a weak implementation path.
- Agent-selectable persistent terminal sessions for workflows that require retained cwd
  or environment state.
- Exact one-action approval through API and WebUI.
- Project grounding and bounded multi-file reading.
- Bounded local codebase search with relevance-ranked files and line-numbered snippets.
- Native read-only Git change review with file/line scope, whitespace checks, conflict
  warnings, and likely-secret redaction.
- Engine-agnostic evidence contracts and confidence gates that block promotion when
  required verification is failed, skipped, or unknown.
- Guarded adaptive self-extension: Vaelor recognizes requests to gain reusable abilities,
  fills genuine capability gaps modularly, and does not hardcode incidental examples.
- Persistent conversations with automatic bounded summaries, relevance-ranked memory,
  and user-controlled preferences.
- Desktop/web tome interface, streamed answers, and voice conversation.
- Windows installer and portable/desktop package builders.

## Project documentation

- [Installation and troubleshooting](INSTALL.md)
- [Architecture and developer briefing](CODER_BRIEFING.md)
- [Product roadmap](ROADMAP.md)
- [Release and milestone history](CHANGELOG.md)
- [Installer and packaging notes](installer/README.md)
- [Safety policy](config/SANDBOX_GOD_MODE.md)

## Verify a development checkout

Run the deterministic focused suite from the repository root:

```powershell
python -m unittest -v test_web_approvals.py test_web_copy.py test_release_metadata.py test_multi_file_reader.py test_readiness.py test_api_tasks.py test_project_context.py test_safety_defaults.py test_task_lifecycle.py test_agent_loop.py test_task_store.py test_brain_actions.py test_action_protocol.py test_tool_registry.py test_task_intent.py test_memory_retrieval.py test_preference_store.py test_preference_integration.py
```

## Privacy and safety

Vaelor is local-first, but some optional features—including Edge TTS and web research—may
contact internet services. Do not commit API keys, private memory files, model weights, or
machine-local configuration. Mutating tools are governed by supervised, trusted, or admin
policy, and core operating-system paths remain protected.

Current release: **1.1.4-alpha**.
