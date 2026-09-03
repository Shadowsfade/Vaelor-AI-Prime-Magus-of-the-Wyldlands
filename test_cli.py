import unittest

import vaelor
from core.version import VAELOR_VERSION


class CliTests(unittest.TestCase):
    def test_parser_supports_terminal_json_and_cwd(self):
        args = vaelor.build_parser().parse_args(["--terminal", "--json", "--cwd", "."])
        self.assertTrue(args.terminal)
        self.assertTrue(args.json)
        self.assertEqual(args.cwd, ".")

    def test_cli_uses_canonical_version(self):
        self.assertEqual(vaelor.VAELOR_VERSION, VAELOR_VERSION)


if __name__ == "__main__":
    unittest.main()
