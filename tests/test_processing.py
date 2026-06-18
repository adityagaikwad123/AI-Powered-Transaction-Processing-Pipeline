from app.processing import process_csv_content


def test_processing_cleans_classifies_and_flags_anomalies():
    csv_content = """txn_id,date,merchant,amount,currency,status,category,account_id,notes
TXN1,04-09-2024,Swiggy,$100.00,usd,success,,ACC1,
TXN2,2024/02/05,Amazon,10.00,INR,failed,Shopping,ACC1,
TXN2,2024/02/05,Amazon,10.00,INR,failed,Shopping,ACC1,
TXN3,17-02-2024,Ola,1000.00,INR,SUCCESS,Transport,ACC1,SUSPICIOUS
"""

    output = process_csv_content(csv_content)

    assert output.raw_count == 4
    assert output.clean_count == 3
    swiggy = next(row for row in output.transactions if row.merchant == "Swiggy")
    assert swiggy.date.isoformat() == "2024-09-04"
    assert swiggy.currency == "USD"
    assert swiggy.status == "SUCCESS"
    assert swiggy.category == "Food"
    assert swiggy.is_anomaly is True
    assert "domestic-only" in swiggy.anomaly_reason
    assert output.summary["anomaly_count"] >= 1

