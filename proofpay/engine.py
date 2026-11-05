"""Deterministic policy. Imported evidence is a human-reviewed attestation."""
import os
from datetime import timedelta
from .models import Case
from proofpay.services.ledger import LedgerService
from proofpay.services.causal import CausalVerificationService
from proofpay.services.tax import TaxComplianceService
from proofpay.services.escalation import EscalationEngine
from engine.packet import packet


def rupees(paise):
    return f"INR {paise // 100:,}.{paise % 100:02d}"


def analyze(case: Case, *, verifier=None):
    ledger = LedgerService()
    matrix, net = ledger.reconcile(case)
    due, dpd, bucket, accrual, statutory = EscalationEngine.clock(case)
    proof = (verifier or CausalVerificationService()).evaluate(case)
    tax = TaxComplianceService.evaluate(case, matrix, net, ledger)
    statement = tax["statement"]
    gst_match = tax["master_match"]
    reasons = list(tax["issues"])
    if case.msme_registered and not case.terms:
        reasons.append("Confirm supplier classification, acceptance and terms before escalation.")
    if case.contact.contact_paused:
        reasons.append("Buyer contact is paused.")
    if accrual["amount"] is None:
        reasons.append(accrual["status"])
    if case.terms and case.terms.basis == "msmed" and case.terms.written_agreement and case.due < case.terms.acceptance:
        reasons.append("Resolve the agreed due date preceding acceptance.")
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
    state, action = EscalationEngine.decide(case, net, dpd, reasons)
    draft = None
    deadline = None
    if state in ("Reminder", "Reconciliation", "MSE legal review", "Manager review"):
        deadline = case.as_of + timedelta(days=7 if state == "Reminder" else 2)
        citations = [f"{p['line']} ({p['clause']}): {a['kind']} {a['id']}, {a['timestamp']}, "
                     f"{a['signer'] or a['source']}." for p in proof for a in p["anchors"]]
        routing = os.environ.get("PROOFPAY_REMITTANCE", "").strip()
        instruction = routing or f"Please use the payment instructions already agreed with {case.creditor}."
        draft = (f"Dear {case.buyer} accounts payable team,\n\nOur records show {rupees(net)} outstanding "
                 f"on {case.invoice}, due {due}.\n\n" + "\n".join(citations)
                 + f"\n\nPlease confirm a payment date or identify the disputed line and supporting record "
                   f"by {deadline}. {instruction}")
        if state == "MSE legal review":
            draft += (f"\n\nOur reviewed terms reference {case.terms.authority_ref}. Sections 15 and 16 "
                      f"of the MSMED Act address payment timing and interest. Our separate provisional "
                      f"interest estimate as of {case.as_of} is {rupees(accrual['amount'])}. "
                      "Please reconcile the stated dates and transactions. We may seek review of a "
                      "reference to the Facilitation Council under section 18.")
        elif state == "Manager review":
            draft += "\n\nOur credit manager is reviewing this outstanding account."
        draft += f"\n\nAccounts receivable\n{case.creditor}"
    report = dict(invoice=case.invoice, buyer=case.buyer, as_of=str(case.as_of), due=str(due),
                matrix=matrix, balance=net, collectible=max(net,0), dpd=dpd, bucket=bucket,
                state=state, action=action, statement=statement, reasons=reasons, proof=proof, master_match=gst_match,
                tax_compliance=tax, statutory_clock=statutory, itc_review=tax["review"], draft=draft, response_by=str(deadline) if deadline else None)
    report.update(packet(case, report, due, accrual))
    return report
