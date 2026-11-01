---
skill: celery
layer: infrastructure
tags: [python, celery, async, queue, task]
---

## Task definition

```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(
    bind=True,
    acks_late=True,
    autoretry_for=(TransientError,),
    retry_backoff=True,
    max_retries=5,
)
def send_newsletter_email(self, subscriber_id: str) -> None:
    logger.info("sending email to %s", subscriber_id)
```

Rules:
- Always use `@shared_task(bind=True)` so `self` is available for retries.
- Set `acks_late=True` for any task touching external systems.
- Declare `autoretry_for` and `retry_backoff` — never rely on manual `self.retry` alone.
- Pass serializable arguments only: `str`, `int`, `UUID` (as `str`), dicts.

## Idempotency

- Every task must be safe to run twice. Use a unique key (e.g., `idempotency_key`)
  and check before mutating.
- External calls should use idempotency tokens when the third-party API supports them.
- Never depend on timing or order; use explicit dependencies via chains/chords.

## Error handling

- Distinguish transient errors (network, rate limit) from permanent errors
  (invalid input, missing entity). Only transient errors should trigger retries.
- Log structured context (`subscriber_id`, `attempt`) before raising.
- Dead-letter: if `max_retries` is exceeded, emit to a DLQ topic or mark the entity
  as `failed` so operators can inspect.
