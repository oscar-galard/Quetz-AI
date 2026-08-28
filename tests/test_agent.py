import unittest
from quetz.agent import parse_tool_call_from_text

class TestAgentFallbackParser(unittest.TestCase):
    def test_direct_json(self):
        content = '{"name": "write_file", "arguments": {"file_path": "test.txt", "content": "hello"}}'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})
        self.assertTrue(result[0]["id"].startswith("fallback_id_"))

    def test_markdown_code_block(self):
        content = '```json\n{"name": "write_file", "args": {"file_path": "test.txt", "content": "hello"}}\n```'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})

        content_plain = '```\n{"name": "write_file", "parameters": {"file_path": "test.txt", "content": "hello"}}\n```'
        result_plain = parse_tool_call_from_text(content_plain)
        self.assertIsNotNone(result_plain)
        self.assertEqual(result_plain[0]["args"], {"file_path": "test.txt", "content": "hello"})

    def test_xml_tags(self):
        content = '<tool_call>{"name": "write_file", "arguments": {"file_path": "test.txt", "content": "hello"}}</tool_call>'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "test.txt", "content": "hello"})

    def test_invalid_json_returns_none(self):
        self.assertIsNone(parse_tool_call_from_text("not a json string"))
        self.assertIsNone(parse_tool_call_from_text('{"name": "missing_closing_bracket"'))

    def test_sub_json_extraction(self):
        content = 'Here is the tool call you requested:\n\n{"name": "write_file", "arguments": {"file_path": "hello.txt", "content": "world"}}\n\nLet me know if you need anything else!'
        result = parse_tool_call_from_text(content)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["name"], "write_file")
        self.assertEqual(result[0]["args"], {"file_path": "hello.txt", "content": "world"})

if __name__ == "__main__":
    unittest.main()
