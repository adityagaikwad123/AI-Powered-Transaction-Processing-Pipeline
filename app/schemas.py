from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    job_id: UUID
    status: str


class JobListItem(BaseModel):
    id: UUID
    status: str
    filename: str
    row_count_raw: int
    row_count_clean: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str
    row_count_raw: int
    row_count_clean: int
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None
    summary: dict | None = None


class TransactionOut(BaseModel):
    txn_id: str | None
    date: date | None
    merchant: str
    amount: Decimal
    currency: str
    status: str
    category: str
    account_id: str | None
    notes: str | None
    is_anomaly: bool
    anomaly_reason: str | None
    llm_category: str | None
    llm_raw_response: dict | None
    llm_failed: bool

    model_config = ConfigDict(from_attributes=True)


class JobResultsResponse(BaseModel):
    job_id: UUID
    status: str
    cleaned_transactions: list[TransactionOut]
    flagged_anomalies: list[TransactionOut]
    per_category_spend: dict
    llm_summary: dict | None

