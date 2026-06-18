from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db, init_db
from app.models import Job, JobSummary, Transaction
from app.schemas import JobListItem, JobResultsResponse, JobStatusResponse, UploadResponse
from app.worker import process_transactions

app = FastAPI(title="Transaction Processing Pipeline", version="1.0.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs/upload", response_model=UploadResponse, status_code=202)
async def upload_job(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV uploads are supported")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded CSV is empty")

    try:
        csv_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc

    job = Job(filename=file.filename, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    process_transactions.delay(str(job.id), csv_content)
    return UploadResponse(job_id=job.id, status=job.status)


@app.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: UUID, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = db.scalar(select(Job).options(selectinload(Job.summary)).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    summary = None
    if job.summary:
        summary = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "top_merchants": job.summary.top_merchants,
            "anomaly_count": job.summary.anomaly_count,
            "risk_level": job.summary.risk_level,
        }
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary,
    )


@app.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: UUID, db: Session = Depends(get_db)) -> JobResultsResponse:
    job = db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    transactions = list(
        db.scalars(select(Transaction).where(Transaction.job_id == job_id).order_by(Transaction.date, Transaction.id))
    )
    summary = db.scalar(select(JobSummary).where(JobSummary.job_id == job_id))
    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        cleaned_transactions=transactions,
        flagged_anomalies=[tx for tx in transactions if tx.is_anomaly],
        per_category_spend=summary.spend_by_category if summary else {},
        llm_summary=summary.raw_summary if summary else None,
    )


@app.get("/jobs", response_model=list[JobListItem])
def list_jobs(
    status: str | None = Query(default=None, pattern="^(pending|processing|completed|failed)$"),
    db: Session = Depends(get_db),
) -> list[Job]:
    statement = select(Job).order_by(Job.created_at.desc())
    if status:
        statement = statement.where(Job.status == status)
    return list(db.scalars(statement))

