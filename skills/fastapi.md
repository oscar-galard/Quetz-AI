---
skill: fastapi
layer: interface
tags: [python, fastapi, http, api, dependency-injection]
---

## Route handler pattern

```python
from fastapi import APIRouter, Depends, status

router = APIRouter(prefix="/newsletters", tags=["newsletters"])

@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SubscribeResponse,
)
async def subscribe(
    payload: SubscribeRequest,
    use_case: SubscribeToNewsletterUseCase = Depends(),
) -> SubscribeResponse:
    return await use_case.execute(payload)
```

Rules:
- One router per bounded context, mounted in `main.py` with `app.include_router(router)`.
- Handlers delegate to a use case — they contain zero business logic.
- Always declare `status_code` explicitly; never rely on FastAPI defaults.
- Use `response_model` to lock the response shape.

## Dependency injection

```python
from fastapi import Depends
from typing import Protocol

class SubscriberRepository(Protocol):
    async def save(self, subscriber: Subscriber) -> None: ...

def get_subscriber_repo() -> SubscriberRepository:
    from adapters.sqlalchemy import SqlSubscriberRepository
    return SqlSubscriberRepository(get_session())
```

Rules:
- Define ports as `Protocol` or `ABC` in `application/`. Implement in `infrastructure/`.
- Always inject dependencies via `Depends()` — never import concrete adapters from `interface/`.
- Use `Annotated[Repo, Depends(get_repo)]` for type-safe shorthand.
- Use `yield` for session-bound dependencies; commit on happy path, rollback on exception.

## Error handling

```python
from fastapi import HTTPException

class DomainError(Exception): pass
class NotFoundError(DomainError): pass
class DuplicateError(DomainError): pass

def map_errors(exc: DomainError) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(404, detail=str(exc))
    if isinstance(exc, DuplicateError):
        return HTTPException(409, detail=str(exc))
    return HTTPException(500, detail="internal error")
```

Rules:
- Convert domain exceptions to HTTP exceptions at the adapter boundary (`interface/`).
- Never raise `HTTPException` from `domain/` or `application/`.
- Use problem+json for error bodies when the API is public.
