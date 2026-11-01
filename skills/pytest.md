---
skill: pytest
layer: application
tags: [python, pytest, testing, fixtures, assertions]
---

## Test layout

```text
tests/
  domain/        pure unit tests, no fixtures, no mocks
  application/   use-case tests with fake ports
  interface/     HTTP tests with FastAPI TestClient
  infrastructure/integration tests with real DB (docker)
```

Rules:
- Mirror `src/` under `tests/`. One test module per source module.
- Domain tests use zero fixtures and zero mocks.
- Application tests use fakes that implement the port protocol.

## Fakes over mocks

```python
class FakeSubscriberRepo(SubscriberRepository):
    def __init__(self) -> None:
        self._store: dict[UUID, Subscriber] = {}

    async def save(self, subscriber: Subscriber) -> None:
        self._store[subscriber.id] = subscriber

    async def find(self, subscriber_id: UUID) -> Subscriber | None:
        return self._store.get(subscriber_id)
```

Rules:
- Prefer fakes over `unittest.mock` for repository / notifier ports.
- Mocks hide state; fakes make it inspectable.
- Use `mock.patch` only for pure functions or external SDKs with no fake available.

## Assertions

```python
async def test_subscribe_creates_subscriber() -> None:
    repo = FakeSubscriberRepo()
    use_case = SubscribeToNewsletterUseCase(repo)

    response = await use_case.execute(SubscribeRequest(email="a@b.com", source="web"))

    assert response.subscriber_id is not None
    stored = await repo.find(response.subscriber_id)
    assert stored is not None and stored.email == "a@b.com"
```

Rules:
- Assert the visible behavior, not internal calls.
- Use `pytest.raises(SubscriberAlreadyExists)` for error paths.
- Parameterize with `@pytest.mark.parametrize` — avoid looping manually.

## Running

- `pytest -q` for CI; `pytest -x -v` for debugging.
- Mark slow tests: `@pytest.mark.slow`; exclude with `-m "not slow"` in fast loops.
