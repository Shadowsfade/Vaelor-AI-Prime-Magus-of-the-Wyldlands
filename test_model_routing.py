import unittest
from unittest.mock import patch

import spellbook.llm_client as llm_client
from spellbook.llm_client import chat, resolve_route, select_available_model


class ModelRoutingTests(unittest.TestCase):
    def test_installed_configured_model_is_never_replaced(self):
        selected = select_available_model(
            "chosen:14b", ["chosen:14b", "other:3b"], "core_reasoning",
            {"vram_mb": 4096},
        )
        self.assertEqual(selected, "chosen:14b")

    def test_missing_model_uses_task_appropriate_installed_model_within_vram(self):
        models = ["embed-model:7b", "general:14b", "general:7b", "coder:7b"]
        selected = select_available_model(
            "missing", models, "code_forge", {"vram_mb": 6144}
        )
        self.assertEqual(selected, "coder:7b")

    def test_fast_route_prefers_smaller_installed_model(self):
        selected = select_available_model(
            "missing", ["general:7b", "general:3b"], "fast_thought",
            {"vram_mb": 6144},
        )
        self.assertEqual(selected, "general:3b")

    def test_hardware_probe_is_cached_across_route_selections(self):
        llm_client._HARDWARE_CACHE.update({"timestamp": 0.0, "value": None})
        with patch("core.hardware.scan_hardware", return_value={"vram_mb": 6144}) as scan:
            for _ in range(2):
                selected = select_available_model(
                    "missing", ["general:14b", "general:7b"], "core_reasoning"
                )
                self.assertEqual(selected, "general:7b")
        scan.assert_called_once_with()

    @patch("spellbook.llm_client.get_backend_settings", return_value={
        "provider": "auto", "ollama_url": "ollama", "lmstudio_url": "lm", "timeout": 10,
    })
    @patch("spellbook.llm_client.get_spell_model", return_value="missing:9b")
    @patch("spellbook.llm_client.probe_lmstudio", return_value={
        "ok": True, "models": ["lm-general:3b"], "url": "lm",
    })
    @patch("spellbook.llm_client.probe_ollama", return_value={
        "ok": True, "models": ["ollama-coder:7b"], "url": "ollama",
    })
    def test_route_selects_models_independently_for_primary_and_fallback(
        self, _ollama, _lmstudio, _configured, _settings
    ):
        route = resolve_route("code_forge", hw={"vram_mb": 6144})
        self.assertEqual(route["provider"], "ollama")
        self.assertEqual(route["model"], "ollama-coder:7b")
        self.assertEqual(route["fallback"], {"provider": "lmstudio", "model": "lm-general:3b"})

    @patch("spellbook.llm_client.get_backend_settings", return_value={
        "provider": "auto", "ollama_url": "ollama", "lmstudio_url": "lm", "timeout": 10,
    })
    @patch("spellbook.llm_client.probe_lmstudio", return_value={"ok": False, "models": [], "url": "lm"})
    @patch("spellbook.llm_client.probe_ollama", return_value={"ok": True, "models": ["local:3b"], "url": "ollama"})
    def test_explicit_model_override_is_preserved(self, _ollama, _lmstudio, _settings):
        route = resolve_route("core_reasoning", model="explicit:70b", hw={"vram_mb": 4096})
        self.assertEqual(route["model"], "explicit:70b")

    @patch("spellbook.llm_client.get_backend_settings", return_value={
        "provider": "auto", "ollama_url": "ollama", "lmstudio_url": "lm", "timeout": 10,
    })
    @patch("spellbook.llm_client.resolve_route", return_value={
        "provider": "ollama", "model": "primary:7b",
        "fallback": {"provider": "lmstudio", "model": "fallback:3b"},
        "configured_model": "missing",
    })
    @patch("spellbook.llm_client._ollama_chat", side_effect=ConnectionError("offline"))
    @patch("spellbook.llm_client._openai_chat", return_value="fallback worked")
    def test_chat_uses_provider_specific_fallback_model(
        self, openai_chat, _ollama_chat, _route, _settings
    ):
        self.assertEqual(chat("hello"), "fallback worked")
        self.assertEqual(openai_chat.call_args.kwargs["model"], "fallback:3b")


if __name__ == "__main__":
    unittest.main()
