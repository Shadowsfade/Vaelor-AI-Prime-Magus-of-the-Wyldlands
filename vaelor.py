from core.runtime import VaelorRuntime
from spellbook.command_parser import parse_command, parse_tool_command


VAELOR_VERSION = "0.8.1"

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