def clean_input(command):
    command = command.strip()

    if command.lower().startswith("vaelor >"):
        command = command[8:].strip()

    return command


def parse_command(command):
    """
    Parses raw input into (mode, prompt).
    mode is one of: "code", "remember", "fast", "think", "roadmap", "tool", "tools"
    Shared by both the CLI and the API so behavior never drifts apart.
    """
    command = clean_input(command)
    command_lower = command.lower()

    if command_lower.startswith("code:"):
        return "code", command[5:].strip()

    elif command_lower.startswith("remember:"):
        return "remember", command[9:].strip()

    elif command_lower.startswith("roadmap:"):
        return "roadmap", command[8:].strip()

    elif command_lower.startswith("fast:"):
        return "fast", command[5:].strip()

    elif command_lower.startswith("analyze:"):
        return "think", command[8:].strip()

    elif command_lower.startswith("tools"):
        return "tools", ""

    elif command_lower.startswith("tool:"):
        return "tool", command[5:].strip()

    else:
        return "think", command


def parse_tool_command(prompt):
    """
    Parses a 'tool:' prompt into (tool_name, kwargs).
    Format: tool: <tool_name> key=value key2=value2
    Example: tool: file_reader path=vaelor.py
    """
    parts = prompt.strip().split()

    if not parts:
        return None, {}

    tool_name = parts[0]
    kwargs = {}

    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            kwargs[key] = value

    return tool_name, kwargs