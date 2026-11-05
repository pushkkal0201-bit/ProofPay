"""Read-only interest scenarios and editable draft exports."""
import json
from datetime import timedelta
from email.message import EmailMessage
from email.policy import SMTP
from typing import Literal
from pydantic import Field
from .accrual import effective_due, estimate
from .notices import render_notice
from .policy import Input, RatePoint


class Projection(Input):
    invoice: str
    review_key: str
    bank_rate_bps: int = Field(strict=True, gt=0, le=10000)


def project(case, params):
    if not case.terms or case.terms.basis != "msmed":
        raise ValueError("Projection requires reviewed MSE terms.")
    copy = case.model_copy(deep=True)
    start = case.as_of
    copy.terms.rates = [r for r in copy.terms.rates if r.effective <= start]
    copy.terms.rates.append(RatePoint(effective=start+timedelta(days=1),
                                      bank_rate_bps=params.bank_rate_bps, source="Reviewer scenario"))
    due = effective_due(copy)
    points = []
    for offset in range(31):
        copy.as_of = start+timedelta(days=offset)
        result = estimate(copy,due)
        if result["amount"] is None:
            raise ValueError(result["status"])
        points.append(dict(date=str(copy.as_of),amount=result["amount"]))
    return dict(points=points,basis="Daily estimate, unchanged holdings, monthly rests")


class Handoff(Input):
    invoice: str
    review_key: str
    channel: Literal["email","whatsapp","pdf"]
    text: str = Field(min_length=1,max_length=20000)


def handoff(report, body):
    channels = report["COMMUNICATIONS_DRAFT"]
    eligible = channels["pdf_available"] if body.channel == "pdf" else channels[body.channel]
    if not eligible or not body.text.strip():
        raise ValueError("This channel requires a current eligible draft.")
    if body.channel == "pdf":
        return render_notice(dict(report,draft=body.text)), "application/pdf"
    if body.channel == "email":
        message = EmailMessage(policy=SMTP)
        message["X-Unsent"] = "1"
        message["Subject"] = "Payment reconciliation | " + report["invoice"]
        message.set_content(body.text,charset="utf-8")
        return message.as_bytes(), "message/rfc822"
    if len(body.text)>4096:
        raise ValueError("WhatsApp plain-text exports support up to 4,096 characters.")
    template = dict(messaging_product="whatsapp",to="",type="text",text=dict(body=body.text))
    return json.dumps(template,ensure_ascii=False,indent=2).encode(), "application/json"
