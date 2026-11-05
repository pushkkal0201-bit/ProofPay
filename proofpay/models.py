"""Input contract. All values represent one invoice snapshot in INR paise."""
import base64
import hashlib
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from datetime import date
from engine.policy import ContactPolicy, Money, TaxSplit, Terms
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Amount = Money
Quantity = Annotated[int, Field(strict=True, gt=0, le=10**8)]
Bps = Annotated[int, Field(strict=True, ge=0, le=10000)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Coordinates(Record):
    # Integer microdegrees keep comparisons and signed payloads lossless.
    lat_e6: Annotated[int, Field(strict=True, ge=-90000000, le=90000000)]
    lon_e6: Annotated[int, Field(strict=True, ge=-180000000, le=180000000)]


class DeliveryZone(Coordinates):
    tolerance_e6: Annotated[int, Field(strict=True, ge=0, le=1000000)]


class Signature(Record):
    key_id: Text
    ed25519_base64: Annotated[str, Field(min_length=88, max_length=88)]


class Line(Record):
    delivery_zone: DeliveryZone | None = None
    require_signature: bool = False
    id: Text
    description: Text
    kind: Literal["goods", "service"]
    quantity: Quantity
    principal: Amount
    gst: Amount
    split: TaxSplit | None = None
    clause: Text
    uptime_target_bps: Bps | None = None


class Attachment(Record):
    filename: Text
    text: Annotated[str, Field(min_length=1, max_length=18000)]
    sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class Crop(Record):
    png_base64: Annotated[str, Field(min_length=1,max_length=240000)]
    sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    ocr_text: Annotated[str, Field(max_length=18000)]
    origin: Text

    @model_validator(mode="after")
    def check_image(self):
        raw = base64.b64decode(self.png_base64,validate=True)
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError("Signed-note crop checksum mismatch.")
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.format != "PNG" or image.width * image.height > 4000000:
                    raise ValueError("Attach a PNG crop of up to four megapixels.")
                image.verify()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as err:
            raise ValueError("Invalid crop image.") from err
        return self


class Evidence(Record):
    signature: Signature | None = None
    coordinates: Coordinates | None = None
    crop: Crop | None = None
    attachment: Attachment | None = None
    id: Text
    invoice: Text
    line: Text
    kind: Literal["POD", "BOL", "acceptance", "telemetry", "eway"]
    timestamp: AwareDatetime
    source: Text
    reviewer: Text
    verified: bool
    signer: Text | None = None
    quantity: Quantity | None = None
    uptime_bps: Bps | None = None
    covers_contract_period: bool = False


class Entry(Record):
    id: Text
    kind: Literal["payment", "credit", "debit"]
    date: date
    base: Amount
    gst: Amount
    split: TaxSplit | None = None
    approved: bool


class StatementRow(Record):
    """Recipient statement snapshot of the original invoice, before adjustments."""
    invoice: Text
    supplier_gstin: Text
    recipient_gstin: Text
    issued: date
    principal: Amount
    gst: Amount
    split: TaxSplit | None = None


class Case(Record):
    msme_registered: bool | None = None
    place_of_supply: Annotated[str, Field(pattern="^[0-9]{2}$")] | None = None
    sez_supply: bool = False
    statement_expected_on: date | None = None
    itc_availed: bool | None = None
    contact: ContactPolicy = Field(default_factory=ContactPolicy)
    terms: Terms | None = None
    supplier_gstin: Text | None = None
    statement_row: StatementRow | None = None
    invoice: Text
    creditor: Text
    buyer: Text
    gstin: Text
    master_gstin: Text | None
    master_name: Text | None
    issued: date
    due: date
    as_of: date
    dispute: Literal["none", "non_receipt", "performance", "other"]
    dispute_text: Text | None = None
    reverse_charge: bool = False
    lines: list[Line] = Field(min_length=1, max_length=300)
    evidence: list[Evidence] = Field(max_length=1000)
    ledger: list[Entry] = Field(max_length=1000)

    @model_validator(mode="after")
    def check_snapshot(self):
        if max(self.issued, self.due, self.as_of).year > 9900:
            raise ValueError("Dates exceed the supported projection horizon.")
        if self.msme_registered is False and self.terms and self.terms.basis == "msmed":
            raise ValueError("MSE terms conflict with negative registration verification.")
        if self.statement_expected_on and self.statement_expected_on < self.issued:
            raise ValueError("Statement observation window cannot precede invoice issue.")
        if min(self.as_of, self.due) < self.issued:
            raise ValueError("Snapshot and due date must be on or after issue.")
        for entry in [*self.lines, *self.ledger, *([self.statement_row] if self.statement_row else [])]:
            if entry.split and entry.split.total() != entry.gst:
                raise ValueError("GST components must sum to the posted GST.")
        if self.terms and self.terms.acceptance and self.terms.acceptance > self.as_of:
            raise ValueError("Acceptance cannot be in the future.")
        for records in [self.lines, self.evidence, self.ledger]:
            if len({r.id for r in records}) != len(records):
                raise ValueError("Duplicate IDs within a record collection.")
        if any(e.date > self.as_of for e in self.ledger):
            raise ValueError("Ledger contains future entries.")
        if any(e.kind == "payment" and e.gst for e in self.ledger):
            raise ValueError("Record the full cash payment in base with gst=0.")
        return self
