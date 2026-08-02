"""CLI: write config/network.json with a free port for this install."""
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
sys.path.insert(0, str(root))
from core.netbind import resolve_bind
host, port, url = resolve_bind(root, force_new=False)
print(f"{host}:{port}")
print(url)
