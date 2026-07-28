from .memory import VaelorMemory


class VaelorMemoryManager:
    """
    Higher-level intelligence layer for Vaelor memory.
    """

    def __init__(self):
        self.memory = VaelorMemory()

    def remember(self, category, content, importance=1):
        return self.memory.remember(
            category,
            content,
            importance
        )

    def recall(self, category=None):
        return self.memory.recall(
            category
        )

    def build_context(self, prompt, limit=5):
        """
        Build a text block of relevant remembered facts
        to inject into a reasoning prompt.
        """
        archive = self.memory.recall()

        if not archive:
            return ""

        sorted_memories = sorted(
            archive,
            key=lambda m: m.get("importance", 1),
            reverse=True
        )

        top_memories = sorted_memories[:limit]

        lines = [f"- {m['content']}" for m in top_memories]

        return "Known context:\n" + "\n".join(lines)

    def cleanup_duplicates(self):
        archive = self.memory.recall()
        cleaned = []
        seen = set()

        for item in archive:
            key = (item["category"], item["content"])
            if key not in seen:
                cleaned.append(item)
                seen.add(key)

        self.memory._save(cleaned)
        return len(cleaned)