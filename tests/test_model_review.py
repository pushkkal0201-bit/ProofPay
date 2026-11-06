import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from proofpay.__main__ import Handler, ThreadingHTTPServer, init_db
from proofpay.agent import suggest
from proofpay.engine import analyze
from proofpay.models import Case


class ReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "review.db")
        init_db(self.db)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.database = self.db
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        with urlopen(self.base + "/api/cases") as response:
            self.case = next(c for c in json.load(response) if c["invoice"] == "PP-1043")

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temp.cleanup()

    def review(self, **overrides):
        payload = dict(invoice=self.case["invoice"], review_key=self.case["review_key"], require_model=True)
        payload.update(overrides)
        request = Request(self.base + "/api/agent", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def test_model_inspections_and_snapshot_binding(self):
        with patch.dict(os.environ, {"PROOFPAY_MODEL": "fixture", "PROOFPAY_PROVIDER": "ollama"}):
            with patch("proofpay.agent.ask_model", return_value={"task": "check_source"}):
                result = self.review()
        self.assertEqual(result["review_key"], self.case["review_key"])
        self.assertEqual(result["provider"], "ollama")
        evidence = next(i["result"] for i in result["inspections"] if i["tool"] == "read_evidence")
        self.assertEqual(evidence[0]["submitted_records"][0]["id"], "POD-1043")
        self.assertEqual(evidence[0]["submitted_records"][0]["quantity"], 1)
        self.assertTrue(evidence[0]["gaps"])

    def test_model_required_and_stale_requests(self):
        with patch.dict(os.environ, {"PROOFPAY_MODEL": ""}):
            with self.assertRaises(HTTPError) as error:
                self.review()
            self.assertEqual(error.exception.code, 503)
        with patch("proofpay.agent.ask_model") as model:
            with self.assertRaises(HTTPError) as error:
                self.review(review_key="stale")
            self.assertEqual(error.exception.code, 409)
            model.assert_not_called()

    def test_revision_during_inference(self):
        def revise(*args):
            with sqlite3.connect(self.db) as connection:
                row = connection.execute("SELECT data FROM cases WHERE id=?", ("PP-1043",)).fetchone()
                source = json.loads(row[0])
                source["dispute_text"] = "Updated while reviewer was running."
                connection.execute("UPDATE cases SET data=? WHERE id=?", (json.dumps(source), "PP-1043"))
            return {"mode": "fixture"}
        with patch.dict(os.environ, {"PROOFPAY_MODEL": "fixture", "PROOFPAY_PROVIDER": "ollama"}):
            with patch("proofpay.__main__.suggest", side_effect=revise):
                with self.assertRaises(HTTPError) as error:
                    self.review()
                self.assertEqual(error.exception.code, 409)

    def test_provider_failure_visible(self):
        with patch.dict(os.environ, {"PROOFPAY_MODEL": "fixture", "PROOFPAY_PROVIDER": "ollama"}):
            with patch("proofpay.agent.ask_model", side_effect=TimeoutError):
                with self.assertRaises(HTTPError) as error:
                    self.review()
                self.assertEqual(error.exception.code, 503)

    def test_model_selects_from_allowed_tasks(self):
        case = Case.model_validate(self.case["source"])
        with patch.dict(os.environ, {"PROOFPAY_MODEL": "fixture"}):
            with patch("proofpay.agent.ask_model", return_value={"task": "not_allowed"}):
                with self.assertRaises(ValueError):
                    suggest(case, analyze(case))
