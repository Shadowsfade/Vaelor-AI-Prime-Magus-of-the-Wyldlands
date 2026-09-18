"""Native Vaelor command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.runtime import VaelorRuntime
from core.terminal_session import TerminalSessionManager
from core.version import VAELOR_VERSION


def _discover_worktree_root() -> Path:
    """Discover the Vaelor worktree root from the current module location.

    This avoids hardcoding any specific worktree path.
    """
    # vaelor.py is at <worktree_root>/vaelor.py
    return Path(__file__).resolve().parent


def build_parser():
    parser = argparse.ArgumentParser(description="Vaelor local AI assistant", prog="vaelor")
    parser.add_argument("prompt", nargs="*", help="Run one prompt and exit")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    parser.add_argument("--research", action="store_true", help="Research a topic using public web sources")
    parser.add_argument("--terminal", action="store_true", help="Start in persistent terminal mode")
    parser.add_argument("--cwd", help="Initial terminal working directory")
    parser.add_argument("--version", action="version", version=VAELOR_VERSION)
    # New infra subcommands - parsed as positional args when no flags given
    parser.add_argument("--infra", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--infra-command", dest="infra_command", help=argparse.SUPPRESS)
    parser.add_argument("--infra-node", dest="infra_node", help=argparse.SUPPRESS)
    return parser


def handle_infra_status(args):
    """Handle 'vaelor infra status' command."""
    from core.infra.observer import observe_local
    from core.infra.classifier import get_state_summary
    from core.infra.recovery import get_recovery_policy

    worktree_root = _discover_worktree_root()
    obs = observe_local(node_name=args.infra_node or "skyai", worktree_path=str(worktree_root))

    if args.json:
        print(json.dumps(obs.to_dict(), indent=2))
        return 0

    summary = get_state_summary(obs)
    print(f"{summary['node'].upper()}")
    print(f"State: {summary['state']}")
    print()
    print(f"Host             {summary['host']}")
    print(f"Tailscale        {summary['tailscale']}")
    print(f"Tailscale Backend {summary['tailscale_backend']}")
    print(f"Tailscale Peers  {summary['tailscale_peers']}")
    print(f"SSH Service      {summary['ssh_service']}")
    print(f"Vaelor API       {summary['vaelor_health']}")
    print(f"Vaelor Readiness {summary['vaelor_readiness']}")
    print(f"Supervisor       {summary['supervisor']}")
    print(f"Model Backend    {summary['model_backend']}")
    print()
    if summary['uptime_seconds']:
        print(f"Uptime: {summary['uptime_seconds']:.0f}s")
    if summary['git_branch']:
        print(f"Git:")
        print(f"  branch: {summary['git_branch']}")
        print(f"  HEAD: {summary['git_head']}")
    print()
    print("Listeners:")
    for port, info in summary['listeners'].items():
        exe = info.get('exe', 'unknown')
        pid = info.get('pid', 'unknown')
        hint = info.get('worktree_hint', '')
        hint_str = f" ({hint})" if hint else ""
        print(f"  {port} -> {exe} (PID {pid}){hint_str}")
    print()
    policy = get_recovery_policy(observation_only=True)
    print("Recovery:")
    print("  observation-only")
    print("  no actions taken")
    return 0


def handle_infra_diagnose(args):
    """Handle 'vaelor infra diagnose' command."""
    # Create args with proper node
    args.infra_node = args.prompt[0] if args.prompt else "skyai"
    return handle_infra_status(args)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # Detect infra subcommand: first positional arg is 'infra' and second is 'status'/'diagnose'
    if args.prompt and args.prompt[0] == "infra":
        if len(args.prompt) >= 2 and args.prompt[1] in ("status", "diagnose"):
            # Rewrite args for infra handling
            args.infra_command = args.prompt[1]
            if args.infra_command == "diagnose" and len(args.prompt) >= 3:
                args.infra_node = args.prompt[2]
            else:
                args.infra_node = "skyai"
            if args.infra_command == "status":
                return handle_infra_status(args)
            elif args.infra_command == "diagnose":
                return handle_infra_diagnose(args)
        else:
            parser.print_help()
            return 1

    runtime = VaelorRuntime()
    if args.prompt:
        prompt = " ".join(args.prompt)
        response = runtime.brain.research_answer(prompt) if args.research else runtime.brain.think(prompt)
        print(json.dumps({"response": response}) if args.json else response)
        return 0

    terminals = TerminalSessionManager()
    terminal_id = None
    if args.terminal:
        terminal_id = terminals.create(args.cwd)["id"]
    print(f"Vaelor {VAELOR_VERSION} - type /help for commands")
    try:
        while True:
            text = input("Vaelor > ").strip()
            if not text:
                continue
            if text in ("/quit", "/exit", "quit", "exit"):
                return 0
            if text == "/help":
                print("/terminal [cwd], /close, !command, /research topic, /quit, or enter a natural-language request")
                continue
            if text.startswith("/terminal"):
                if terminal_id:
                    terminals.close(terminal_id)
                cwd = text[len("/terminal"):].strip() or args.cwd
                terminal_id = terminals.create(cwd)["id"]
                print(f"Persistent terminal {terminal_id} started")
                continue
            if text == "/close":
                if terminal_id:
                    terminals.close(terminal_id)
                    terminal_id = None
                print("Persistent terminal closed")
                continue
            if text.startswith("!"):
                if not terminal_id:
                    terminal_id = terminals.create(args.cwd)["id"]
                result = terminals.execute(terminal_id, text[1:].strip())
                print(result["output"] or f"[exit {result['returncode']}; no output]")
                continue
            if text.startswith("/research "):
                print(runtime.brain.research_answer(text[len("/research "):].strip()))
            else:
                print(runtime.brain.think(text))
    except (EOFError, KeyboardInterrupt):
        return 0
    finally:
        terminals.close_all()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())