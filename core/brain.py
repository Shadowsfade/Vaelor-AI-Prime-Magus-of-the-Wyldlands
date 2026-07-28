from spellbook.spell_router import cast_spell

from .memory_manager import VaelorMemoryManager
from .tools.registry import registry as tool_registry


class VaelorBrain:
    """
    Primary reasoning interface for Vaelor.

    Handles:
    - reasoning requests (core_reasoning, 14B)
    - fast/lightweight requests (fast_thought, 3B)
    - coding requests (code_forge)
    - archive recall
    - roadmap / self-awareness of project status
    - tool use (observe -> act, read-only for now)
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self.memory = VaelorMemoryManager()

    def think(self, prompt):
        """
        Route a thought through Vaelor's primary reasoning system (14B).
        Relevant memories are injected into context.
        """
        memory_context = self.memory.build_context(prompt)

        enhanced_prompt = (
            memory_context
            + "\n\nCurrent request:\n"
            + prompt
        )

        response = cast_spell(
            "core_reasoning",
            enhanced_prompt
        )

        return response

    def fast(self, prompt):
        """
        Route a thought through the lightweight fast model (3B).
        No memory injection - kept minimal for speed.
        """
        return cast_spell(
            "fast_thought",
            prompt
        )

    def create(self, prompt):
        """
        Route coding tasks through AiderSpell.
        """
        return cast_spell(
            "code_forge",
            prompt
        )

    def remember(self, category, content):
        """
        Manually store archive knowledge.
        """
        return self.memory.remember(
            category,
            content
        )

    def reflect(self, prompt):
        """
        Answer questions about Vaelor's own development status,
        using the roadmap as grounding context.
        """
        roadmap = self.runtime.roadmap

        roadmap_text = (
            "Current Vaelor version: " + roadmap.get("current_version", "unknown")
            + "\n\nCompleted:\n"
            + "\n".join("- " + item for item in roadmap.get("completed", []))
            + "\n\nIn progress:\n"
            + "\n".join("- " + item for item in roadmap.get("in_progress", []))
            + "\n\nNext goals:\n"
            + "\n".join("- " + item for item in roadmap.get("next_goals", []))
            + "\n\nHardware constraints:\n"
            + roadmap.get("hardware_constraints", "")
        )

        enhanced_prompt = (
            "You are being asked about your own development status. "
            "Here is your current roadmap:\n\n"
            + roadmap_text
            + "\n\nQuestion:\n"
            + prompt
        )

        return cast_spell(
            "core_reasoning",
            enhanced_prompt
        )

    def list_tools(self):
        """
        Return the list of tools Vaelor currently has access to.
        """
        tools = tool_registry.list_tools()

        if not tools:
            return "No tools are registered yet."

        lines = []
        for tool in tools:
            access = "read-only" if tool["read_only"] else "requires approval"
            lines.append(f"- {tool['name']} ({access}): {tool['description']}")

        return "Available tools:\n" + "\n".join(lines)

    def use_tool(self, tool_name, **kwargs):
        """
        Execute a registered tool directly and return its raw result.
        """
        return tool_registry.execute(tool_name, **kwargs)