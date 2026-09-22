"""Manual archive maintenance script (not a test).

This file is named ``test_*`` only for historical reasons, so pytest imports
it during collection. Every operation here writes to personal memory
(``memory/archive.json``), therefore all side effects are guarded behind
``__main__``: importing this module must stay read-only, and collection must
never be able to modify protected memory files.

Run it explicitly when you actually want to clean duplicates:

    python test_memory_manager.py
"""
from core.memory_manager import VaelorMemoryManager


def main() -> None:
    memory = VaelorMemoryManager()

    removed = memory.cleanup_duplicates()
    print(f"Cleanup complete. Memories remaining: {removed}")

    memory.remember(
        "fact",
        "The Architect is building Vaelor inside Project Wyld.",
        importance=10,
    )

    print("\nRelevant Archive Memories:\n")
    for item in memory.recall("fact"):
        print(f"- [{item['category']}] {item['content']}")


if __name__ == "__main__":
    main()
