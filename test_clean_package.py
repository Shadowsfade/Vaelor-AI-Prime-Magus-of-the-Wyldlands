from pathlib import Path
import importlib
import tempfile
import unittest
import zipfile

from installer.verify_clean_package import inspect_archive


ROOT = Path(__file__).resolve().parent


class CleanPackageTests(unittest.TestCase):
    def test_optional_runtime_modules_import_from_clean_sources(self):
        self.assertIsNotNone(importlib.import_module("core.tools.unreal_tools"))

    def test_builder_explicitly_removes_remote_api_credentials(self):
        builder = (ROOT / "installer" / "Build-AlphaPackage.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('Join-Path $cfg "api_access.json"', builder)
        self.assertIn("Remove-Item", builder)

    def test_inspector_rejects_packaged_remote_api_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive_path = folder / "Vaelor-Alpha-test.zip"
            required = {
                f"Vaelor-Alpha-test/{name}": b"safe"
                for name in (
                    "INSTALL.bat", "ALPHA_README.txt", "requirements.txt",
                    "api/server.py", "core/runtime.py", "web/index.html",
                    "installer/Install-Vaelor-Alpha.ps1",
                    "installer/init_local_config.py",
                )
            }
            required["Vaelor-Alpha-test/config/api_access.json"] = b'{"token":"secret"}'
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, payload in required.items():
                    archive.writestr(name, payload)
            import hashlib
            archive_path.with_suffix(".zip.sha256").write_text(
                hashlib.sha256(archive_path.read_bytes()).hexdigest(), encoding="ascii"
            )
            with self.assertRaisesRegex(RuntimeError, "private/build state"):
                inspect_archive(archive_path, ROOT)

    def test_runtime_sources_have_no_legacy_builder_identity(self):
        legacy_user = "Sho" + "vel"
        legacy_server = "S:\\" + "VeilorServer"
        for relative in (
            "launcher.ps1", "spellbook/aider_spell.py",
            "core/tools/approval.py", "core/tools/shell_exec.py",
            "core/tools/unreal_tools.py", "installer/init_local_config.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8-sig")
            self.assertNotIn(legacy_user, text, relative)
            self.assertNotIn(legacy_server, text, relative)


if __name__ == "__main__":
    unittest.main()
