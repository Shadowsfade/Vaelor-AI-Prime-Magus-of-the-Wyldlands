from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from desktop import vaelor_app


class DesktopRuntimeTests(unittest.TestCase):
    def test_frozen_server_normalizes_localhost_alias(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(vaelor_app.sys, "frozen", True, create=True), patch.object(vaelor_app, "port_open", return_value=False), patch.object(vaelor_app.subprocess, "Popen") as spawn:
                vaelor_app.start_server(Path(root), "localhost", 9876)
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")

    def test_frozen_root_is_bundled_data_root(self):
        with patch.object(vaelor_app.sys, "frozen", True, create=True), patch.object(vaelor_app.sys, "_MEIPASS", str(Path("bundled").resolve()), create=True):
            self.assertEqual(vaelor_app.app_root(), Path("bundled").resolve())

    def test_server_mode_does_not_open_desktop_or_spawn_python(self):
        import os
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as root:
            try:
                with patch.object(vaelor_app, "app_root", return_value=Path(root)), patch("installer.init_local_config.init_local_config"), patch("uvicorn.run") as run, patch.object(vaelor_app, "start_server", side_effect=AssertionError("no nested process")):
                    self.assertEqual(vaelor_app.main(["--server", "--port", "9876"]), 0)
                run.assert_called_once_with("api.server:app", host="127.0.0.1", port=9876, log_config=None, access_log=False)
            finally:
                os.chdir(previous)

    def test_server_cannot_bind_public_interface(self):
        with self.assertRaises(SystemExit):
            vaelor_app.main(["--server", "--host", "0.0.0.0"])
