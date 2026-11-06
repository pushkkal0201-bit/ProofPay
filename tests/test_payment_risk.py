import csv
from datetime import date, timedelta

import pytest

from proofpay.payment_risk import load_rows, evaluate, FEATURES


def make_csv(tmp_path, count=40):
    path = tmp_path / "history.csv"
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["invoice_id", "issued_at", "due_at", "paid_at", *FEATURES])
        writer.writeheader()
        for i in range(count):
            issued = date(2025, 1, 1) + timedelta(days=i * 3)
            due = issued + timedelta(days=30)
            paid = due + timedelta(days=5 if i % 2 else -5)
            writer.writerow({"invoice_id": str(i), "issued_at": issued.isoformat(),
                             "due_at": due.isoformat(), "paid_at": paid.isoformat(),
                             "invoice_amount_paise": 10000 + i * 100,
                             "payment_terms_days": 30, "buyer_prior_invoices": i,
                             "buyer_prior_late_rate": 0.5, "buyer_prior_avg_delay_days": 0})
    return path


def test_labels_and_chronological_sort(tmp_path):
    rows = load_rows(make_csv(tmp_path))
    assert len(rows) == 40
    assert rows[0]["label"] == 0
    assert rows[1]["label"] == 1


def test_holdout_report(tmp_path):
    pytest.importorskip("sklearn")
    result = evaluate(make_csv(tmp_path), tmp_path / "report.json")
    assert result["training_rows"] == 30
    assert result["test_rows"] == 10
    assert result["train_end"] < result["test_start"]
    assert "brier" in result["evaluation"]


def test_rejects_small_sample(tmp_path):
    with pytest.raises(ValueError, match="At least 20"):
        evaluate(make_csv(tmp_path, 10), tmp_path / "report.json")
