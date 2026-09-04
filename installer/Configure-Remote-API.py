"""Generate Vaelor's local bearer token without enabling network binding."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.api_security import generate_api_access_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace an existing local token")
    args = parser.parse_args()
    try:
        token = generate_api_access_token(force=args.force)
    except FileExistsError as exc:
        print(str(exc))
        print("Use --force only when you intentionally want to invalidate the old token.")
        return 2
    print("Remote API authentication token (shown once; keep it private):")
    print(token)
    print("Authentication is configured. Network binding remains loopback-only until explicitly changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
