"""Run: python scripts/evaluate_payment_risk.py historical.csv report.json"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proofpay.payment_risk import evaluate

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/evaluate_payment_risk.py historical.csv report.json")
    print(json.dumps(evaluate(sys.argv[1], sys.argv[2]), indent=2))
