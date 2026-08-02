"""Vaelor Tool Registry — sandbox god-mode tools."""

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
    def specs_for_prompt(self):
        lines = []
        for t in self._tools.values():
            flag = "read-only" if t.read_only else "sandbox-god"
            lines.append(f"- {t.name} [{flag}]: {t.description}")
        return "\n".join(lines)
    def execute(self, name, **kwargs):
        tool = self.get(name)
        if tool is None:
            return f"Unknown tool: {name}. Type 'tools' to see available tools."
        try:
            return tool.run(**kwargs)
        except Exception as e:
            return f"Tool '{name}' failed: {e}"

registry = ToolRegistry()

def register_all_tools():
    from .project_scanner import scan_project
    from .file_reader import read_file
    from .file_editor import propose_edit, stage_file
    from .cleaner import scan_unused_files
    from .approval import approve_change, reject_change
    from .proposals import list_pending

    registry.register("project_scanner", "List project folder/file structure.", True, scan_project)
    registry.register("file_reader", "Read a project file. Requires path=.", True, read_file)
    registry.register("file_editor_propose", "Propose file edit/diff without writing. Requires path=.", True, propose_edit)
    registry.register("stage_file", "Create staging copy for editing. Requires path=.", True, stage_file)
    registry.register("scan_unused_files", "Find unused/empty Python files.", True, scan_unused_files)
    registry.register("list_proposals", "List pending file-change proposals.", True, lambda: str(list_pending()))
    registry.register("approve_change", "Apply pending proposal. Requires proposal_id=.", False, lambda proposal_id="", confirm="yes": approve_change(proposal_id))
    registry.register("reject_change", "Reject pending proposal. Requires proposal_id=.", True, lambda proposal_id="": reject_change(proposal_id))

    try:
        from .web_research import web_search, fetch_url
        registry.register("web_search", "Free web research. Requires query=.", True, web_search)
        registry.register("fetch_url", "Fetch public URL text. Requires url=.", True, fetch_url)
    except Exception:
        pass

    try:
        from .shell_exec import (
            shell_exec, shell_which, set_autonomy_mode, get_autonomy_status, describe_sandbox
        )
        registry.register("shell_exec", "Broad shell access. Blocks only core OS destruction. Args: command=, cwd=, timeout=.", False, shell_exec)
        registry.register("shell_which", "Locate executable. Args: command=git", True, shell_which)
        registry.register("set_autonomy_mode", "Set mode=supervised|trusted|admin. Core OS delete still blocked.", False, set_autonomy_mode)
        registry.register("get_autonomy_status", "Show autonomy / OS-safe policy config.", True, get_autonomy_status)
        registry.register("describe_sandbox", "Explain full-access OS-safe policy and protected delete roots.", True, describe_sandbox)
    except Exception as e:
        print("shell register fail", e)

    try:
        from .git_ops import (
            git_status, git_diff, git_log, git_branch, git_remote,
            git_add, git_commit, git_checkout, git_push, git_pull,
        )
        registry.register("git_status", "Git status -sb", True, git_status)
        registry.register("git_diff", "Git diff. optional staged=yes", True, git_diff)
        registry.register("git_log", "Recent commits. optional limit=10", True, git_log)
        registry.register("git_branch", "List branches.", True, git_branch)
        registry.register("git_remote", "Show remotes", True, git_remote)
        registry.register("git_add", "Stage files. path=.", False, git_add)
        registry.register("git_commit", "Commit. message=...", False, git_commit)
        registry.register("git_checkout", "Checkout/create branch.", False, git_checkout)
        registry.register("git_pull", "Pull remote.", False, git_pull)
        registry.register("git_push", "Push remote (force disabled by failsafe).", False, git_push)
    except Exception as e:
        print("git register fail", e)

register_all_tools()

try:
    from .unreal_tools import unreal_status, unreal_open_epic_download, unreal_launch_epic
    registry.register("unreal_status", "Detect Unreal Engine/Epic Launcher/.uprojects and explain next install steps.", True, unreal_status)
    registry.register("unreal_open_epic_download", "Open free Epic Games Launcher download page in browser.", False, unreal_open_epic_download)
    registry.register("unreal_launch_epic", "Launch Epic Games Launcher if installed.", False, unreal_launch_epic)
except Exception:
    pass

