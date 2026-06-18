import json
import time
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from app.config import settings

CATEGORIES = [
    "Food",
    "Shopping",
    "Travel",
    "Transport",
    "Utilities",
    "Cash Withdrawal",
    "Entertainment",
    "Other",
]


class LLMClient:
    def classify_categories(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = {
            "task": "Classify transactions into one allowed category.",
            "allowed_categories": CATEGORIES,
            "transactions": rows,
            "output_format": {"classifications": [{"row_id": "string", "category": "string"}]},
        }
        return self._call_with_retry("classification", prompt, lambda: self._fallback_classify(rows))

    def summarize(self, transactions: list[dict[str, Any]], anomaly_count: int) -> dict[str, Any]:
        prompt = {
            "task": "Create a JSON financial transaction summary.",
            "transactions": transactions,
            "anomaly_count": anomaly_count,
            "output_format": {
                "total_spend_by_currency": {"INR": "number", "USD": "number"},
                "top_3_merchants": [{"merchant": "string", "total": "number"}],
                "anomaly_count": "number",
                "narrative": "2-3 sentences",
                "risk_level": "low|medium|high",
            },
        }
        return self._call_with_retry("summary", prompt, lambda: self._fallback_summary(transactions, anomaly_count))

    def _call_with_retry(self, kind: str, prompt: dict[str, Any], fallback):
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if settings.llm_provider == "gemini":
                    return self._call_gemini(prompt)
                if settings.llm_provider == "ollama":
                    return self._call_ollama(prompt)
                return fallback()
            except Exception as exc:  # External providers can fail in many small ways.
                last_error = exc
                time.sleep(2**attempt)
        if kind == "classification":
            return {"llm_failed": True, "error": str(last_error), "classifications": []}
        summary = fallback()
        summary["llm_failed"] = True
        summary["error"] = str(last_error)
        return summary

    def _call_gemini(self, prompt: dict[str, Any]) -> dict[str, Any]:
        import httpx

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={settings.gemini_api_key}"
        )
        payload = {"contents": [{"parts": [{"text": json.dumps(prompt)}]}]}
        with httpx.Client(timeout=30) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_text(text)

    def _call_ollama(self, prompt: dict[str, Any]) -> dict[str, Any]:
        import httpx

        payload = {
            "model": settings.ollama_model,
            "prompt": json.dumps(prompt),
            "format": "json",
            "stream": False,
        }
        with httpx.Client(timeout=60) as client:
            response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
            response.raise_for_status()
        return _parse_json_text(response.json()["response"])

    def _fallback_classify(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        classifications = []
        for row in rows:
            merchant = row.get("merchant", "").lower()
            notes = row.get("notes", "").lower()
            category = "Other"
            if any(word in merchant for word in ["swiggy", "zomato", "restaurant", "cafe"]):
                category = "Food"
            elif any(word in merchant for word in ["amazon", "flipkart", "myntra"]):
                category = "Shopping"
            elif any(word in merchant for word in ["irctc", "indigo", "air", "hotel"]):
                category = "Travel"
            elif any(word in merchant for word in ["ola", "uber", "metro"]):
                category = "Transport"
            elif any(word in merchant for word in ["jio", "electricity", "gas", "water"]):
                category = "Utilities"
            elif "atm" in merchant or "cash" in notes:
                category = "Cash Withdrawal"
            elif any(word in merchant for word in ["netflix", "bookmyshow", "spotify"]):
                category = "Entertainment"
            classifications.append({"row_id": row["row_id"], "category": category})
        return {"provider": "fallback", "classifications": classifications}

    def _fallback_summary(self, transactions: list[dict[str, Any]], anomaly_count: int) -> dict[str, Any]:
        totals = defaultdict(Decimal)
        merchant_totals = Counter()
        for tx in transactions:
            amount = Decimal(str(tx["amount"]))
            totals[tx["currency"]] += amount
            merchant_totals[tx["merchant"]] += float(amount)
        top_merchants = [
            {"merchant": merchant, "total": round(total, 2)}
            for merchant, total in merchant_totals.most_common(3)
        ]
        risk_level = "high" if anomaly_count >= 5 else "medium" if anomaly_count >= 2 else "low"
        narrative = (
            f"Processed {len(transactions)} cleaned transactions across {len(merchant_totals)} merchants. "
            f"The largest spending concentration is with {top_merchants[0]['merchant'] if top_merchants else 'no merchant'}, "
            f"and {anomaly_count} transactions were flagged for review."
        )
        return {
            "provider": "fallback",
            "total_spend_by_currency": {currency: float(amount) for currency, amount in totals.items()},
            "top_3_merchants": top_merchants,
            "anomaly_count": anomaly_count,
            "narrative": narrative,
            "risk_level": risk_level,
        }


def _parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return json.loads(cleaned)
