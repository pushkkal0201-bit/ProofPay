"""Local loopback ingestion benchmark with real HTTP, validation and durable commits."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter, sleep
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 100 or min(args.batches, args.concurrency) < 1:
        parser.error("Use positive counts and at most 100 invoices per batch.")
    source = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/PP-1042.json").read_bytes()
    )
    token = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    def batch(number):
        items = []
        for index in range(args.batch_size):
            invoice = f"BENCH-{number}-{index}"
            case = dict(source, invoice=invoice)
            case["statement_row"] = dict(source["statement_row"], invoice=invoice)
            case["lines"] = [dict(source["lines"][0], id=f"L{i}") for i in range(10)]
            case["statement_row"]["principal"] *= 10
            case["statement_row"]["gst"] *= 10
            case["evidence"] = [
                dict(
                    source["evidence"][0],
                    id=f"POD-{i}",
                    invoice=invoice,
                    line=f"L{i}",
                    attachment=None,
                )
                for i in range(10)
            ]
            case["ledger"] = [
                dict(source["ledger"][0], id=f"PAY-{i}", base=1000) for i in range(100)
            ]
            items.append({"case": case, "expected_revision": 0})
        return json.dumps({"items": items}).encode()

    payloads = [batch(i) for i in range(args.batches)]

    def post(item):
        index, payload = item
        req = Request(
            url + "/v1/decisions",
            data=payload,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Idempotency-Key": str(index),
            },
        )
        with urlopen(req, timeout=60) as res:
            return len(json.load(res))

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(
            os.environ,
            PROOFPAY_API_TOKENS=json.dumps({"benchmark": token}),
            PROOFPAY_JOURNAL=str(Path(tmp) / "test.sqlite3"),
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "proofpay.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "error",
            ],
            env=env,
        )
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("Benchmark server exited.")
                try:
                    with urlopen(url + "/healthz", timeout=1):
                        break
                except OSError:
                    sleep(0.1)
            else:
                raise RuntimeError("Benchmark server failed readiness check.")
            start = perf_counter()
            with ThreadPoolExecutor(args.concurrency) as workers:
                count = sum(workers.map(post, enumerate(payloads)))
            elapsed = perf_counter() - start
            print(
                json.dumps(
                    {
                        "committed_invoices": count,
                        "ledger_postings": count * 100,
                        "seconds": round(elapsed, 3),
                        "invoices_per_second": round(count / elapsed, 1),
                        "concurrent_clients": args.concurrency,
                        "batch_size": args.batch_size,
                    }
                )
            )
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
