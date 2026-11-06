# Payment delay risk: experimental baseline

This module evaluates whether invoice-issue-time information can predict settlement **after the contractual due date**. It does not replace ProofPay's accounting, statutory checks, dispute holds, or human review.

## Setup and run

```sh
python -m pip install -r requirements-ml.txt
python scripts/evaluate_payment_risk.py historical.csv artifacts/payment-risk-report.json
python -m pytest tests/test_payment_risk.py
```

The CSV needs `invoice_id,issued_at,due_at,paid_at,invoice_amount_paise,payment_terms_days,buyer_prior_invoices,buyer_prior_late_rate,buyer_prior_avg_delay_days`. Dates are ISO-8601 YYYY-MM-DD. The training data must contain **fully settled** historical invoices; do not train on open invoices with unknown outcomes. Buyer history features must be computed *as of the invoice issue date*, not from today's aggregate statistics.

## Evaluation design

Records are sorted by issue date, with the oldest 75% for training and newest 25% held out. The model uses only the five documented numeric features, a train-fitted median imputer, and constrained histogram gradient boosting. A training set with one outcome class falls back to a prevalence-only classifier. Results include Brier score (lower is better), average precision, ROC-AUC where defined, and a constant-prevalence baseline. Undefined metrics are reported as null rather than invented.

The held-out score is a research benchmark, **not** a production accuracy claim. The split is not purged for payment-label availability; a production backtest must ensure every training invoice had already settled by the prediction cutoff, and should use multiple rolling cutoffs. Add buyer-group analysis, calibration curves, confidence intervals, and out-of-time drift tests before deployment. No automatic collection or compliance action should be based on the output.

## Limitations and next steps

The repository's seven synthetic examples are far too few for training. Obtain a permissioned, de-identified historical invoice dataset with real payment outcomes. Do not publish buyer identities, account details, or financial records. Prioritize reproducible benchmarks and leakage checks before connecting inference to the dashboard.
