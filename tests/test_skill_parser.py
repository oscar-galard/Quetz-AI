import tempfile
import unittest
from pathlib import Path

from quetz.infrastructure.skills.parser import parse_frontmatter, parse_skill_file


class TestSkillParser(unittest.TestCase):
    def test_parse_frontmatter(self):
        fm = parse_frontmatter(
            "skill: fastapi\nlayer: interface\ntags: [python, fastapi, http]"
        )
        self.assertEqual(fm.skill, "fastapi")
        self.assertEqual(fm.layer, "interface")
        self.assertIn("python", fm.tags)
        self.assertIn("fastapi", fm.tags)

    def test_parse_sections_with_section_meta(self):
        text = """---
skill: fastapi
layer: interface
tags: [python, fastapi]
---

# FastAPI skills

## Route handler pattern
Simple intro text.

## Dependency injection
> tags: python, dependency-injection
> layer: application

Override section tags.
"""
        sections = parse_skill_file("skills/fastapi.md", text)
        self.assertEqual(len(sections), 2)

        first, second = sections
        self.assertEqual(first.title, "Route handler pattern")
        self.assertEqual(first.tags, ("python", "fastapi"))
        self.assertEqual(first.layer, "interface")
        self.assertIn("Simple intro text", first.body)

        self.assertEqual(second.title, "Dependency injection")
        self.assertEqual(second.tags, ("python", "dependency-injection"))
        self.assertEqual(second.layer, "application")
        self.assertIn("Override section tags", second.body)

    def test_no_frontmatter(self):
        text = """## One
Body one.

### Two
Body two.
"""
        sections = parse_skill_file("plain.md", text)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].title, "One")
        self.assertEqual(sections[1].title, "Two")
        self.assertEqual(sections[0].tags, ())


if __name__ == "__main__":
    unittest.main()
