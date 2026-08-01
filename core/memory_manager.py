from .memory import VaelorMemory


class VaelorMemoryManager:
    """Higher-level memory intelligence for Vaelor."""

    def __init__(self):
        self.memory = VaelorMemory()

    def classify_memory(self, content):
        text = content.lower()
        if any(w in text for w in [
            "should not", "do not", "must not", "must", "rule",
            "constraint", "not assumed", "do not assume", "never",
        ]):
            return "rule"
        if any(w in text for w in [
            "project wyld", "roadmap", "architecture", "design decision",
            "vaelor server", "priority",
        ]):
            return "project"
        if any(w in text for w in [
            "unreal", "unity", "inventory", "code", "system", "script",
            "data asset", "api", "ollama", "fastapi",
        ]):
            return "technical"
        if any(w in text for w in [
            "wyldlands", "creature", "magic", "spell", "lore", "archive",
        ]):
            return "world"
        if any(w in text for w in [
            "vaelor", "architect", "prefers", "identity", "apprentice",
        ]):
            return "identity"
        return "fact"

    def remember(self, category, content, importance=1):
        if category == "fact":
            category = self.classify_memory(content)
        return self.memory.remember(category, content, importance)

    def recall(self, category=None):
        return self.memory.recall(category)

    def score_memory(self, memory, prompt):
        score = 0
        content = memory.get("content", "").lower()
        prompt_l = prompt.lower()
        # token overlap
        words = [w.strip(".,!?;:()[]\"'") for w in prompt_l.split() if len(w) > 2]
        seen = set()
        for word in words:
            if word in seen:
                continue
            seen.add(word)
            if word in content:
                score += 2
        # bigram bonus
        toks = words
        for i in range(len(toks) - 1):
            bigram = toks[i] + " " + toks[i + 1]
            if bigram in content:
                score += 3

        authority = {
            "rule": 12,
            "project": 8,
            "technical": 6,
            "identity": 5,
            "world": 4,
            "fact": 2,
        }
        score += authority.get(memory.get("category", "fact"), 1)
        score += int(memory.get("importance", 1) or 1)
        return score

    def build_context(self, prompt, limit=8):
        archive = self.memory.recall()
        if not archive:
            return ""

        ranked = sorted(
            archive,
            key=lambda m: self.score_memory(m, prompt),
            reverse=True,
        )
        # always include top rules even if weak lexical match
        rules = [m for m in archive if m.get("category") == "rule"]
        selected = []
        seen_ids = set()
        for m in rules[:3] + ranked:
            mid = m.get("id") or (m.get("category"), m.get("content"))
            if mid in seen_ids:
                continue
            # skip zero-relevance non-rules
            if m.get("category") != "rule" and self.score_memory(m, prompt) < 4:
                continue
            seen_ids.add(mid)
            selected.append(m)
            if len(selected) >= limit:
                break

        if not selected:
            selected = ranked[: min(3, limit)]

        lines = [
            f"- [{m.get('category', 'fact')}|imp={m.get('importance', 1)}] {m['content']}"
            for m in selected
        ]
        return (
            "Known archive context (prioritize rules/project facts):\n"
            + "\n".join(lines)
        )

    def cleanup_duplicates(self):
        archive = self.memory.recall()
        cleaned, seen = [], set()
        for item in archive:
            key = (item["category"], item["content"])
            if key not in seen:
                cleaned.append(item)
                seen.add(key)
        self.memory._save(cleaned)
        return len(cleaned)
