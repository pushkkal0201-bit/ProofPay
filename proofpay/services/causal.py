import base64
import hashlib
import json
import os
from collections import defaultdict
from datetime import timedelta, timezone
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from engine.intake import parse_record


def signature_bytes(evidence):
    """Canonical v1 message. Bind all claims, text and crop to invoice and line."""
    material = evidence.model_dump(
        mode="json", exclude={"signature", "reviewer", "verified"}
    )
    return b"proofpay-evidence-v1\x00" + json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def verify_signature(evidence, keyring):
    signature = evidence.signature
    trusted = keyring.get(signature.key_id)
    if (
        not trusted
        or trusted["source"] != evidence.source
        or evidence.kind not in trusted["kinds"]
    ):
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(trusted["public_key"], validate=True)
        )
        key.verify(
            base64.b64decode(signature.ed25519_base64, validate=True),
            signature_bytes(evidence),
        )
        return True
    except (InvalidSignature, ValueError):
        return False


IST = timezone(timedelta(hours=5, minutes=30))


@lru_cache(maxsize=4)
def configured_keyring(raw):
    return json.loads(raw)


class CausalVerificationService:
    def __init__(self, keyring=None):
        self.keyring = (
            keyring
            if keyring is not None
            else configured_keyring(os.getenv("PROOFPAY_EVIDENCE_KEYS", "{}"))
        )
        for entry in self.keyring.values():
            if (
                not entry.get("source")
                or not isinstance(entry.get("kinds"), list)
                or not entry["kinds"]
            ):
                raise ValueError(
                    "Trusted keys require an issuer source and permitted evidence kinds."
                )
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(entry["public_key"], validate=True)
            )

    def evaluate(self, case):
        by_line = defaultdict(list)
        for evidence in case.evidence:
            if (
                evidence.invoice == case.invoice
                and evidence.verified
                and evidence.timestamp.astimezone(IST).date() <= case.as_of
            ):
                by_line[evidence.line].append(evidence)
        return [
            _evaluate_line(case, line, by_line[line.id], self.keyring)
            for line in case.lines
        ]


def _evaluate_line(case, line, records, keyring):
    rejected = [
        e.id for e in records if e.signature and not verify_signature(e, keyring)
    ]
    records = [e for e in records if e.id not in rejected]
    conflicting_files = [
        e.id
        for e in records
        if e.attachment
        and hashlib.sha256(e.attachment.text.encode("utf-8")).hexdigest()
        != e.attachment.sha256
    ]
    metadata_conflicts = []
    for e in records:
        if not e.attachment or e.id in conflicting_files:
            continue
        fields = parse_record(e.attachment.text)["fields"]
        expected = {"invoice": e.invoice, "line": e.line}
        if e.signer:
            expected["signer"] = e.signer
        if e.quantity:
            expected["quantity"] = str(e.quantity)
        if any(
            key in fields and fields[key] != value for key, value in expected.items()
        ):
            metadata_conflicts.append(e.id)
    records = [
        e
        for e in records
        if e.id not in conflicting_files and e.id not in metadata_conflicts
    ]
    signed = [e for e in records if e.signature]
    accepted = {"POD", "BOL"} if line.kind == "goods" else {"acceptance"}
    # Require one complete receipt; two copies of a partial receipt cannot add up.
    receipt = next(
        (
            e
            for e in records
            if e.kind in accepted
            and e.signer
            and (not line.require_signature or e in signed)
            and (e.quantity or 0) >= line.quantity
        ),
        None,
    )
    metric = next(
        (
            e
            for e in records
            if e.kind == "telemetry"
            and e.covers_contract_period
            and line.uptime_target_bps is not None
            and e.uptime_bps is not None
            and e.uptime_bps >= line.uptime_target_bps
        ),
        None,
    )
    gaps = [f"Attachment checksum mismatch: {key}." for key in conflicting_files]
    gaps.extend(
        f"Attachment fields conflict with evidence metadata: {key}."
        for key in metadata_conflicts
    )
    gaps.extend(f"Untrusted or invalid digital signature: {ref}." for ref in rejected)
    zone = line.delivery_zone
    fixes = [e for e in records if e.coordinates]
    inside = [
        e
        for e in fixes
        if zone
        and abs(e.coordinates.lat_e6 - zone.lat_e6) <= zone.tolerance_e6
        and min(
            abs(e.coordinates.lon_e6 - zone.lon_e6),
            360000000 - abs(e.coordinates.lon_e6 - zone.lon_e6),
        )
        <= zone.tolerance_e6
    ]
    if zone and (not inside or len(inside) != len(fixes)):
        gaps.append("Missing or conflicting destination coordinates.")
    if not receipt:
        gaps.append("Full-quantity signed receipt or acceptance required.")
    if line.uptime_target_bps is not None and not metric:
        gaps.append("Period-matched telemetry meeting the contract target required.")
    if line.uptime_target_bps is not None and any(
        e.kind == "telemetry"
        and e.covers_contract_period
        and e.uptime_bps is not None
        and e.uptime_bps < line.uptime_target_bps
        for e in records
    ):
        gaps.append(
            "A verified period report records uptime below the contract target."
        )
    if case.dispute == "performance":
        gaps.append("Reviewer must resolve the specific performance objection.")
    anchors = [e.model_dump(mode="json") for e in (receipt, metric) if e]
    anchors.extend(e.model_dump(mode="json") for e in records if e.kind == "eway")

    def milestone(name, matches, required, conflicting=()):
        return {
            "milestone": name,
            "required": required,
            "result": "fail"
            if conflicting
            else "pass"
            if matches
            else "unknown"
            if required
            else "not_applicable",
            "evidence_ids": [e.id for e in matches],
            "conflicts": list(conflicting),
        }

    truth = [
        milestone(
            "signed_full_quantity_receipt",
            [receipt] if receipt else [],
            True,
            [] if receipt else [e.id for e in records if e.kind in accepted],
        ),
        milestone("transit", [e for e in records if e.kind == "eway"], False),
        milestone(
            "digital_signature",
            [e for e in signed if e.kind in accepted],
            line.require_signature,
            rejected,
        ),
        milestone(
            "delivery_coordinates",
            inside,
            bool(zone),
            [e.id for e in fixes if zone and e not in inside],
        ),
        milestone(
            "period_uptime",
            [metric] if metric else [],
            line.uptime_target_bps is not None,
            [
                e.id
                for e in records
                if e.kind == "telemetry"
                and e.covers_contract_period
                and line.uptime_target_bps is not None
                and e.uptime_bps is not None
                and e.uptime_bps < line.uptime_target_bps
            ],
        ),
    ]
    return {
        "truth_table": truth,
        "line": line.id,
        "description": line.description,
        "clause": line.clause,
        "quantity": line.quantity,
        "target_bps": line.uptime_target_bps,
        "anchors": anchors,
        "gaps": gaps,
    }
