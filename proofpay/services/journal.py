"""Immutable decision versions and idempotent atomic batches in a WAL journal."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime


class Conflict(ValueError):
    pass


def encode(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def stream_id(case):
    return digest([case.creditor, case.invoice])


class Journal:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS decision_versions (
                    stream TEXT NOT NULL, revision INTEGER NOT NULL,
                    assessed_on TEXT NOT NULL, source TEXT NOT NULL, report TEXT NOT NULL,
                    event TEXT NOT NULL, event_hash TEXT NOT NULL,
                    PRIMARY KEY(stream, revision));
                CREATE TABLE IF NOT EXISTS request_replays (
                    actor TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY(actor, request_key));
                CREATE TABLE IF NOT EXISTS draft_exports (
                    id INTEGER PRIMARY KEY, stream TEXT NOT NULL, revision INTEGER NOT NULL,
                    actor TEXT NOT NULL, created TEXT NOT NULL, format TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exported_bytes (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS export_stream_idx ON draft_exports(stream,id);
            """)

    @staticmethod
    def replay(db, actor, key, fingerprint):
        row = db.execute(
            "SELECT fingerprint,result FROM request_replays WHERE actor=? AND request_key=?",
            (actor, key),
        ).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise Conflict("Idempotency key already belongs to a different request.")
        return json.loads(row["result"]) if row else None

    def append(self, actor, key, fingerprint, evaluated):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self.replay(db, actor, key, fingerprint)
            if prior is not None:
                return prior
            results = []
            for item, stream, source, report, input_hash, output_hash in evaluated:
                head = db.execute(
                    """SELECT revision,event_hash,assessed_on FROM decision_versions
                                     WHERE stream=? ORDER BY revision DESC LIMIT 1""",
                    (stream,),
                ).fetchone()
                previous = head["revision"] if head else 0
                as_of = item.case.as_of.isoformat()
                if item.expected_revision != previous or (
                    head and as_of < head["assessed_on"]
                ):
                    raise Conflict(
                        f"Revision or assessment date is stale for {item.case.invoice}."
                    )
                revision = previous + 1
                event = {
                    "stream": stream,
                    "revision": revision,
                    "actor": actor,
                    "request_id": key,
                    "policy_version": "2.0",
                    "created": datetime.now(UTC).isoformat(),
                    "input_sha256": input_hash,
                    "output_sha256": output_hash,
                    "previous": head["event_hash"] if head else None,
                }
                checksum = digest(event)
                db.execute(
                    "INSERT INTO decision_versions VALUES (?,?,?,?,?,?,?)",
                    (stream, revision, as_of, source, report, encode(event), checksum),
                )
                results.append(
                    {
                        "stream": stream,
                        "invoice": item.case.invoice,
                        "revision": revision,
                        "event_sha256": checksum,
                    }
                )
            db.execute(
                "INSERT INTO request_replays VALUES (?,?,?,?)",
                (actor, key, fingerprint, encode(results)),
            )
            return results

    def version(self, stream, revision=None):
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT * FROM decision_versions WHERE stream=? ORDER BY revision DESC LIMIT 1",
                    (stream,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM decision_versions WHERE stream=? AND revision=?",
                    (stream, revision),
                ).fetchone()
        if not row:
            raise KeyError("Unknown invoice stream or revision.")
        with self.connect() as db:
            parent = db.execute(
                "SELECT event_hash FROM decision_versions WHERE stream=? AND revision=?",
                (stream, row["revision"] - 1),
            ).fetchone()
        event = json.loads(row["event"])
        source, report = json.loads(row["source"]), json.loads(row["report"])
        if (
            digest(event) != row["event_hash"]
            or digest(source) != event["input_sha256"]
            or digest(report) != event["output_sha256"]
            or event["stream"] != stream
            or (row["revision"] > 1 and parent is None)
            or event["previous"] != (parent[0] if parent else None)
            or event["revision"] != row["revision"]
        ):
            raise RuntimeError("Decision integrity check failed.")
        return {
            "source": source,
            "report": report,
            "event": event,
            "event_sha256": row["event_hash"],
        }

    def log_export(self, stream, revision, actor, channel, content):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT MAX(revision) FROM decision_versions WHERE stream=?", (stream,)
            ).fetchone()[0]
            if revision != current:
                raise Conflict("The invoice changed; compile the latest revision.")
            checksum = hashlib.sha256(content).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO exported_bytes VALUES (?,?)", (checksum, content)
            )
            cursor = db.execute(
                "INSERT INTO draft_exports(stream,revision,actor,created,format,sha256) VALUES (?,?,?,?,?,?)",
                (
                    stream,
                    revision,
                    actor,
                    datetime.now(UTC).isoformat(),
                    channel,
                    checksum,
                ),
            )
            return cursor.lastrowid
