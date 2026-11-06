"""Leakage-aware baseline for predicting whether an invoice will be paid late.

This module is intentionally independent of statutory and accounting decisions.
Only features known at the prediction timestamp may be used.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

FEATURES = ("invoice_amount_paise", "payment_terms_days", "buyer_prior_invoices",
            "buyer_prior_late_rate", "buyer_prior_avg_delay_days")


def load_rows(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"invoice_id", "issued_at", "paid_at", "due_at", *FEATURES}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"CSV must have rows and columns: {sorted(required)}")
    seen = set()
    for row in rows:
        if row["invoice_id"] in seen:
            raise ValueError("Duplicate invoice_id")
        seen.add(row["invoice_id"])
        issued = date.fromisoformat(row["issued_at"])
        due = date.fromisoformat(row["due_at"])
        paid = date.fromisoformat(row["paid_at"])
        if not issued <= due or paid < issued:
            raise ValueError("Invalid invoice chronology")
        for name in FEATURES:
            row[name] = float(row[name])
        if row["invoice_amount_paise"] < 0 or row["payment_terms_days"] < 0:
            raise ValueError("Negative amount or terms")
        if row["buyer_prior_invoices"] < 0 or not 0 <= row["buyer_prior_late_rate"] <= 1:
            raise ValueError("Invalid historical buyer feature")
        row["label"] = int(paid > due)
    return sorted(rows, key=lambda r: (r["issued_at"], r["invoice_id"]))


def evaluate(path: str | Path, output: str | Path, test_fraction: float = 0.25) -> dict:
    """Chronological holdout; train-only preprocessing; never use paid_at as feature."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    try:
        import numpy as np
        from sklearn.dummy import DummyClassifier
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
    except ImportError as exc:
        raise RuntimeError("Install requirements-ml.txt") from exc

    rows = load_rows(path)
    if len(rows) < 20:
        raise ValueError("At least 20 historical, fully settled invoices required")
    split = int(len(rows) * (1 - test_fraction))
    train, test = rows[:split], rows[split:]
    if train[-1]["issued_at"] == test[0]["issued_at"]:
        raise ValueError("Train/test boundary shares an issue date; choose a different split")
    x_train = np.asarray([[r[k] for k in FEATURES] for r in train])
    x_test = np.asarray([[r[k] for k in FEATURES] for r in test])
    y_train = np.asarray([r["label"] for r in train])
    y_test = np.asarray([r["label"] for r in test])
    if len(set(y_train)) < 2:
        model = make_pipeline(SimpleImputer(strategy="median"), DummyClassifier(strategy="prior"))
        model_name = "prior-only baseline (one training class)"
    else:
        model = make_pipeline(SimpleImputer(strategy="median"),
                              HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=8,
                                                             min_samples_leaf=10, random_state=42))
        model_name = "histogram gradient boosting"
    model.fit(x_train, y_train)
    classes = list(model[-1].classes_)
    probability = model.predict_proba(x_test)[:, classes.index(1)] if 1 in classes else np.zeros(len(test))
    prevalence = float(np.mean(y_train))
    baseline = np.full(len(test), prevalence)

    def metrics(scores):
        result = {"brier": float(brier_score_loss(y_test, scores))}
        result["average_precision"] = float(average_precision_score(y_test, scores)) if 1 in y_test else None
        result["roc_auc"] = float(roc_auc_score(y_test, scores)) if len(set(y_test)) == 2 else None
        return result

    report = {
        "model": model_name, "training_rows": len(train), "test_rows": len(test),
        "train_end": train[-1]["issued_at"], "test_start": test[0]["issued_at"],
        "features": list(FEATURES), "positive_label": "paid_after_due_date",
        "evaluation": metrics(probability), "prevalence_baseline": metrics(baseline),
        "limitations": [
            "Historical features must be computed using only data available at issue time.",
            "Only fully settled invoices are labeled; selection bias may affect results.",
            "This score is not a statutory finding, debt collection decision, or payment guarantee.",
            "Use genuinely historical data before claiming predictive performance."
        ],
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
