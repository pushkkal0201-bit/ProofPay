"""Serialize the audit packet consumed by API, CLI and the review desk."""
from decimal import Decimal


def breakdown(records):
    taxes = dict(cgst=0, sgst=0, igst=0, unallocated=0)
    for row, sign in records:
        if row.split:
            for field, value in row.split.model_dump().items():
                taxes[field] += sign * value
        else:
            taxes["unallocated"] += sign * row.gst
    return taxes


def packet(case, report, due, accrual):
    records = [(line, 1) for line in case.lines]
    for entry in case.ledger:
        if entry.approved and entry.kind != "payment":
            records.append((entry, 1 if entry.kind == "debit" else -1))
    cash = sorted((e for e in case.ledger if e.approved and e.kind == "payment"), key=lambda e:e.date)
    matrix = report["matrix"]
    summary = dict(currency="INR", unit="paise", original_principal=matrix["principal"],
                   original_gst=matrix["gst"], adjusted_tax_split=breakdown(records),
                   credits=matrix["credit"], debits=matrix["debit"], payments=matrix["payment"],
                   total_owed=report["collectible"], signed_balance=report["balance"],
                   effective_due=str(due), contract_due=str(case.due), dpd=report["dpd"],
                   bucket=report["bucket"], interest_estimate=accrual,
                   payment_history=dict(count=len(cash), latest=str(cash[-1].date) if cash else None,
                                        received_after_due=sum(e.base for e in cash if e.date > due)))
    refs = [a["id"] for p in report["proof"] for a in p["anchors"]]
    email = report["draft"]
    whatsapp = None
    if email and case.contact.whatsapp_opt_in:
        whatsapp = (f"{case.creditor} to {case.buyer} accounts payable: please review {case.invoice}. "
                    f"Outstanding INR {Decimal(summary['total_owed'])/100:,.2f}; evidence {', '.join(refs)}. "
                    f"Please confirm a payment date or identify the disputed line by {report['response_by']}.")
    return dict(LEDGER_SUMMARY=summary, CAUSAL_ANCHOR=report["proof"],
                TRANSACTION_STRATEGY=dict(tier=report["state"], action=report["action"], holds=report["reasons"]),
                COMMUNICATIONS_DRAFT=dict(email=email if case.contact.email_allowed else None, whatsapp=whatsapp, pdf_available=bool(email),
                                          contact_window_ist=[case.contact.start_hour_ist,case.contact.end_hour_ist],
                                          status="review_required" if email else "withheld"))
