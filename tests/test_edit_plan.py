import unittest

from quetz.domain.edit import EditOp, EditPlan, extract_json_object, parse_edit_plan
from quetz.domain.exceptions import EditError


class TestEditPlan(unittest.TestCase):
    def test_parses_fenced_json(self):
        raw = """Here you go:
```json
{"task_id":"T1","status":"done","summary":"ok","edits":[
  {"file":"a.py","op":"create","content":"x = 1\\n"}
]}
```
"""
        plan = parse_edit_plan(raw, "T1")
        self.assertFalse(plan.blocked)
        self.assertEqual(plan.edits[0].op, EditOp.CREATE)
        self.assertEqual(plan.edits[0].file, "a.py")

    def test_accepts_operation_aliases(self):
        data = extract_json_object(
            '{"status":"done","edits":[{"path":"a.py","op":"write","content":"x"}]}'
        )
        plan = EditPlan.from_dict(data, task_id="T1")
        self.assertEqual(plan.edits[0].op, EditOp.CREATE)

    def test_blocked_requires_reason(self):
        with self.assertRaises(EditError):
            EditPlan.from_dict({"status": "blocked", "edits": []}, task_id="T1")

    def test_done_requires_edits(self):
        with self.assertRaises(EditError):
            EditPlan.from_dict({"status": "done", "edits": []}, task_id="T1")

    def test_rejects_prose_only(self):
        with self.assertRaises(EditError):
            parse_edit_plan("I cannot do that.", "T1")

    def test_fixes_escaped_quotes_in_values(self):
        # Local models sometimes output \" inside string values
        raw = '{"project": "test", "tasks": [{"id": "T1", "conventions": \\"Do not use pip\\"", "goal": "x", "title": "y", "files": [], "acceptance": [{"command": "ok"}], "layer": "domain"}]}'
        data = extract_json_object(raw)
        self.assertIsNotNone(data)
        self.assertEqual(data["project"], "test")

    def test_fixes_trailing_commas(self):
        raw = '{"project": "test", "tasks": [],}'
        data = extract_json_object(raw)
        self.assertIsNotNone(data)
        self.assertEqual(data["project"], "test")


if __name__ == "__main__":
    unittest.main()
