import json
from pathlib import Path
import unittest

from core.agent_loop import build_react_system_prompt
from core.brain import VaelorBrain
from core.config_loader import config
from spellbook.llm_client import build_system_prompt as build_llm_prompt
from spellbook.ollama_client import build_system_prompt as build_legacy_ollama_prompt


class IdentityPromptTests(unittest.TestCase):
    def test_every_reasoning_path_keeps_prime_magus_and_world_reality(self):
        brain = VaelorBrain.__new__(VaelorBrain)
        brain.runtime = type("Runtime", (), {
            "identity": config.identity,
            "personality": config.personality,
        })()
        prompts = [
            VaelorBrain._identity_block(brain),
            build_react_system_prompt("(tools)"),
            build_llm_prompt(),
            build_legacy_ollama_prompt(),
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("Prime Magus of the Wyldlands", prompt)
                self.assertIn("emerging virtual world", prompt)
                self.assertIn("unfinished", prompt)
                self.assertIn("Apprentice", prompt)

    def test_legacy_archivist_title_no_longer_overrides_prime_magus(self):
        self.assertNotIn("The Arcane Archivist of the Wyldlands", build_llm_prompt())
        self.assertNotIn("The Arcane Archivist of the Wyldlands", build_legacy_ollama_prompt())

    def test_portable_install_keeps_canonical_title(self):
        path = Path(__file__).parent / "config" / "templates" / "vaelor.portable.json"
        template = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(template["identity"]["title"], "Prime Magus of the Wyldlands")


if __name__ == "__main__":
    unittest.main()
