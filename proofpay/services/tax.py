import re
from datetime import timedelta

from engine.packet import breakdown


class TaxComplianceService:
    @staticmethod
    def evaluate(case, matrix, net, ledger):
        gst_match = bool(
            re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", case.gstin)
            and case.gstin == case.master_gstin
            and case.buyer == case.master_name
        )
        row = case.statement_row
        statement = "Unavailable"
        if row:
            match = (
                row.invoice == case.invoice
                and row.issued == case.issued
                and row.recipient_gstin == case.gstin
                and row.supplier_gstin == case.supplier_gstin
                and row.principal == matrix["principal"]
                and row.gst == matrix["gst"]
            )
            if row.split:
                amounts = breakdown([(line, 1) for line in case.lines])
                match = (
                    match
                    and not amounts.pop("unallocated")
                    and amounts == row.split.model_dump()
                )
            statement = "Matched" if match else "Mismatch"
        pattern = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
        supplier = case.supplier_gstin
        origin = supplier[:2] if supplier and re.fullmatch(pattern, supplier) else None
        destination = case.place_of_supply
        regime = "undetermined"
        if origin and (destination or case.sez_supply):
            regime = (
                "inter_state"
                if case.sez_supply or origin != destination
                else "intra_state"
            )
        issues = []
        if supplier and not origin:
            issues.append("Supplier GSTIN format requires review.")
        for record in [
            *case.lines,
            *(e for e in case.ledger if e.approved and e.kind != "payment"),
        ]:
            split = record.split
            if not split:
                continue
            if (regime == "intra_state" and split.igst) or (
                regime == "inter_state" and (split.cgst or split.sgst)
            ):
                issues.append(
                    f"{record.id}: GST components conflict with place of supply."
                )
        deadline = case.issued + timedelta(days=180)
        at_deadline = (
            ledger.reconcile(case, through=deadline)[1]
            if case.as_of >= deadline
            else None
        )
        if case.reverse_charge or case.itc_availed is False:
            risk = "outside_payment_review"
        elif case.as_of < deadline:
            risk = "within_payment_window"
        elif case.as_of == deadline and net > 0:
            risk = "payment_window_closes_today"
        elif at_deadline is not None and at_deadline > 0:
            risk = (
                "unpaid_after_window"
                if net > 0
                else "subsequently_settled_review_reavailment"
            )
        else:
            risk = "no_unpaid_balance_at_deadline"
        observation = "observed" if row else "schedule_unknown"
        if not row and case.statement_expected_on:
            observation = (
                "awaiting_statement"
                if case.as_of < case.statement_expected_on
                else "statement_not_observed"
            )
        return {
            "master_match": gst_match,
            "statement": statement,
            "issues": issues,
            "regime": regime,
            "supplier_state": origin,
            "recipient_registration_state": case.gstin[:2] if gst_match else None,
            "place_of_supply": destination,
            "statement_window": observation,
            "expected_on": str(case.statement_expected_on)
            if case.statement_expected_on
            else None,
            "payment_deadline": str(deadline),
            "balance_at_deadline": at_deadline,
            "payment_status": risk,
            "itc_availed": case.itc_availed,
            "review": risk in {"payment_window_closes_today", "unpaid_after_window"},
        }
