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
    parser.add_argument("--guardian-action", dest="guardian_action",
                        help=argparse.SUPPRESS)
    return parser


def handle_infra_status(args):
    """Handle 'vaelor infra status' command."""
    from core.infra.classifier import get_state_summary
    from core.infra.node_config import NodeConfigError, load_node_registry
    from core.infra.observation import build_local_observation
    from core.infra.recovery import get_recovery_policy

    worktree_root = _discover_worktree_root()

    try:
        registry = load_node_registry(root=worktree_root)
    except NodeConfigError as exc:
        print(f"MISCONFIGURED: {exc}", file=sys.stderr)
        return 1

    # Default to observing the local observer node. A remote target is
    # refused rather than silently mixing local evidence into it.
    target = args.infra_node or None

    try:
        scoped = build_local_observation(
            registry, target_name=target, worktree_path=str(worktree_root))
    except NodeConfigError as exc:
        print(f"MISCONFIGURED: {exc}", file=sys.stderr)
        return 1

    obs = scoped.observation

    if args.json:
        print(json.dumps(scoped.to_dict(), indent=2, default=str))
        return 0

    summary = get_state_summary(obs)
    print(f"{summary['node'].upper()}  [{scoped.scope}]")
    print(f"State:     {summary['state']}")
    print(f"Condition: {scoped.condition.value}")
    print(f"Observer:  {scoped.observer.name}"
          f"  Target host: {scoped.target.hostname}")
    print(f"Detail:    {scoped.explanation}")
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
    if scoped.contradictions:
        print("Contradictions:")
        for line in scoped.contradictions:
            print(f"  - {line}")
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
    get_recovery_policy(observation_only=True)
    print("Recovery:")
    print("  observation-only")
    print("  no actions taken")
    return 0


def handle_infra_diagnose(args):
    """Handle 'vaelor infra diagnose' command."""
    # Create args with proper node
    args.infra_node = args.prompt[0] if args.prompt else "legiongo"
    return handle_infra_status(args)


def handle_infra_guardian(args):
    """Handle 'vaelor infra guardian <status|run-once|run>' commands.

    These only observe, evaluate, or supervise the *local* configured
    Vaelor process. They never install an OS service, never touch
    Tailscale/firewall/power, and never execute a model-supplied command.
    """
    from core.infra.guardian import (
        GuardianConfigError,
        guardian_run,
        guardian_run_once,
        guardian_status,
    )

    worktree_root = _discover_worktree_root()
    action = args.guardian_action or "status"

    if action == "status":
        result = guardian_status(root=worktree_root)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return 0 if "error" not in result else 1
        _print_guardian_status(result)
        return 0 if "error" not in result else 1

    if action == "run-once":
        result = guardian_run_once(root=worktree_root)
        print(json.dumps(result, indent=2, default=str))
        return 0 if "error" not in result else 1

    if action == "run":
        code = guardian_run(root=worktree_root)
        return code

    print(f"unknown guardian action: {action}", file=sys.stderr)
    return 1


def _print_guardian_status(result: dict) -> None:
    if "error" in result:
        print(f"GUARDIAN ERROR: {result['error']}")
        return
    probe = result.get("probe", {})
    decision = result.get("decision", {})
    controller = result.get("controller", {})
    budget = controller.get("budget", {})
    breaker = controller.get("circuit_breaker", {})

    print("VAELOR GUARDIAN")
    print(f"Enabled          {'yes' if result.get('enabled') else 'no'}")
    print(f"Guardian PID     {result.get('guardian_pid')}")
    print(f"Guardian lock    {result.get('instance')}")
    print(f"Child PID file   {result.get('child_pid_status')}")
    print(f"Observed state   {probe.get('state')}")
    print(f"Decision         {decision.get('action')} ({decision.get('reason')})")
    print(f"Authority        {decision.get('authority')}")
    print()
    print(f"Process alive    {probe.get('process_alive')}")
    print(f"API responsive   {probe.get('api_responsive')}")
    print(f"Ready            {probe.get('ready')}")
    print()
    print(f"Restart budget   {budget.get('used')}/{budget.get('max_restarts')}"
          f" (exhausted={budget.get('exhausted')})")
    print(f"Circuit breaker  {breaker.get('state')}"
          f" failures={breaker.get('consecutive_failures')}"
          f"/{breaker.get('failure_threshold')}")
    print(f"Blocked reason   {controller.get('blocked_reason')}")
    print(f"Next delay       {controller.get('backoff', {}).get('next_delay_seconds')}s")
    print()
    health = probe.get("health")
    if health:
        print(f"Overall health   {health.get('overall')}")
        for reason in health.get("degraded_reasons", [])[:8]:
            print(f"  - {reason}")
        print()
    recent = result.get("recent_events", [])
    if recent:
        print("Recent events:")
        for ev in recent[-6:]:
            print(f"  {ev.get('at')} {ev.get('type')}: {ev.get('detail')}")
        print()
    print("Note: this command observes and plans only.")
    print("No OS service was installed and no system state was changed.")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # Detect infra subcommand: first positional arg is 'infra'
    if args.prompt and args.prompt[0] == "infra":
        sub = args.prompt[1] if len(args.prompt) >= 2 else None

        if sub == "guardian":
            action = args.prompt[2] if len(args.prompt) >= 3 else "status"
            if action in ("status", "run-once", "run"):
                args.guardian_action = action
                return handle_infra_guardian(args)
            parser.print_help()
            return 1

        if sub in ("status", "diagnose"):
            args.infra_command = sub
            if sub == "diagnose" and len(args.prompt) >= 3:
                args.infra_node = args.prompt[2]
            else:
                args.infra_node = None
            if sub == "status":
                return handle_infra_status(args)
            return handle_infra_diagnose(args)

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
