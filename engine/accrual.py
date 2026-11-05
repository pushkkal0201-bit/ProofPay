"""Interest estimates in paise. Reviewed gross basis; opening-of-day cash posting."""
from calendar import monthrange
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

DAY = timedelta(days=1)


def effective_due(case):
    t = case.terms
    if not t or t.basis == "contract":
        return case.due
    if t.written_agreement:
        return min(case.due, t.acceptance + 45 * DAY)
    return t.acceptance + 15 * DAY


def aging(days):
    for limit, name in [(0, "Current"), (30, "1–30"), (45, "31–45"), (90, "46–90")]:
        if days <= limit:
            return name
    return "91+"


def rounded(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate(case, due):
    t = case.terms
    result = dict(basis=t.basis if t else "none", amount=0, status="disabled", audit=[])
    if not t:
        return result
    result.update(authority=t.authority_ref, status="estimated")
    start = due + DAY
    if start > case.as_of:
        return result
    if (case.as_of - start).days > 3653:
        return dict(result, amount=None, status="Historical period requires manual review")
    if t.basis == "msmed" and (not t.rates or t.rates[0].effective > start):
        return dict(result, amount=None, status="Bank-rate coverage missing")
    postings = defaultdict(int)
    for e in case.ledger:
        if e.approved:
            postings[e.date] += (e.base + e.gst) * (1 if e.kind == "debit" else -1)
    balance = sum(l.principal + l.gst for l in case.lines) + sum(v for d,v in postings.items() if d < start)
    capital = Decimal(0)
    pending = Decimal(0)
    rate_index = 0
    rates = t.rates
    day = start
    segment = None
    while day <= case.as_of:
        balance += postings.get(day, 0)
        rate = t.annual_bps
        source = t.authority_ref
        if rates:
            while rate_index + 1 < len(rates) and rates[rate_index + 1].effective <= day:
                rate_index += 1
            rate = rates[rate_index].bank_rate_bps * 3
            source = rates[rate_index].source
        base = max(0, balance)
        if segment is None or (base, rate, source) != (segment["balance"], segment["annual_bps"], segment["source"]):
            segment = dict(start=str(day), end=str(day), balance=base, annual_bps=rate, source=source,
                           opening_capitalized=rounded(capital), days=0)
            result["audit"].append(segment)
        segment.update(end=str(day), days=segment["days"]+1)
        accrual = (base + capital) * rate / Decimal(3650000)
        pending += accrual
        if day.day == monthrange(day.year, day.month)[1]:
            if t.basis == "msmed":
                capital += pending
                pending = Decimal(0)
            segment = None
        if day == case.as_of:
            break
        day += DAY
    result["amount"] = rounded(capital + pending)
    return result
