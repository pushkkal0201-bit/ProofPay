"""Exact decimal reconciliation; the public JSON contract expresses money in paise."""

from datetime import date
from decimal import Decimal

from proofpay.models import Case


class LedgerService:
    def reconcile(self, case: Case, through: date | None = None):
        principal = sum((Decimal(line.principal) for line in case.lines), Decimal(0))
        tax = sum((Decimal(line.gst) for line in case.lines), Decimal(0))
        totals = {
            "principal": principal,
            "gst": tax,
            "payment": Decimal(0),
            "credit": Decimal(0),
            "debit": Decimal(0),
            "interest": Decimal(0),
        }
        for entry in case.ledger:
            if entry.approved and (through is None or entry.date <= through):
                totals[entry.kind] += Decimal(entry.base) + Decimal(entry.gst)
        balance = (
            principal + tax + totals["debit"] - totals["payment"] - totals["credit"]
        )
        return {k: int(v) for k, v in totals.items()}, int(balance)
