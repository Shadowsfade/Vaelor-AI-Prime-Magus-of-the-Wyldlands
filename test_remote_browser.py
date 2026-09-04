from pathlib import Path
import unittest

from installer.start_remote_api import validate_host


HTML = (Path(__file__).resolve().parent / "web" / "index.html").read_text(
    encoding="utf-8-sig"
)


class RemoteBrowserTests(unittest.TestCase):
    def test_tome_exchanges_token_without_persisting_it_in_browser_storage(self):
        self.assertIn("fetch('/auth/status')", HTML)
        self.assertIn("fetch('/auth/token'", HTML)
        self.assertIn("'Authorization':'Bearer '+token", HTML)
        self.assertNotIn("localStorage.setItem('vaelor", HTML)
        self.assertNotIn("sessionStorage.setItem('vaelor", HTML)

    def test_boot_stops_when_remote_authentication_fails(self):
        self.assertIn("if(await ensureRemoteAuthentication())bootInstallerFlow()", HTML)
        self.assertIn("Remote authentication required", HTML)

    def test_remote_launcher_requires_a_valid_explicit_host(self):
        self.assertEqual(validate_host("100.64.0.2"), "100.64.0.2")
        self.assertEqual(validate_host("vaelor.tailnet.ts.net"), "vaelor.tailnet.ts.net")
        for invalid in ("", "bad host", ";rm"):
            with self.assertRaises(ValueError):
                validate_host(invalid)


if __name__ == "__main__":
    unittest.main()
