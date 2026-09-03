"""Native Vaelor command-line interface."""
from __future__ import annotations

import argparse
import json

from core.runtime import VaelorRuntime
from core.terminal_session import TerminalSessionManager
from core.version import VAELOR_VERSION


def build_parser():
    parser = argparse.ArgumentParser(description="Vaelor local AI assistant")
    parser.add_argument("prompt", nargs="*", help="Run one prompt and exit")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    parser.add_argument("--terminal", action="store_true", help="Start in persistent terminal mode")
    parser.add_argument("--cwd", help="Initial terminal working directory")
    parser.add_argument("--version", action="version", version=VAELOR_VERSION)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    runtime = VaelorRuntime()
    if args.prompt:
        prompt = " ".join(args.prompt)
        response = runtime.brain.think(prompt)
        print(json.dumps({"response": response}) if args.json else response)
        return 0

    terminals = TerminalSessionManager()
    terminal_id = None
    if args.terminal:
        terminal_id = terminals.create(args.cwd)["id"]
    print(f"Vaelor {VAELOR_VERSION} — type /help for commands")
    try:
        while True:
            text = input("Vaelor > ").strip()
            if not text:
                continue
            if text in ("/quit", "/exit", "quit", "exit"):
                return 0
            if text == "/help":
                print("/terminal [cwd], /close, !command, /quit, or enter a natural-language request")
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
            print(runtime.brain.think(text))
    except (EOFError, KeyboardInterrupt):
        return 0
    finally:
        terminals.close_all()


if __name__ == "__main__":
    raise SystemExit(main())
