import json
from pathlib import Path
import unittest

from core.version import VAELOR_VERSION


ROOT = Path(__file__).resolve().parent


class ReleaseMetadataTests(unittest.TestCase):
    def test_json_metadata_uses_canonical_version(self):
        for relative, key in (
            ("config/vaelor.json", "version"),
            ("config/capabilities.json", "version"),
            ("config/roadmap.json", "current_version"),
            ("config/templates/vaelor.portable.json", "version"),
        ):
            data = json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))
            self.assertEqual(data[key], VAELOR_VERSION, relative)

    def test_installer_artifacts_use_canonical_version(self):
        for relative in (
            "installer/Build-AlphaPackage.ps1",
            "installer/Install-Vaelor-Alpha.ps1",
            "installer/Build-Vaelor-Exe.ps1",
            "installer/init_local_config.py",
            "installer/README.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8-sig")
            self.assertIn(VAELOR_VERSION, text, relative)

    def test_api_uses_canonical_version(self):
        import api.server as server
        self.assertEqual(server.app.version, VAELOR_VERSION)
        self.assertEqual(server.health()["version"], VAELOR_VERSION)


if __name__ == "__main__":
    unittest.main()
