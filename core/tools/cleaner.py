import os
import ast

# Critical folders and files Vaelor should NEVER touch or delete
PROTECTED_PATHS = {
    "vaelor.py",
    "api/server.py",
    "core/__init__.py",
    "core/__main__.py"
}

# Entire directories that should be excluded from unused scanning
PROTECTED_DIRS = {
    "core",
    "spellbook",
    "api"
}

def get_all_python_files(root_dir="."):
    """Collects all .py files excluding .venv, __pycache__, and git folders."""
    py_files = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ('.venv', 'venv', '__pycache__', '.git', '.staging')]
        for file in files:
            if file.endswith('.py'):
                rel_path = os.path.relpath(os.path.join(root, file), root_dir)
                py_files.append(rel_path.replace("\\", "/"))
    return py_files

def scan_unused_files(root_dir="."):
    """Scans project files for truly empty scripts or unreferenced test files."""
    all_files = get_all_python_files(root_dir)
    imported_modules = set()

    for rel_path in all_files:
        full_path = os.path.join(root_dir, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_modules.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported_modules.add(node.module)
        except Exception:
            continue

    candidates = []

    for rel_path in all_files:
        # Skip explicitly protected core entry files
        if rel_path in PROTECTED_PATHS:
            continue

        # Skip core architecture subdirectories—only analyze root scripts/tests unless empty
        top_dir = rel_path.split('/')[0]
        if top_dir in PROTECTED_DIRS and not rel_path.endswith('__init__.py'):
            continue

        full_path = os.path.join(root_dir, rel_path)
        is_empty = os.path.getsize(full_path) == 0

        # Don't delete non-empty __init__.py files
        if rel_path.endswith('__init__.py') and not is_empty:
            continue

        mod_name = rel_path.replace('.py', '').replace('/', '.')
        is_imported = any(
            mod_name == imp or imp.startswith(mod_name + ".")
            for imp in imported_modules
        )

        if is_empty or not is_imported:
            reason = "File is empty" if is_empty else "No imports detected across codebase"
            candidates.append({"file": rel_path, "reason": reason})

    return candidates