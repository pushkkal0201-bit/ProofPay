"""Reviewed accounting and legal inputs. All rates are annual basis points."""
from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[int, Field(strict=True, ge=0, le=10**11)]
Rate = Annotated[int, Field(strict=True, gt=0, le=10000)]
Ref = Annotated[str, Field(min_length=1, max_length=300)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaxSplit(Input):
    cgst: Money
    sgst: Money
    igst: Money

    @model_validator(mode="after")
    def check_regime(self):
        if self.igst and (self.cgst or self.sgst):
            raise ValueError("Mixed IGST and local tax require separate lines.")
        return self

    def total(self):
        return self.cgst + self.sgst + self.igst


class RatePoint(Input):
    effective: date
    bank_rate_bps: Rate
    source: Ref


class Terms(Input):
    basis: Literal["msmed", "contract"]
    authority_ref: Ref
    supplier_class: Literal["micro", "small"] | None = None
    acceptance: date | None = None
    written_agreement: bool | None = None
    rates: list[RatePoint] = Field(default_factory=list, max_length=240)
    annual_bps: Rate | None = None

    @model_validator(mode="after")
    def check_basis(self):
        dates = [r.effective for r in self.rates]
        if dates != sorted(set(dates)):
            raise ValueError("Rate schedule must have unique effective dates in ascending order.")
        if self.basis == "msmed":
            if not self.supplier_class or not self.acceptance or self.written_agreement is None or self.annual_bps:
                raise ValueError("Provide confirmed MSE eligibility, acceptance and agreement status.")
        elif not self.annual_bps or self.rates or self.acceptance or self.supplier_class or self.written_agreement is not None:
            raise ValueError("Contract basis requires an annual rate and clause reference only.")
        return self


class ContactPolicy(Input):
    """Operator-approved local business hours for the India-only workflow."""
    email_allowed: bool = True
    whatsapp_opt_in: bool = False
    contact_paused: bool = False
    start_hour_ist: Annotated[int, Field(ge=0, le=23)] = 9
    end_hour_ist: Annotated[int, Field(ge=1, le=24)] = 18

    @model_validator(mode="after")
    def validate_window(self):
        if self.start_hour_ist >= self.end_hour_ist:
            raise ValueError("Contact window must begin before it ends.")
        return self
