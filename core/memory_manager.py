import re

from .memory import VaelorMemory


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.I)


class VaelorMemoryManager:
    """Higher-level memory intelligence for Vaelor."""

    def __init__(self, path=None):
        self.memory = VaelorMemory(path)

    @staticmethod
    def _tokens(text):
        return set(TOKEN_RE.findall(str(text).casefold()))

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

    def remember(self, category, content, importance=1, source="user_explicit", confidence=1.0, tags=None):
        if category == "fact":
            category = self.classify_memory(content)
        return self.memory.remember(category, content, importance, source, confidence, tags)

    def recall(self, category=None):
        return self.memory.recall(category)

    def score_memory(self, memory, prompt):
        score = 0.0
        content = memory.get("content", "").lower()
        prompt_l = prompt.lower()
        words = self._tokens(prompt_l)
        content_words = self._tokens(content)
        overlap = words & content_words
        score += len(overlap) * 3
        if words:
            score += 5 * (len(overlap) / len(words))
        # bigram bonus
        toks = TOKEN_RE.findall(prompt_l)
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
        score += max(0, min(int(memory.get("importance", 1) or 1), 10))
        score *= max(0.0, min(float(memory.get("confidence", 1.0) or 0), 1.0))
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
        # Only authoritative rules are global; ordinary rules still require relevance.
        rules = [
            m for m in archive
            if m.get("category") == "rule"
            and int(m.get("importance", 1) or 1) >= 8
            and float(m.get("confidence", 1.0) or 0) >= 0.8
        ]
        selected = []
        seen_ids = set()
        for m in rules[:3] + ranked:
            mid = m.get("id") or (m.get("category"), m.get("content"))
            if mid in seen_ids:
                continue
            # skip zero-relevance non-rules
            if m not in rules and self.score_memory(m, prompt) < 6:
                continue
            seen_ids.add(mid)
            selected.append(m)
            if len(selected) >= limit:
                break

        if not selected:
            return ""

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
            key = (
                item.get("category", "fact"),
                " ".join(str(item.get("content", "")).casefold().split()),
            )
            if key not in seen:
                cleaned.append(item)
                seen.add(key)
        self.memory._save(cleaned)
        return len(cleaned)
