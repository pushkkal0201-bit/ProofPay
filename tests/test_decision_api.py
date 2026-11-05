import hashlib
import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from proofpay.__main__ import ROOT
from proofpay.api import create_app
from proofpay.services.journal import digest


class DecisionApiTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "journal.sqlite3")
        key = "test-operator-secret" * 2
        self.client = self.enterContext(
            TestClient(create_app(self.path, {"reviewer": key}))
        )
        self.auth = {"Authorization": "Bearer " + key}
        self.source = json.loads((ROOT / "examples/PP-1047.json").read_bytes())

    def post(self, key, items):
        return self.client.post(
            "/v1/decisions",
            headers={**self.auth, "Idempotency-Key": key},
            json={"items": items},
        )

    def item(self, rev=0, **changes):
        return {"expected_revision": rev, "case": {**self.source, **changes}}

    def test_auth_and_payload_limit(self):
        r = self.client.post(
            "/v1/decisions",
            json={"items": [self.item()]},
            headers={"Idempotency-Key": "A"},
        )
        self.assertEqual(r.status_code, 401)
        r = self.client.post(
            "/v1/decisions", headers=self.auth, content=b"x" * (4194304 + 1)
        )
        self.assertEqual(r.status_code, 413)

    def test_exact_retry_and_atomic_failure(self):
        first = self.post("one", [self.item()])
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json(), self.post("one", [self.item()]).json())
        self.assertEqual(
            self.post("one", [self.item(dispute="other")]).status_code, 409
        )
        # First insert of the second batch must be rolled back when its last CAS fails.
        self.assertEqual(
            self.post("batch", [self.item(invoice="NEW"), self.item()]).status_code, 409
        )
        with sqlite3.connect(self.path) as db:
            self.assertEqual(
                db.execute("select count(*) from decision_versions").fetchone()[0], 1
            )

    def test_concurrent_writers_and_hash_chain(self):
        stream = self.post("initial", [self.item()]).json()[0]["stream"]
        with ThreadPoolExecutor(2) as pool:
            statuses = list(
                pool.map(
                    lambda k: self.post(k, [self.item(1, dispute="other")]).status_code,
                    ("B", "C"),
                )
            )
        self.assertEqual(sorted(statuses), [201, 409])
        root = "/v1/decisions/" + stream
        audit = self.client.get(root + "/audit", headers=self.auth).json()
        self.assertEqual(audit[1]["event"]["previous"], audit[0]["sha256"])
        self.assertEqual(audit[1]["sha256"], digest(audit[1]["event"]))
        self.assertEqual(
            self.client.get(root + "?revision=1", headers=self.auth).json()["report"][
                "state"
            ],
            "MSE legal review",
        )
        self.assertIsNone(
            self.client.get(root, headers=self.auth).json()["report"]["draft"]
        )
        result = self.client.post(
            root + "/communications",
            headers=self.auth,
            json={"revision": 1, "channel": "pdf"},
        )
        self.assertEqual(result.status_code, 409)

    def test_export_receipts_and_mocked_render_failure(self):
        stream = self.post("initial", [self.item()]).json()[0]["stream"]
        root = "/v1/decisions/" + stream
        for channel in ["markdown", "whatsapp", "pdf"]:
            r = self.client.post(
                root + "/communications",
                headers=self.auth,
                json={"revision": 1, "channel": channel},
            )
            self.assertEqual(r.status_code, 200, r.text[:100])
            self.assertEqual(
                r.headers["x-content-sha256"], hashlib.sha256(r.content).hexdigest()
            )
            saved = self.client.get(
                root + "/exports/" + r.headers["x-export-id"], headers=self.auth
            )
            self.assertEqual(saved.content, r.content)
        with patch(
            "engine.workbench.render_notice",
            side_effect=ValueError("renderer rejected source"),
        ):
            r = self.client.post(
                root + "/communications",
                headers=self.auth,
                json={"revision": 1, "channel": "pdf"},
            )
            self.assertEqual(r.status_code, 422)
        exports = self.client.get(root + "/exports", headers=self.auth).json()
        self.assertEqual(len(exports), 3)
        self.assertEqual(exports[-1]["actor"], "reviewer")

    def test_projected_clock_preserves_archived_snapshot(self):
        stream = self.post("initial", [self.item()]).json()[0]["stream"]
        root = "/v1/decisions/" + stream
        projected = self.client.get(root + "/clock?on=2027-01-01", headers=self.auth)
        self.assertEqual(projected.status_code, 200, projected.text)
        self.assertEqual(projected.json()["dpd"], 82)
        self.assertEqual(
            self.client.get(root, headers=self.auth).json()["report"]["dpd"], 65
        )
        self.assertEqual(
            self.client.get(
                root + "/clock?on=2025-01-01", headers=self.auth
            ).status_code,
            422,
        )

    def test_changed_stored_report_is_detected(self):
        stream = self.post("initial", [self.item()]).json()[0]["stream"]
        with sqlite3.connect(self.path) as db:
            db.execute(
                "update decision_versions set report='{}' where stream=?", (stream,)
            )
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            self.client.get("/v1/decisions/" + stream, headers=self.auth)
