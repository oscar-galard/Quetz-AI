import tempfile
import unittest
from pathlib import Path

from quetz.domain.task_spec import TaskSpec
from quetz.infrastructure.skills.index import FileSkillIndex


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_FASTAPI_SKILL = """---
skill: fastapi
layer: interface
tags: [python, fastapi, http, api]
---

## Route handler pattern

FastAPI routes delegate to use cases.

```python
@router.post("/", response_model=Resp)
async def endpoint(payload: Req, uc: UC = Depends()):
    return await uc.execute(payload)
```

## Error handling

Map domain errors to HTTP at the interface layer.
"""

_PYDANTIC_SKILL = """---
skill: pydantic
layer: application
tags: [python, pydantic, validation, dto]
---

## Strict request models

```python
class SubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
```

## Response models

Use `from_attributes=True` for ORM conversion.
"""

_CLEAN_ARCH_SKILL = """---
skill: clean-architecture
layer: domain
tags: [python, architecture, layers, ports]
---

## Layer map

domain -> application -> interface -> infrastructure.

## Use cases

One class per use case. Inject ports via constructor.
"""


class TestFileSkillIndex(unittest.TestCase):
    def test_build_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "skills/fastapi.md", _FASTAPI_SKILL)
            _write(root, "skills/pydantic.md", _PYDANTIC_SKILL)
            _write(root, "skills/clean-architecture.md", _CLEAN_ARCH_SKILL)

            index = FileSkillIndex(tmp)
            count = index.build()
            self.assertEqual(count, 6)

            task = TaskSpec(
                id="T1",
                title="Add newsletter route",
                goal="Create a FastAPI route that accepts a Pydantic request",
                files=("interface/http/newsletter.py",),
                layer="interface",
            )
            sections = index.retrieve(
                task,
                stack_tags={"python", "fastapi", "pydantic", "http"},
                language="python",
                limit_chars=2000,
            )
            self.assertTrue(sections)
            titles = {s.title for s in sections}
            self.assertIn("Route handler pattern", titles)
            self.assertIn("Strict request models", titles)

    def test_layer_boost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "skills/fastapi.md", _FASTAPI_SKILL)
            _write(root, "skills/clean-architecture.md", _CLEAN_ARCH_SKILL)

            index = FileSkillIndex(tmp)
            index.build()

            task = TaskSpec(
                id="T1",
                title="Define domain entity",
                goal="Define Subscriber entity in domain layer",
                files=("domain/subscriber.py",),
                layer="domain",
            )
            sections = index.retrieve(
                task,
                stack_tags={"python", "architecture"},
                language="python",
                limit_chars=2000,
            )
            self.assertTrue(sections)
            top = sections[0]
            self.assertEqual(top.source, str(root / "skills/clean-architecture.md"))

    def test_no_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = FileSkillIndex(tmp)
            self.assertEqual(index.build(), 0)
            task = TaskSpec(id="T1", title="t", goal="g", files=())
            self.assertEqual(index.retrieve(task, stack_tags=(), language="", limit_chars=100), [])

    def test_budget_limits_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "skills/fastapi.md", _FASTAPI_SKILL)
            _write(root, "skills/pydantic.md", _PYDANTIC_SKILL)
            _write(root, "skills/clean-architecture.md", _CLEAN_ARCH_SKILL)

            index = FileSkillIndex(tmp)
            index.build()
            task = TaskSpec(
                id="T1",
                title="Add route",
                goal="Add FastAPI route",
                files=("interface/http/newsletter.py",),
            )
            sections = index.retrieve(
                task,
                stack_tags={"python", "fastapi"},
                language="python",
                limit_chars=50,
            )
            self.assertTrue(len(sections) <= 2)


if __name__ == "__main__":
    unittest.main()
