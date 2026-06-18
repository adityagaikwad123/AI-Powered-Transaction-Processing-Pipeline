from datetime import datetime, timezone
from uuid import UUID

from celery import Celery
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Job, JobSummary, Transaction
from app.processing import process_csv_content

celery_app = Celery("transaction_pipeline", broker=settings.redis_url, backend=settings.redis_url)


@celery_app.task(name="process_transactions")
def process_transactions(job_id: str, csv_content: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        _process(db, UUID(job_id), csv_content)
    finally:
        db.close()


def _process(db: Session, job_id: UUID, csv_content: str) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    try:
        job.status = "processing"
        db.commit()

        output = process_csv_content(csv_content)
        job.row_count_raw = output.raw_count
        job.row_count_clean = output.clean_count

        for row in output.transactions:
            db.add(Transaction(job_id=job.id, **row.as_transaction_dict()))

        summary = output.summary
        totals = summary.get("total_spend_by_currency", {})
        db.add(
            JobSummary(
                job_id=job.id,
                total_spend_inr=totals.get("INR", 0),
                total_spend_usd=totals.get("USD", 0),
                top_merchants=summary.get("top_3_merchants", []),
                anomaly_count=summary.get("anomaly_count", 0),
                narrative=summary.get("narrative", ""),
                risk_level=summary.get("risk_level", "low"),
                spend_by_category=output.spend_by_category,
                raw_summary=summary,
            )
        )
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

