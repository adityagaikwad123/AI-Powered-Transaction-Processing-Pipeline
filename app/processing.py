import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from statistics import median
from typing import Any

from app.llm import CATEGORIES, LLMClient

DOMESTIC_ONLY_MERCHANTS = {"swiggy", "ola", "irctc", "zomato", "jio recharge"}


@dataclass
class CleanedRow:
    row_id: str
    txn_id: str | None
    date: date | None
    merchant: str
    amount: Decimal
    currency: str
    status: str
    category: str
    account_id: str | None
    notes: str | None
    originally_missing_category: bool
    is_anomaly: bool = False
    anomaly_reason: str | None = None
    llm_category: str | None = None
    llm_raw_response: dict[str, Any] | None = None
    llm_failed: bool = False

    def as_transaction_dict(self) -> dict[str, Any]:
        return {
            "txn_id": self.txn_id,
            "date": self.date,
            "merchant": self.merchant,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "category": self.category,
            "account_id": self.account_id,
            "notes": self.notes,
            "is_anomaly": self.is_anomaly,
            "anomaly_reason": self.anomaly_reason,
            "llm_category": self.llm_category,
            "llm_raw_response": self.llm_raw_response,
            "llm_failed": self.llm_failed,
        }

    def as_llm_input(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "merchant": self.merchant,
            "amount": str(self.amount),
            "currency": self.currency,
            "status": self.status,
            "notes": self.notes or "",
        }

    def as_summary_input(self) -> dict[str, Any]:
        return {
            "merchant": self.merchant,
            "amount": str(self.amount),
            "currency": self.currency,
            "category": self.category,
            "is_anomaly": self.is_anomaly,
        }


@dataclass
class PipelineOutput:
    raw_count: int
    clean_count: int
    transactions: list[CleanedRow]
    summary: dict[str, Any]
    spend_by_category: dict[str, dict[str, float]] = field(default_factory=dict)


def process_csv_content(csv_content: str) -> PipelineOutput:
    rows = list(csv.DictReader(StringIO(csv_content)))
    cleaned_rows = _clean_rows(rows)
    _detect_anomalies(cleaned_rows)
    _classify_missing_categories(cleaned_rows)
    spend_by_category = _spend_by_category(cleaned_rows)
    anomaly_count = sum(1 for row in cleaned_rows if row.is_anomaly)
    summary = LLMClient().summarize([row.as_summary_input() for row in cleaned_rows], anomaly_count)
    summary["spend_by_category"] = spend_by_category
    return PipelineOutput(
        raw_count=len(rows),
        clean_count=len(cleaned_rows),
        transactions=cleaned_rows,
        summary=summary,
        spend_by_category=spend_by_category,
    )


def _clean_rows(rows: list[dict[str, str]]) -> list[CleanedRow]:
    cleaned = []
    seen = set()
    for index, row in enumerate(rows):
        normalised_tuple = tuple((key, (value or "").strip()) for key, value in sorted(row.items()))
        if normalised_tuple in seen:
            continue
        seen.add(normalised_tuple)

        merchant = (row.get("merchant") or "Unknown").strip()
        category_raw = (row.get("category") or "").strip()
        missing_category = not category_raw
        category = category_raw or "Uncategorised"

        cleaned.append(
            CleanedRow(
                row_id=str(index),
                txn_id=_blank_to_none(row.get("txn_id")),
                date=_parse_date(row.get("date")),
                merchant=merchant,
                amount=_parse_amount(row.get("amount")),
                currency=(row.get("currency") or "INR").strip().upper(),
                status=(row.get("status") or "PENDING").strip().upper(),
                category=category,
                account_id=_blank_to_none(row.get("account_id")),
                notes=_blank_to_none(row.get("notes")),
                originally_missing_category=missing_category,
            )
        )
    return cleaned


def _classify_missing_categories(rows: list[CleanedRow], batch_size: int = 25) -> None:
    llm_rows = [row for row in rows if row.originally_missing_category]
    client = LLMClient()
    for start in range(0, len(llm_rows), batch_size):
        batch = llm_rows[start : start + batch_size]
        response = client.classify_categories([row.as_llm_input() for row in batch])
        failed = bool(response.get("llm_failed"))
        classifications = {
            item.get("row_id"): item.get("category")
            for item in response.get("classifications", [])
            if item.get("row_id")
        }
        for row in batch:
            row.llm_raw_response = response
            if failed:
                row.llm_failed = True
                continue
            category = classifications.get(row.row_id, "Other")
            if category not in CATEGORIES:
                category = "Other"
            row.llm_category = category
            row.category = category


def _detect_anomalies(rows: list[CleanedRow]) -> None:
    by_account: dict[str, list[Decimal]] = defaultdict(list)
    for row in rows:
        if row.account_id:
            by_account[row.account_id].append(row.amount)

    medians = {
        account_id: Decimal(str(median(amounts)))
        for account_id, amounts in by_account.items()
        if amounts
    }

    for row in rows:
        reasons = []
        account_median = medians.get(row.account_id or "")
        if account_median and account_median > 0 and row.amount > account_median * 3:
            reasons.append(f"amount exceeds 3x account median ({account_median})")
        if row.currency == "USD" and row.merchant.strip().lower() in DOMESTIC_ONLY_MERCHANTS:
            reasons.append("USD used with domestic-only merchant")
        if row.notes and "suspicious" in row.notes.lower():
            reasons.append("notes mention suspicious activity")
        if reasons:
            row.is_anomaly = True
            row.anomaly_reason = "; ".join(reasons)


def _spend_by_category(rows: list[CleanedRow]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        totals[row.category][row.currency] += row.amount
    return {
        category: {currency: float(amount) for currency, amount in currency_totals.items()}
        for category, currency_totals in totals.items()
    }


def _parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    stripped = value.strip()
    for fmt in ("%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(stripped, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    cleaned = value.strip().replace("$", "").replace(",", "")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
