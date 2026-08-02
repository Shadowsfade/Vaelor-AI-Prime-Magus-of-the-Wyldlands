from core.runtime import VaelorRuntime
from spellbook.command_parser import parse_command, parse_tool_command


VAELOR_VERSION = "0.9.0"

runtime = VaelorRuntime()
brain = runtime.brain


def banner():
    print("""
=================================
        VAELOR CORE ONLINE
=================================
Version: {}
Spellbook: Connected
Memory: Connected
Tools: Connected
Write Tools: Connected (stage -> propose -> approve)
Natural Command Routing: Enabled
=================================
""".format(VAELOR_VERSION))


def process_command(command):
    mode, prompt = parse_command(command)

    if mode == "code":
        print("\n[Spell Selected: code_forge]")
        return brain.create(prompt)

    elif mode == "remember":
        brain.remember("fact", prompt)
        return f"Understood. I will remember: {prompt}"

    elif mode == "roadmap":
        print("\n[Spell Selected: reflect]")
        return brain.reflect(prompt)

    elif mode == "fast":
        print("\n[Spell Selected: fast_thought]")
        return brain.fast(prompt)

        elif mode == "agent":
        print("\n[Spell Selected: agent_loop]")
        return brain.act(prompt)
    
    elif mode == "shell":
        print("\n[Spell Selected: shell_exec]")
        conf = "yes" if "confirm=yes" in prompt.lower() else "no"
        import re as _re
        cmd = _re.sub(r"confirm=yes", "", prompt, flags=_re.I).strip()
        return brain.use_tool("shell_exec", command=cmd, confirm=conf)
    
    elif mode == "git":
        print("\n[Spell Selected: git]")
        parts = prompt.split(None, 1)
        sub = (parts[0].lower() if parts else "status")
        rest = parts[1] if len(parts) > 1 else ""
        if sub == "status":
            return brain.use_tool("git_status")
        if sub == "diff":
            return brain.use_tool("git_diff")
        if sub == "log":
            return brain.use_tool("git_log")
        if sub == "branch":
            return brain.use_tool("git_branch")
        if sub == "remote":
            return brain.use_tool("git_remote")
        if sub == "add":
            return brain.use_tool("git_add", path=rest or ".", confirm="yes" if "confirm=yes" in rest.lower() else "no")
        if sub == "commit":
            conf = "yes" if "confirm=yes" in rest.lower() else "no"
            msg = rest.replace("confirm=yes", "").strip()
            return brain.use_tool("git_commit", message=msg, confirm=conf)
        if sub == "push":
            return brain.use_tool("git_push", confirm="yes" if "confirm=yes" in rest.lower() else "no")
        if sub == "pull":
            return brain.use_tool("git_pull", confirm="yes" if "confirm=yes" in rest.lower() else "no")
        return "Usage: git: status|diff|log|branch|remote|add|commit|push|pull"
    
    elif mode == "tools":
        print("\n[Spell Selected: tools]")
        return brain.use_tool(prompt)
    
    elif mode == "tools":
        return brain.list_tools()

    elif mode == "tool":
        print("\n[Spell Selected: tool use]")
        tool_name, kwargs = parse_tool_command(prompt)
        if not tool_name:
            return "Usage: tool: <tool_name> key=value"
        return brain.use_tool(tool_name, **kwargs)

    elif mode == "stage":
        if not prompt:
            return "Usage: stage: <path relative to project root>"
        return brain.stage_edit(prompt)

    elif mode == "propose":
        if not prompt:
            return "Usage: propose: <path relative to project root>"
        return brain.propose_edit(prompt)

    elif mode == "approve":
        if not prompt:
            return "Usage: approve: <proposal id>"
        return brain.approve_change(prompt)

    elif mode == "reject":
        if not prompt:
            return "Usage: reject: <proposal id>"
        return brain.reject_change(prompt)

    elif mode == "diffs":
        return brain.list_proposals()

    else:
        print("\n[Spell Selected: core_reasoning]")
        return brain.think(prompt)


if __name__ == "__main__":
    banner()

    while True:
        user_input = input("\nVaelor > ")

        if user_input.lower() in ["exit", "quit"]:
            print("Vaelor shutting down.")
            break

        response = process_command(user_input)

        print("\n" + response)
