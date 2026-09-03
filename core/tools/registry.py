"""Vaelor Tool Registry."""
import inspect

class Tool:
    def __init__(self, name, description, read_only, func):
        self.name = name
        self.description = description
        self.read_only = read_only
        self.func = func
    def run(self, **kwargs):
        return self.func(**kwargs)
    def argument_schema(self):
        parameters = {}
        accepts_extra = False
        for name, param in inspect.signature(self.func).parameters.items():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                accepts_extra = True
                continue
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.POSITIONAL_ONLY):
                continue
            annotation = param.annotation
            type_name = None if annotation is inspect.Parameter.empty else getattr(annotation, "__name__", str(annotation))
            parameters[name] = {
                "required": param.default is inspect.Parameter.empty,
                "type": type_name,
            }
        return {"parameters": parameters, "accepts_extra": accepts_extra}

class ToolRegistry:
    def __init__(self):
        self._tools = {}
    def register(self, name, description, read_only, func):
        self._tools[name] = Tool(name, description, read_only, func)
    def list_tools(self):
        return [
            {
                "name": t.name,
                "description": t.description,
                "read_only": t.read_only,
                "arguments": t.argument_schema(),
            }
            for t in self._tools.values()
        ]
    def get(self, name):
        return self._tools.get(name)
    def specs_for_prompt(self):
        lines = ["# Registered tools (" + str(len(self._tools)) + ") — invoke via JSON actions"]
        # group mutating vs read
        reads = [t for t in self._tools.values() if t.read_only]
        muts = [t for t in self._tools.values() if not t.read_only]
        lines.append("## Read-only")
        for t in sorted(reads, key=lambda x: x.name):
            lines.append(f"- {t.name}{self._signature_text(t)}: {t.description}")
        lines.append("## Mutating (admin auto-confirm=yes)")
        for t in sorted(muts, key=lambda x: x.name):
            lines.append(f"- {t.name}{self._signature_text(t)}: {t.description}")
        lines.append('Format: {"thought":"...","actions":[{"tool":"name","arguments":{}}],"final":null}')
        return "\n".join(lines)
    @staticmethod
    def _signature_text(tool):
        schema = tool.argument_schema()["parameters"]
        args = [name if meta["required"] else f"{name}?" for name, meta in schema.items()]
        return "(" + ", ".join(args) + ")"
    def accepts_argument(self, name, argument):
        tool = self.get(name)
        if tool is None:
            return False
        schema = tool.argument_schema()
        return argument in schema["parameters"] or schema["accepts_extra"]
    def validate_call(self, name, arguments):
        tool = self.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        if not isinstance(arguments, dict):
            return "arguments must be an object"
        schema = tool.argument_schema()
        unknown = sorted(set(arguments) - set(schema["parameters"]))
        if unknown and not schema["accepts_extra"]:
            return "unexpected argument(s): " + ", ".join(unknown)
        missing = [
            key for key, meta in schema["parameters"].items()
            if meta["required"] and key not in arguments
        ]
        if missing:
            return "missing required argument(s): " + ", ".join(missing)
        return None
    def execute(self, name, **kwargs):
        tool = self.get(name)
        if tool is None:
            return f"Unknown tool: {name}. Type 'tools' to see available tools."
        try:
            return tool.run(**kwargs)
        except Exception as e:
            return f"Tool '{name}' failed: {e}"
    def names(self):
        return sorted(self._tools.keys())

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
    registry.register(
        "approve_change",
        "Apply pending proposal. Requires proposal_id= and confirm=yes.",
        False,
        lambda proposal_id="", confirm="no": (
            approve_change(proposal_id)
            if str(confirm).lower() in ("yes", "true", "1", "y")
            else "Refused: approve_change needs confirm=yes"
        ),
    )
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
        registry.register("shell_exec", "Admin shell (auto-confirm in admin). OS core wipe blocked. command= cwd= timeout=", False, shell_exec)
        registry.register("shell_which", "Locate executable. command=git", True, shell_which)
        registry.register("set_autonomy_mode", "Set mode=supervised|trusted|admin.", False, set_autonomy_mode)
        registry.register("get_autonomy_status", "Show autonomy config.", True, get_autonomy_status)
        registry.register("describe_sandbox", "Explain OS-safe full-access policy.", True, describe_sandbox)
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
        registry.register("git_push", "Push remote (no force).", False, git_push)
    except Exception as e:
        print("git register fail", e)

    try:
        from .fs_ops import (
            list_dir, glob_files, read_text_file, write_text_file, apply_patch,
            grep_files, make_dir, delete_path,
        )
        registry.register("list_dir", "List directory. path=. recursive=yes|no", True, list_dir)
        registry.register("glob_files", "Glob files. pattern=**/*.py path=.", True, glob_files)
        registry.register("read_text_file", "Read text file in allowed roots. path= start_line= end_line=", True, read_text_file)
        registry.register("write_text_file", "Create/edit file (non-OS-core). path= content= mode=overwrite|append confirm=yes", False, write_text_file)
        registry.register("apply_patch", "Exact text replace. path= old= new= confirm=yes", False, apply_patch)
        registry.register("grep_files", "Search contents. query= path=. glob=*.py", True, grep_files)
        registry.register("make_dir", "Create directory. path= confirm=yes", False, make_dir)
        registry.register("delete_path", "Delete file/dir (not OS core). path= recursive=yes|no confirm=yes", False, delete_path)
    except Exception as e:
        print("fs_ops register fail", e)

    try:
        from .console_homebrew import console_homebrew_help, console_scope_guard
        registry.register("console_homebrew_help", "Game-console-only verified public CFW/homebrew guides. console=switch|3ds|wiiu|wii|vita|psp goal=", True, console_homebrew_help)
        registry.register("console_scope_guard", "Confirm target is game-console homebrew scope.", True, console_scope_guard)
    except Exception as e:
        print("console register fail", e)


    try:
        from .diagnostics_tools import system_status, check_port, process_list
        registry.register("system_status", "Host CPU/RAM/disk and toolchain which.", True, system_status)
        registry.register("check_port", "Check if TCP port open. port=8000 host=localhost", True, check_port)
        registry.register("process_list", "List processes. query= limit=30", True, process_list)
    except Exception as e:
        print("diagnostics register fail", e)

    try:
        from .unreal_tools import unreal_status, unreal_open_epic_download, unreal_launch_epic
        registry.register("unreal_status", "Detect Unreal/Epic/.uprojects.", True, unreal_status)
        registry.register("unreal_open_epic_download", "Open Epic download page.", False, unreal_open_epic_download)
        registry.register("unreal_launch_epic", "Launch Epic if installed.", False, unreal_launch_epic)
    except Exception:
        pass

register_all_tools()
