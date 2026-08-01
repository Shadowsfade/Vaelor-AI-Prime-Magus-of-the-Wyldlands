"""Vaelor Tool Registry"""

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
        return [{"name": t.name, "description": t.description, "read_only": t.read_only} for t in self._tools.values()]
    def get(self, name):
        return self._tools.get(name)
    def execute(self, name, **kwargs):
        tool = self.get(name)
        if tool is None:
            return f"Unknown tool: {name}. Type 'tools' to see available tools."
        if not tool.read_only:
            return f"Tool '{name}' requires approval and will not run automatically."
        try:
            return tool.run(**kwargs)
        except Exception as e:
            return f"Tool '{name}' failed: {e}"

registry = ToolRegistry()

def register_all_tools():
    from .project_scanner import scan_project
    from .file_reader import read_file
    from .file_editor import propose_edit
    from .cleaner import scan_unused_files
    registry.register("project_scanner", "List project folder/file structure.", True, scan_project)
    registry.register("file_reader", "Read a project file. Requires path=.", True, read_file)
    registry.register("file_editor_propose", "Propose a file edit/diff without writing.", True, propose_edit)
    registry.register("scan_unused_files", "Find unused/empty Python files.", True, scan_unused_files)
    try:
        from .web_research import web_search, fetch_url
        registry.register("web_search", "Free web search (DuckDuckGo). Requires query=.", True, web_search)
        registry.register("fetch_url", "Fetch public URL text. Requires url=.", True, fetch_url)
    except Exception:
        pass

register_all_tools()
