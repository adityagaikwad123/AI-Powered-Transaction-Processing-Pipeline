# Architecture

![Architecture diagram](architecture.png)

Editable Draw.io source: [`architecture.drawio`](architecture.drawio)

## Actual Runtime Flow

```mermaid
flowchart LR
    client[Client / curl / Swagger UI]
    api[FastAPI API]
    postgres[(PostgreSQL)]
    redis[(Redis queue / broker)]
    worker[Celery worker]
    pipeline[Clean rows + detect anomalies]
    llm[LLM client]
    fallback[Fallback classifier and summary]
    gemini[Gemini API optional]

    client -->|POST /jobs/upload CSV| api
    api -->|create pending job| postgres
    api -->|enqueue job_id + CSV content| redis
    redis -->|deliver task| worker
    worker -->|mark processing| postgres
    worker --> pipeline
    pipeline -->|missing categories + summary prompt| llm
    llm -->|default in docker-compose| fallback
    llm -.->|if LLM_PROVIDER=gemini| gemini
    worker -->|store transactions + summary| postgres
    client -->|GET /jobs, /status, /results| api
    api -->|read persisted state| postgres
```

## Request Lifecycle

1. `POST /jobs/upload` validates the CSV, creates a pending job in PostgreSQL, and enqueues `process_transactions(job_id, csv_content)` in Redis.
2. Celery consumes the Redis task, marks the job processing, cleans rows, detects anomalies, classifies missing categories, and generates a narrative summary.
3. The LLM client uses the deterministic fallback by default because `docker-compose.yml` sets `LLM_PROVIDER=fallback`. Gemini is supported when `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` are supplied.
4. The worker stores cleaned transactions and the summary in PostgreSQL.
5. `GET /jobs`, `GET /jobs/{job_id}/status`, and `GET /jobs/{job_id}/results` read persisted state from PostgreSQL.

