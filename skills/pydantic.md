---
skill: pydantic
layer: application
tags: [python, pydantic, validation, dto, schema]
---

## Strict request/response models (Pydantic v2)

```python
from pydantic import BaseModel, EmailStr, ConfigDict, Field

class SubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    source: str = Field(min_length=1, max_length=64)
```

Rules:
- Always set `extra="forbid"` on inbound DTOs — reject unknown fields early.
- Use `EmailStr`, `HttpUrl`, `UUID`, `IPvAnyAddress`, etc. for typed validation.
- **Important**: `EmailStr` requires `email-validator` (`uv add 'pydantic[email]'`). If the project doesn't have it, use `str` with a custom validator instead.
- Keep `str_strip_whitespace=True` globally; never accept whitespace-only strings.
- Mark optional fields with `Field(default=...)`; never use `None` as implicit default.

## Response shape

```python
class SubscribeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subscriber_id: UUID
    status: str
    created_at: datetime
```

Rules:
- Response models use `from_attributes=True` so domain entities convert via `model_validate(entity)`.
- Never expose ORM internals — response models are DTOs.
- Use `model_dump(mode="json")` before serialization to guarantee JSON-safe values.

## Validation pitfalls

- Use `field_validator("name")` for custom rules — not `validator(...)` (deprecated).
- Use `model_validator(mode="after")` for cross-field rules.
- Use `TypeAdapter` to validate raw dicts when the schema is dynamic.
