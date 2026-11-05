"""Deterministic policy. Imported evidence is a human-reviewed attestation."""
import hashlib
import os
import re
from datetime import timedelta
from .models import Case


def rupees(paise):
    return f"INR {paise // 100:,}.{paise % 100:02d}"


def evidence_for(case, line):
    records = [e for e in case.evidence if e.verified and e.invoice == case.invoice
               and e.line == line.id and e.timestamp.date() <= case.as_of]
    conflicting_files = [e.id for e in records if e.attachment and hashlib.sha256(
        e.attachment.text.encode("utf-8")).hexdigest() != e.attachment.sha256]
    records = [e for e in records if e.id not in conflicting_files]
    accepted = {"POD", "BOL"} if line.kind == "goods" else {"acceptance"}
    # Require one complete receipt; two copies of a partial receipt cannot add up.
    receipt = next((e for e in records if e.kind in accepted and e.signer
                    and (e.quantity or 0) >= line.quantity), None)
    metric = next((e for e in records if e.kind == "telemetry" and e.covers_contract_period
                   and line.uptime_target_bps is not None and e.uptime_bps is not None
                   and e.uptime_bps >= line.uptime_target_bps), None)
    gaps = [f"Attachment checksum mismatch: {key}." for key in conflicting_files]
    if not receipt:
        gaps.append("Full-quantity signed receipt or acceptance required.")
    if line.uptime_target_bps is not None and not metric:
        gaps.append("Period-matched telemetry meeting the contract target required.")
    if line.uptime_target_bps is not None and any(
            e.kind == "telemetry" and e.covers_contract_period and e.uptime_bps is not None
            and e.uptime_bps < line.uptime_target_bps for e in records):
        gaps.append("A verified period report records uptime below the contract target.")
    if case.dispute == "performance":
        gaps.append("Reviewer must resolve the specific performance objection.")
    anchors = [e.model_dump(mode="json") for e in (receipt, metric) if e]
    return dict(line=line.id, description=line.description, clause=line.clause,
                quantity=line.quantity, target_bps=line.uptime_target_bps, anchors=anchors, gaps=gaps)


def analyze(case: Case):
    matrix = dict(principal=sum(l.principal for l in case.lines), gst=sum(l.gst for l in case.lines),
                  debit=0, credit=0, payment=0, interest=0)
    for entry in case.ledger:
        if entry.approved:
            matrix[entry.kind] += entry.base + entry.gst
    net = matrix["principal"] + matrix["gst"] + matrix["debit"] - matrix["credit"] - matrix["payment"]
    dpd = max(0, (case.as_of - case.due).days)
    age = (case.as_of - case.issued).days
    bucket = next(label for limit, label in [(0,"Current"),(30,"1–30"),(60,"31–60"),
                                              (90,"61–90"),(float("inf"),"91+")] if dpd <= limit)
    proof = [evidence_for(case, line) for line in case.lines]
    gst_match = bool(re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", case.gstin)
                     and case.gstin == case.master_gstin and case.buyer == case.master_name)
    row = case.statement_row
    statement = "Unavailable"
    if row:
        match = (row.invoice == case.invoice and row.issued == case.issued
                 and row.recipient_gstin == case.gstin and row.supplier_gstin == case.supplier_gstin
                 and row.principal == matrix["principal"] and row.gst == matrix["gst"])
        statement = "Matched" if match else "Mismatch"
    reasons = []
    if statement == "Mismatch":
        reasons.append("Reconcile the supplied GSTR-2B statement row against the original invoice.")
    if not gst_match:
        reasons.append("Reconcile buyer name and GSTIN against the account master.")
    if any(item["gaps"] for item in proof):
        reasons.append("Review the flagged invoice lines.")
    if case.dispute == "other":
        reasons.append("Resolve the unclassified dispute before requesting payment.")
    if any(not e.approved for e in case.ledger):
        reasons.append("Reconcile pending ledger entries.")
    if case.reverse_charge:
        reasons.append("Review reverse-charge tax treatment before collection.")
    if net <= 0:
        state = "Credit balance" if net < 0 else "Settled"
    elif reasons:
        state = "Review hold"
    elif dpd == 0:
        state = "Current"
    elif dpd <= 30:
        state = "Reminder"
    elif dpd <= 60:
        state = "Reconciliation"
    else:
        state = "Manager review"
    actions = {
        "Credit balance": "Reconcile the excess receipt with the buyer account.",
        "Settled": "Close the case after confirming the bank posting.",
        "Current": "Monitor until the contractual due date.",
        "Review hold": "Resolve each flagged item and import a corrected snapshot.",
        "Reminder": "Review a reminder requesting a payment date.",
        "Reconciliation": "Review the evidence packet and request a line-specific response within two calendar days.",
        "Manager review": "Assign a credit manager to review the contract, dispute history and account terms.",
    }
    draft = None
    if state in ("Reminder", "Reconciliation"):
        deadline = case.as_of + timedelta(days=2 if state == "Reconciliation" else 7)
        citations = [f"{p['line']} ({p['clause']}): {a['kind']} {a['id']}, {a['timestamp']}, "
                     f"{a['signer'] or a['source']}." for p in proof for a in p["anchors"]]
        routing = os.environ.get("PROOFPAY_REMITTANCE", "").strip()
        instruction = routing or f"Please use the payment instructions already agreed with {case.creditor}."
        draft = (f"Dear {case.buyer} accounts team,\n\nOur records show {rupees(net)} outstanding "
                 f"on {case.invoice}, due {case.due}.\n\n" + "\n".join(citations)
                 + f"\n\nPlease confirm a payment date or identify the disputed line and supporting record "
                   f"by {deadline}. {instruction}"
                 + f"\n\nAccounts receivable\n{case.creditor}")
    return dict(invoice=case.invoice, buyer=case.buyer, as_of=str(case.as_of), due=str(case.due),
                matrix=matrix, balance=net, collectible=max(net,0), dpd=dpd, bucket=bucket,
                state=state, action=actions[state], statement=statement, reasons=reasons, proof=proof, master_match=gst_match,
                itc_review=net>0 and age>=180 and not case.reverse_charge, draft=draft)
