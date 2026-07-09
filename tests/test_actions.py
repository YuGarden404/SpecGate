import unittest

from specgate.actions import Action, ActionParseError, parse_action


class ActionParserTests(unittest.TestCase):
    def test_parse_valid_action(self):
        raw = '{"schema_version":"1","action":"write_file","args":{"path":"index.html","content":"<html></html>"},"reason":"create page"}'

        action = parse_action(raw)

        self.assertEqual(
            action,
            Action(
                schema_version="1",
                action="write_file",
                args={"path": "index.html", "content": "<html></html>"},
                reason="create page",
            ),
        )

    def test_rejects_markdown_wrapped_json(self):
        raw = '```json\n{"schema_version":"1","action":"finish","args":{}}\n```'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("strict JSON object", str(ctx.exception))

    def test_rejects_missing_required_field(self):
        raw = '{"schema_version":"1","args":{}}'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("missing field: action", str(ctx.exception))

    def test_rejects_non_object_args(self):
        raw = '{"schema_version":"1","action":"finish","args":[]}'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("args must be an object", str(ctx.exception))

    def test_rejects_unsupported_schema_version(self):
        raw = '{"schema_version":"2","action":"finish","args":{}}'

        with self.assertRaises(ActionParseError) as ctx:
            parse_action(raw)

        self.assertIn("unsupported schema_version", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
