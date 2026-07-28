from core.memory_manager import VaelorMemoryManager


memory = VaelorMemoryManager()


removed = memory.cleanup_duplicates()

print(
    f"Cleanup complete. Memories remaining: {removed}"
)


memory.remember(
    "fact",
    "The Architect is building Vaelor inside Project Wyld.",
    importance=10
)


print("\nRelevant Archive Memories:\n")


for item in memory.recall("fact"):

    print(
        f"- [{item['category']}] {item['content']}"
    )