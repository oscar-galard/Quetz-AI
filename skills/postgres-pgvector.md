---
skill: postgres-pgvector
layer: infrastructure
tags: [python, postgresql, sql, pgvector, sqlalchemy, alembic, migration]
---

## SQLAlchemy model

```python
from sqlalchemy import Column, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from pgvector.sqlalchemy import Vector
from app.db.base import Base

class SubscriberEmbedding(Base):
    __tablename__ = "subscriber_embeddings"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    subscriber_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    embedding = Column(Vector(1536), nullable=False)
    source = Column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_subscriber_embeddings_vec", "embedding",
              postgresql_using="hnsw", postgresql_with={"m": 16, "ef_construction": 64}),
    )
```

Rules:
- Use `pgvector.sqlalchemy.Vector(dim)` — never raw byte arrays.
- Add an `hnsw` or `ivfflat` index; `hnsw` is better for write-heavy workloads.
- Always scope embeddings by a `source` column for multi-tenant isolation.

## Nearest-neighbor queries

```python
from sqlalchemy import func, select

def nearest(session, vector, *, k: int = 10) -> list[SubscriberEmbedding]:
    return session.execute(
        select(SubscriberEmbedding)
        .order_by(SubscriberEmbedding.embedding.cosine_distance(vector))
        .limit(k)
    ).scalars().all()
```

Rules:
- Use `cosine_distance` for normalized embeddings, `l2_distance` for raw vectors.
- Always `LIMIT`; never scan the full table.
- Prefetch `source` filters before the ANN search when possible.

## Migrations

- New tables: `alembic revision --autogenerate -m "add subscribers"`.
- Enable `pgvector` extension in a dedicated migration:
  `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`.
- Never drop/recreate tables with embeddings in a single revision — use `op.add_column`.
