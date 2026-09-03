import unittest

from core.action_protocol import parse_structured_response


class ActionProtocolTests(unittest.TestCase):
    def test_parses_typed_arguments(self):
        parsed = parse_structured_response(
            '{"thought":"inspect","actions":[{"tool":"list_dir",'
            '"arguments":{"path":".","recursive":true,"depth":2}}],"final":null}'
        )
        self.assertIsNone(parsed.error)
        self.assertEqual(parsed.actions[0][0], "list_dir")
        self.assertIs(parsed.actions[0][1]["recursive"], True)
        self.assertEqual(parsed.actions[0][1]["depth"], 2)

    def test_parses_fenced_final(self):
        parsed = parse_structured_response(
            '```json\n{"thought":"done","actions":[],"final":'
            '{"status":"success","summary":"checks passed"}}\n```'
        )
        self.assertEqual(parsed.final_summary, "FINAL_SUMMARY: SUCCESS checks passed")

    def test_rejects_non_object_arguments(self):
        parsed = parse_structured_response(
            '{"actions":[{"tool":"list_dir","arguments":"path=."}],"final":null}'
        )
        self.assertIn("arguments must be an object", parsed.error)

    def test_rejects_invalid_tool_name(self):
        parsed = parse_structured_response(
            '{"actions":[{"tool":"shell; rm","arguments":{}}],"final":null}'
        )
        self.assertIn("valid tool name", parsed.error)

    def test_rejects_empty_decision(self):
        parsed = parse_structured_response('{"thought":"unsure","actions":[],"final":null}')
        self.assertIn("at least one action", parsed.error)

    def test_non_json_is_left_for_legacy_parser(self):
        parsed = parse_structured_response("ACTION: git_status")
        self.assertFalse(parsed.matched)


if __name__ == "__main__":
    unittest.main()
