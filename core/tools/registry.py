"""
Vaelor Tool Registry

This is the foundation of Vaelor's ability to interact with his own
project files and environment through controlled, registered functions
instead of unrestricted access.

Every tool must be registered here with:
- a unique name
- a short description (used so Vaelor can explain what he did)
- a read_only flag (True = safe to run automatically, False = requires
  human approval before running - not built yet, refuses for now)
- the function that actually performs the work
"""

class Tool:
    def __init__(self, name, description, read_only, func):
        self.name = name
        self.description = description
        self.read_only = read_only
        self.func = func

    def run(self, **kwargs):
        return self.func(**kwargs)


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, description, read_only, func):
        self._tools[name] = Tool(name, description, read_only, func)

    def list_tools(self):
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "read_only": tool.read_only
            }
            for tool in self._tools.values()
        ]

    def get(self, name):
        return self._tools.get(name)

    def execute(self, name, **kwargs):
        tool = self.get(name)

        if tool is None:
            return f"Unknown tool: {name}. Type 'tools' to see available tools."

        if not tool.read_only:
            return (
                f"Tool '{name}' modifies the project and requires human approval. "
                f"This safety gate is not yet built - refusing to run automatically."
            )

        try:
            return tool.run(**kwargs)
        except Exception as e:
            return f"Tool '{name}' failed: {e}"


registry = ToolRegistry()


def register_all_tools():
    """
    Import and register every available tool.
    Called once when this module is first imported.
    """
    from .project_scanner import scan_project
    from .file_reader import read_file
    from .file_editor import propose_edit

    registry.register(
        name="project_scanner",
        description="Lists the folder and file structure of the Vaelor project (excludes .venv and __pycache__).",
        read_only=True,
        func=scan_project
    )

    registry.register(
        name="file_reader",
        description="Reads the contents of a single file inside the Vaelor project. Requires 'path' argument (relative to project root).",
        read_only=True,
        func=read_file
    )

    registry.register(
        name="file_editor_propose",
        description="Proposes an edit to a file and shows a diff. Writes NOTHING - a pending proposal must be applied with 'approve: <id>'. Best used via the dedicated 'propose:' CLI command for multi-line content.",
        read_only=True,
        func=propose_edit
    )


register_all_tools()