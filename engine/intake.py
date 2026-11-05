"""Offline source adapters. Missing information is returned to the reviewer."""
import csv
import json
import io
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pydantic import Field, model_validator
from proofpay.models import Case, Entry, StatementRow, Text, Amount
from engine.policy import Input


def parse_record(text):
    """Extract labeled values from pasted POD, e-way and telemetry text; never attest it."""
    patterns = {
        "invoice": r"(?:invoice(?: id| no\.?)?)",
        "line": r"(?:invoice line|line(?: id)?)",
        "tracking": r"(?:tracking(?: reference)?|e-way bill(?: no\.?)?|pod id)",
        "signer": r"(?:signed by|received by|acknowledged by|signer)",
        "timestamp": r"(?:delivered at|timestamp|recorded at)",
        "quantity": r"(?:quantity(?: accepted)?|units received)",
        "uptime": r"(?:uptime)",
    }
    fields, issues = {}, []
    for key, label in patterns.items():
        values = set(re.findall(r"^\s*" + label + r"\s*[:=]\s*([^\r\n]+?)\s*$",text,re.I|re.M))
        if len(values) == 1:
            fields[key] = values.pop()
        elif len(values) > 1:
            issues.append(f"Ambiguous {key}")
    for key in ("invoice", "line", "timestamp"):
        if key not in fields:
            issues.append(f"Missing {key}")
    if fields.get("timestamp"):
        try:
            dt = datetime.fromisoformat(fields["timestamp"].replace(" IST","+05:30").replace("Z","+00:00"))
            if dt.utcoffset() is None:
                raise ValueError
            fields["timestamp"] = dt.isoformat()
        except ValueError:
            issues.append("Timestamp requires an ISO date and offset")
    return dict(fields=fields, issues=issues, verified=False)


class Allocation(Input):
    invoice: Text
    amount: Amount = Field(gt=0)


class CashReceipt(Input):
    reference: Text
    buyer_gstin: Text
    creditor: Text
    date: date
    received: Amount
    allocations: list[Allocation] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def check_allocations(self):
        ids = [a.invoice for a in self.allocations]
        if len(ids) != len(set(ids)) or sum(a.amount for a in self.allocations) > self.received:
            raise ValueError("Duplicate target invoice or over-allocated payment.")
        return self


def reconcile_batch(snapshots, receipts):
    cases = {c.invoice: c.model_copy(deep=True) for c in snapshots}
    if len(cases) != len(snapshots):
        raise ValueError("Duplicate invoice IDs in portfolio.")
    unallocated = {}
    for receipt in receipts:
        if receipt.reference in unallocated:
            raise ValueError("Duplicate payment reference.")
        unallocated[receipt.reference] = receipt.received - sum(a.amount for a in receipt.allocations)
        target_ids = {a.invoice for a in receipt.allocations}
        for c in cases.values():
            if (c.creditor,c.gstin) == (receipt.creditor,receipt.buyer_gstin) and c.invoice not in target_ids:
                if any(e.id == receipt.reference for e in c.ledger):
                    raise ValueError("Existing allocation was omitted from this receipt.")
        for a in receipt.allocations:
            c = cases.get(a.invoice)
            if not c or (c.gstin,c.creditor) != (receipt.buyer_gstin,receipt.creditor) or receipt.date > c.as_of:
                raise ValueError("Unknown invoice, wrong counterparty or future payment.")
            entry = Entry(id=receipt.reference,kind="payment",date=receipt.date,base=a.amount,gst=0,approved=True)
            existing = next((e for e in c.ledger if e.id == receipt.reference),None)
            if existing and existing != entry:
                raise ValueError("Conflicting payment reference on invoice.")
            if not existing:
                c.ledger.append(entry)
    return [Case.model_validate(c.model_dump()) for c in cases.values()], unallocated


def match_statement(cases, text):
    """Replace prior statement observations for this complete export's invoice scope."""
    rows = defaultdict(list)
    reader = csv.DictReader(io.StringIO(text))
    required = {"invoice","issued","supplier_gstin","recipient_gstin","principal","cgst","sgst","igst"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("The statement CSV header is incomplete.")
    for row in reader:
        split = {k:int(row[k]) for k in ("cgst","sgst","igst")}
        item = StatementRow(invoice=row["invoice"],issued=row["issued"],supplier_gstin=row["supplier_gstin"],
                            recipient_gstin=row["recipient_gstin"],principal=int(row["principal"]),
                            gst=sum(split.values()),split=split)
        rows[(item.supplier_gstin,item.recipient_gstin,item.invoice)].append(item)
    output = []
    for case in cases:
        matches = rows[(case.supplier_gstin,case.gstin,case.invoice)]
        if len(matches) > 1:
            raise ValueError(f"Multiple statement rows for {case.invoice}; reconcile amendments first.")
        output.append(case.model_copy(update={"statement_row":matches[0] if matches else None}))
    return output


def review_profile(payload):
    """A compact profile is incomplete for collection. Return a deterministic intake hold."""
    ledger = payload["financial_ledger"]
    def paise(key):
        value = Decimal(str(ledger[key])) * 100
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise ValueError(f"Invalid rupee amount: {key}")
        return int(value)
    base, tax, credit = (paise(k) for k in ("base_value","gst_value","credits_applied"))
    return dict(LEDGER_SUMMARY=dict(invoice=ledger["invoice_id"],unit="paise",original_principal=base,
                                    original_gst=tax,reported_credits=credit,unverified_balance=base+tax-credit,
                                    total_owed=None,dpd=None), CAUSAL_ANCHOR=dict(candidate=payload["execution_metrics"],verified=False),
                TRANSACTION_STRATEGY=dict(tier="Intake hold",action="Supply as-of date, due terms, master identity, approved postings and line-level reviewed evidence. Confirm MSE eligibility and acceptance separately."),
                COMMUNICATIONS_DRAFT=dict(email=None,whatsapp=None,pdf_available=False,status="withheld"))


def post_portfolio(db, data, analyze, snapshot, review_key):
    """Apply shared cash and a scoped tax export as one compare-and-swap transaction."""
    versions = data["versions"]
    if not isinstance(versions, dict) or not 1 <= len(versions) <= 500:
        raise ValueError("Provide review keys for 1–500 scoped invoices.")
    db.execute("BEGIN IMMEDIATE")
    originals = {}
    cases = []
    for invoice, version in versions.items():
        row = db.execute("SELECT data FROM cases WHERE id=?", (invoice,)).fetchone()
        if not row:
            raise ValueError(f"Unknown scoped invoice: {invoice}")
        case = Case.model_validate_json(row[0])
        if review_key(row[0], analyze(case)) != version:
            raise VersionConflict("A scoped invoice changed. Refresh before posting.")
        originals[invoice] = row[0]
        cases.append(case)
    receipts = [CashReceipt.model_validate(r) for r in data.get("payments", [])]
    cases, residuals = reconcile_batch(cases, receipts)
    for receipt in receipts:
        fingerprint = receipt.model_dump(mode="json")
        fingerprint["allocations"].sort(key=lambda a:a["invoice"])
        encoded = json.dumps(fingerprint,sort_keys=True)
        key = (receipt.creditor,receipt.buyer_gstin,receipt.reference)
        previous = db.execute("SELECT data FROM cash_receipts WHERE creditor=? AND buyer=? AND ref=?",key).fetchone()
        if previous and previous[0] != encoded:
            raise VersionConflict("Cash reference already posted with different allocations.")
        db.execute("INSERT OR IGNORE INTO cash_receipts VALUES (?,?,?,?)",(*key,encoded))
    if "statement_csv" in data:
        cases = match_statement(cases,data["statement_csv"])
    changed = []
    for c in cases:
        old = originals[c.invoice]
        if Case.model_validate_json(old) == c:
            continue
        db.execute("INSERT INTO history(id,data) VALUES (?,?)",(c.invoice,old))
        db.execute("UPDATE cases SET data=? WHERE id=?",(snapshot(c),c.invoice))
        changed.append(c.invoice)
    return dict(changed=changed, unapplied_cash=residuals)


class VersionConflict(ValueError):
    pass
