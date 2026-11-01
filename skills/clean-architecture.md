---
skill: clean-architecture
layer: domain
tags: [python, architecture, layers, ports, dependencies]
---

## Layer map

```text
domain/         pure Python, zero imports from outside
application/    use cases + ports (Protocol / ABC)
  ├─ ports/     repository, event bus, notification interfaces
  └─ use_cases/ one module per use case
interface/      adapters that call in (HTTP, CLI, gRPC, message consumers)
infrastructure/ adapters that call out (DB, S3, Stripe, email)
```

Dependency rule: arrows point inward. `infrastructure` → `application` → `domain`. `interface` → `application`. `domain` never imports from the outer layers.

## Domain layer

- Entities are plain classes with invariants enforced in `__init__` or factory methods.
- Value objects are frozen dataclasses / Pydantic models with equality by value.
- No ORM decorators, no HTTP decorators, no framework imports.
- Raise domain exceptions (`SubscriberAlreadyExists`) — never `HTTPException`.

## Application layer

- One use case = one class with `execute(request) -> response`.
- Dependencies are injected through the constructor as **port interfaces**.
- The use case orchestrates: load entity → apply business rule → persist → publish events.
- No knowledge of HTTP, SQL, JSON, or frameworks.

## Interface layer

- Converts external input (HTTP body, CLI args, message payload) into an
  application request, calls the use case, converts the response back out.
- Translates domain exceptions to protocol-level errors (HTTP status, exit code).
- Dependency injection wiring lives here (FastAPI `Depends`, `__main__`, etc.).

## Infrastructure layer

- Implements ports declared in `application/ports/`.
- Each adapter lives in its own module: `sqlalchemy_subscriber_repo.py`,
  `sendgrid_notifier.py`, `redis_event_bus.py`.
- Keep third-party SDKs isolated here — no other layer imports them.

## Cross-cutting rules

- Use case names: `VerbNounUseCase` (e.g., `SubscribeToNewsletterUseCase`).
- Port names: `NounRepository`, `NounNotifier`, `NounEventBus`.
- One module per use case. One class per use case. No god-classes.
