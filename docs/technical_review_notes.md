# 3-Minute Technical Review Notes

## System Design and Data Flow

This project separates synchronous request handling from slow CSV and LLM work. FastAPI owns upload validation and polling APIs. PostgreSQL persists jobs, transactions, and summaries. Redis is the queue broker. Celery workers run the cleaning, anomaly detection, LLM classification, and narrative summary pipeline.

## Why These Choices

FastAPI keeps the API small and easy to inspect. Celery plus Redis is a common backend queue pairing and satisfies the asynchronous processing requirement. PostgreSQL stores structured results and JSON summary fields cleanly. The LLM client is provider-pluggable and defaults to a deterministic no-cost fallback for reliable local review.

## Bottlenecks at 100x

Uploads are currently passed through Redis as task payloads, which is fine for this assignment but not ideal for large files. API and worker database pools would need tuning. LLM calls would hit provider latency and rate limits. Workers could become CPU or I/O bound depending on CSV size and provider response time.

## Next Production Iteration

Store uploaded files in object storage and pass file references through the queue. Add PgBouncer and explicit SQLAlchemy pool sizing. Split queues for CSV parsing and LLM calls. Add provider rate limiting, caching, idempotency keys, observability, dead-letter queues, and migration tooling such as Alembic.

