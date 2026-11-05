import base64
from datetime import date, timedelta
from unittest import TestCase
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from proofpay.__main__ import ROOT
from proofpay.engine import analyze
from proofpay.models import Case, Coordinates, DeliveryZone, Signature
from proofpay.services.causal import CausalVerificationService, signature_bytes
from proofpay.services.ledger import LedgerService


def example(n=1047):
    return Case.model_validate_json((ROOT / "examples" / f"PP-{n}.json").read_bytes())


class LedgerAndTaxTests(TestCase):
    def test_mixed_fixed_point_inputs_and_independent_notes(self):
        d = example().model_dump(mode="json")
        d["lines"][0].update(
            principal="0.10",
            gst="0.02",
            split={"cgst": "0.01", "sgst": "0.01", "igst": 0},
        )

        def entry(id, kind, base, gst, approved=True):
            return {
                "id": id,
                "kind": kind,
                "date": d["issued"],
                "base": base,
                "gst": gst,
                "approved": approved,
            }

        d["ledger"] = [
            entry("D", "debit", "0.20", "0.04"),
            entry("C", "credit", "0.02", "0.01"),
            entry("P", "payment", "0.10", 0),
            entry("P2", "payment", "0.02", 0, False),
        ]
        matrix, balance = LedgerService().reconcile(Case.model_validate(d))
        self.assertEqual(
            (matrix["principal"], matrix["debit"], matrix["credit"], balance),
            (10, 24, 3, 23),
        )
        for invalid in [0.1, "0.123", "1e-1", True, "NaN"]:
            d["lines"][0]["principal"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                Case.model_validate(d)

    def test_jurisdiction_uses_place_of_supply_and_sez(self):
        c = example()
        c.place_of_supply = "27"
        self.assertEqual(analyze(c)["tax_compliance"]["regime"], "intra_state")
        c.place_of_supply = "09"
        r = analyze(c)
        self.assertEqual(r["tax_compliance"]["regime"], "inter_state")
        self.assertTrue(r["tax_compliance"]["issues"])
        self.assertIsNone(r["draft"])
        c.place_of_supply = "27"
        c.sez_supply = True
        self.assertEqual(analyze(c)["tax_compliance"]["regime"], "inter_state")
        c.sez_supply = False
        c.place_of_supply = None
        self.assertEqual(analyze(c)["tax_compliance"]["regime"], "undetermined")

    def test_payment_clock_is_independent_of_statement_window(self):
        c = example()
        c.ledger = []
        deadline = c.issued + timedelta(days=180)
        c.statement_row = None
        c.statement_expected_on = deadline + timedelta(days=1)
        c.as_of = deadline
        tax = analyze(c)["tax_compliance"]
        self.assertEqual(
            (tax["payment_status"], tax["statement_window"]),
            ("payment_window_closes_today", "awaiting_statement"),
        )
        c.as_of += timedelta(days=1)
        self.assertEqual(
            analyze(c)["tax_compliance"]["payment_status"], "unpaid_after_window"
        )
        p = example().ledger[0]
        p.date = c.as_of
        p.base = 17700000
        c.ledger = [p]
        tax = analyze(c)["tax_compliance"]
        self.assertEqual(tax["statement_window"], "statement_not_observed")
        self.assertEqual(tax["balance_at_deadline"], 17700000)
        self.assertEqual(
            tax["payment_status"], "subsequently_settled_review_reavailment"
        )
        p.date = deadline
        self.assertEqual(
            analyze(c)["tax_compliance"]["payment_status"],
            "no_unpaid_balance_at_deadline",
        )
        c.reverse_charge = True
        self.assertEqual(
            analyze(c)["tax_compliance"]["payment_status"], "outside_payment_review"
        )

    def test_registration_requires_qualified_terms(self):
        d = example().model_dump()
        d["msme_registered"] = False
        with self.assertRaises(ValidationError):
            Case.model_validate(d)
        d.update(msme_registered=True, terms=None)
        self.assertEqual(analyze(Case.model_validate(d))["state"], "Review hold")
        c = example()
        c.msme_registered = True
        c.ledger = []
        clock = analyze(c)["statutory_clock"]
        self.assertEqual(
            (clock["day_45"], clock["interest_starts_on"]), ("2026-10-11", "2026-10-12")
        )
        c.terms.written_agreement = False
        self.assertEqual(
            analyze(c)["statutory_clock"]["interest_starts_on"], "2026-09-12"
        )


class EvidenceTests(TestCase):
    def setUp(self):
        self.case = example()
        self.asset = self.case.evidence[0]
        self.case.lines[0].require_signature = True
        origin = {"lat_e6": 26700000, "lon_e6": 80900000}
        self.case.lines[0].delivery_zone = DeliveryZone(**origin, tolerance_e6=1000)
        self.asset.coordinates = Coordinates(**origin)
        self.key = Ed25519PrivateKey.generate()
        keyring = {
            "carrier-1": {
                "source": self.asset.source,
                "kinds": ["POD"],
                "public_key": base64.b64encode(
                    self.key.public_key().public_bytes_raw()
                ).decode(),
            }
        }
        self.service = CausalVerificationService(keyring)
        self.sign()

    def sign(self):
        self.asset.signature = Signature(
            key_id="carrier-1",
            ed25519_base64=base64.b64encode(
                self.key.sign(signature_bytes(self.asset))
            ).decode(),
        )

    def test_signature_position_and_tamper(self):
        proofs = analyze(self.case, verifier=self.service)["proof"][0]
        table = {r["milestone"]: r["result"] for r in proofs["truth_table"]}
        self.assertEqual(
            (table["digital_signature"], table["delivery_coordinates"]),
            ("pass", "pass"),
        )
        self.asset.coordinates.lon_e6 += 100000
        report = analyze(self.case, verifier=self.service)
        self.assertIsNone(report["draft"])
        self.assertIn("invalid digital signature", " ".join(report["proof"][0]["gaps"]))
        self.sign()
        truth = {
            r["milestone"]: r["result"]
            for r in self.service.evaluate(self.case)[0]["truth_table"]
        }
        self.assertEqual(
            (truth["digital_signature"], truth["delivery_coordinates"]),
            ("pass", "fail"),
        )

    def test_scope_mismatch_and_untrusted_key(self):
        self.asset.signature.key_id = "unknown"
        self.assertIsNone(analyze(self.case, verifier=self.service)["draft"])
        self.asset.invoice = "ANOTHER"
        results = {
            r["milestone"]: r
            for r in self.service.evaluate(self.case)[0]["truth_table"]
        }
        self.assertEqual(results["digital_signature"]["result"], "unknown")
        self.assertEqual(results["transit"]["result"], "pass")

    def test_dispute_uses_evidence_service_even_on_gst_match(self):
        mocked = CausalVerificationService()
        with patch.object(
            mocked,
            "evaluate",
            return_value=[{"line": "L1", "anchors": [], "gaps": ["carrier outage"]}],
        ) as call:
            r = analyze(self.case, verifier=mocked)
        call.assert_called_once_with(self.case)
        self.assertEqual(r["statement"], "Matched")
        self.assertIsNone(r["draft"])


class IntervalReferenceTests(TestCase):
    def test_irregular_ledger_matches_daily_oracle_across_leap_day(self):
        import random
        from calendar import monthrange
        from decimal import ROUND_HALF_UP, Decimal

        from engine.accrual import effective_due, estimate
        from engine.policy import RatePoint
        from proofpay.models import Entry

        rng = random.Random(54)
        for sample in range(12):
            c = example()
            c.issued = date(2023, 11, 1)
            c.terms.acceptance = c.issued
            c.due = date(2024, 1, 31)
            c.as_of = date(2024, 4, 10) + timedelta(days=sample)
            c.terms.rates = [
                RatePoint(effective=c.issued, bank_rate_bps=675, source="fixture"),
                RatePoint(
                    effective=date(2024, 2, 29), bank_rate_bps=625, source="fixture 2"
                ),
            ]
            c.ledger = [
                Entry(
                    id=f"p{i}",
                    kind=rng.choice(["payment", "credit", "debit"]),
                    date=c.issued + timedelta(days=rng.randrange(155)),
                    base=rng.randrange(200000),
                    gst=0,
                    approved=True,
                )
                for i in range(36)
            ]
            start = effective_due(c) + timedelta(days=1)
            capital = Decimal(0)
            pending = Decimal(0)
            d = start
            while d <= c.as_of:
                principal = 17700000 + sum(
                    (1 if e.kind == "debit" else -1) * e.base
                    for e in c.ledger
                    if e.date <= d
                )
                bank = 675 if d < date(2024, 2, 29) else 625
                pending += (Decimal(max(0, principal)) + capital) * 3 * bank / 3650000
                if d.day == monthrange(d.year, d.month)[1]:
                    capital += pending
                    pending = Decimal(0)
                d += timedelta(days=1)
            expected = int(
                (capital + pending).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
            self.assertEqual(estimate(c, effective_due(c))["amount"], expected)
