"""Versioned FastAPI ingestion and decision API. Run with uvicorn --factory."""

import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, model_validator

from engine.policy import Input
from engine.workbench import Handoff, handoff
from proofpay.engine import analyze
from proofpay.models import Case
from proofpay.services.causal import IST, CausalVerificationService
from proofpay.services.escalation import EscalationEngine
from proofpay.services.journal import Conflict, Journal, digest, encode, stream_id


class WriteItem(Input):
    expected_revision: int = Field(strict=True, ge=0)
    case: Case


class Batch(Input):
    items: list[WriteItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_streams(self):
        ids = [stream_id(item.case) for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("A batch can update an invoice only once.")
        return self


class Compile(Input):
    revision: int = Field(strict=True, ge=1)
    channel: Literal["markdown", "whatsapp", "pdf"]


class BodyLimit:
    """Bound buffered JSON even when a client uses chunked transfer encoding."""

    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        buf = bytearray()
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            chunk = msg.get("body", b"")
            if len(buf) + len(chunk) > self.limit:
                return await JSONResponse({"detail": "Request too large."}, 413)(
                    scope, receive, send
                )
            buf.extend(chunk)
            if not msg.get("more_body"):
                break

        async def replay():
            nonlocal buf
            if buf is None:
                return await receive()
            body, buf = bytes(buf), None
            return {"type": "http.request", "body": body, "more_body": False}

        return await self.app(scope, replay, send)


def create_app(db_path=None, credentials=None, keyring=None):
    """One creditor workspace per deployment. Credentials map operator IDs to secrets."""
    tokens = (
        credentials
        if credentials is not None
        else json.loads(os.getenv("PROOFPAY_API_TOKENS", "{}"))
    )
    if (
        not tokens
        or any(not isinstance(t, str) or len(t) < 32 for t in tokens.values())
        or len(set(tokens.values())) != len(tokens)
    ):
        raise ValueError(
            "Configure distinct bearer credentials of at least 32 characters per operator."
        )
    journal = Journal(db_path or os.getenv("PROOFPAY_JOURNAL", "proofpay-api.sqlite3"))
    trusted = (
        keyring
        if keyring is not None
        else json.loads(os.getenv("PROOFPAY_EVIDENCE_KEYS", "{}"))
    )
    verifier = CausalVerificationService(trusted)

    @asynccontextmanager
    async def lifespan(app):
        journal.initialize()
        yield

    app = FastAPI(title="ProofPay Decision API", version="2.0", lifespan=lifespan)
    app.add_middleware(BodyLimit, limit=4 * 1024 * 1024)
    bearer = HTTPBearer(auto_error=False)

    def operator(auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        supplied = auth.credentials.encode() if auth else b""
        for name, token in tokens.items():
            if hmac.compare_digest(supplied, token.encode()):
                return name
        raise HTTPException(
            401,
            "Valid bearer credential required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(sqlite3.OperationalError)
    async def storage_error(request, exc):
        if getattr(exc, "sqlite_errorname", "") in {"SQLITE_BUSY", "SQLITE_LOCKED"}:
            return JSONResponse(
                {"detail": "Journal busy; retry using the same idempotency key."},
                503,
                headers={"Retry-After": "1"},
            )
        raise exc

    @app.get("/healthz")
    def health():
        return {"status": "ready"}

    @app.post("/v1/decisions", status_code=201)
    def write(
        batch: Batch,
        actor: Annotated[str, Depends(operator)],
        idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    ):
        fingerprint = digest(batch.model_dump(mode="json"))
        with journal.connect() as db:
            replay = journal.replay(db, actor, idempotency_key, fingerprint)
        if replay is not None:
            return replay
        # Expensive evidence and tax work runs outside the SQLite write lock.
        evaluated = []
        for item in batch.items:
            source = item.case.model_dump(mode="json")
            report = analyze(item.case, verifier=verifier)
            evaluated.append(
                (
                    item,
                    stream_id(item.case),
                    encode(source),
                    encode(report),
                    digest(source),
                    digest(report),
                )
            )
        return journal.append(actor, idempotency_key, fingerprint, evaluated)

    def read(stream, revision):
        try:
            return journal.version(stream, revision)
        except KeyError:
            raise HTTPException(404, "Unknown invoice stream or revision.") from None

    @app.get("/v1/decisions/{stream}")
    def decision(
        stream: str,
        actor: Annotated[str, Depends(operator)],
        revision: Annotated[int | None, Query(ge=1)] = None,
    ):
        return read(stream, revision)

    @app.get("/v1/decisions/{stream}/clock")
    def clock(
        stream: str, actor: Annotated[str, Depends(operator)], on: date | None = None
    ):
        version = read(stream, None)
        case = Case.model_validate(version["source"])
        observed = on or datetime.now(IST).date()
        if observed < case.as_of or observed.year > 9900:
            raise HTTPException(
                422,
                "Projection must be on or after the stored assessment, within the supported horizon.",
            )
        snapshot_date = case.as_of
        case.as_of = observed
        due, dpd, bucket, interest, statutory = EscalationEngine.clock(case)
        return {
            "revision": version["event"]["revision"],
            "snapshot_on": snapshot_date,
            "projected_on": observed,
            "assumption": "Recorded principal, postings and published input rates carried forward.",
            "due": due,
            "dpd": dpd,
            "bucket": bucket,
            "statutory": statutory,
            "interest_estimate": interest,
        }

    @app.get("/v1/decisions/{stream}/audit")
    def audit(
        stream: str,
        actor: Annotated[str, Depends(operator)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        with journal.connect() as db:
            rows = db.execute(
                """SELECT event,event_hash FROM decision_versions WHERE stream=? AND revision>?
                                 ORDER BY revision LIMIT ?""",
                (stream, after, limit),
            ).fetchall()
        return [
            {"event": json.loads(r["event"]), "sha256": r["event_hash"]} for r in rows
        ]

    @app.get("/v1/decisions/{stream}/exports")
    def exports(
        stream: str,
        actor: Annotated[str, Depends(operator)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        with journal.connect() as db:
            rows = db.execute(
                """SELECT id,revision,actor,created,format,sha256 FROM draft_exports
                                 WHERE stream=? AND id>? ORDER BY id LIMIT ?""",
                (stream, after, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/v1/decisions/{stream}/exports/{receipt}")
    def archived_export(
        stream: str, receipt: int, actor: Annotated[str, Depends(operator)]
    ):
        with journal.connect() as db:
            row = db.execute(
                """SELECT e.format,e.sha256,b.content FROM draft_exports e
                                JOIN exported_bytes b ON b.sha256=e.sha256
                                WHERE e.stream=? AND e.id=?""",
                (stream, receipt),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Unknown export.")
        if hashlib.sha256(row["content"]).hexdigest() != row["sha256"]:
            raise RuntimeError("Export integrity check failed.")
        mime = {
            "markdown": "text/markdown",
            "whatsapp": "application/json",
            "pdf": "application/pdf",
        }[row["format"]]
        return Response(
            row["content"],
            media_type=mime,
            headers={"X-Content-SHA256": row["sha256"], "Cache-Control": "no-store"},
        )

    @app.post("/v1/decisions/{stream}/communications")
    def compile_draft(
        stream: str, body: Compile, actor: Annotated[str, Depends(operator)]
    ):
        stored = read(stream, body.revision)
        report = stored["report"]
        channels = report["COMMUNICATIONS_DRAFT"]
        text = (
            channels["email"]
            if body.channel == "markdown"
            else (report["draft"] if body.channel == "pdf" else channels["whatsapp"])
        )
        if not text:
            raise HTTPException(409, "Policy holds this invoice or channel.")
        if body.channel == "markdown":
            # Fenced plain-text prevents untrusted invoice text becoming Markdown markup.
            longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
            fence = "`" * max(3, longest + 1)
            payload = (
                f"# Payment reconciliation\n\n{fence}text\n{text}\n{fence}\n"
            ).encode()
            mime = "text/markdown"
        else:
            try:
                payload, mime = handoff(
                    report,
                    Handoff(
                        invoice=report["invoice"],
                        review_key=stored["event_sha256"],
                        channel=body.channel,
                        text=text,
                    ),
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        receipt_id = journal.log_export(
            stream, body.revision, actor, body.channel, payload
        )
        return Response(
            payload,
            media_type=mime,
            headers={
                "X-Export-ID": str(receipt_id),
                "X-Content-SHA256": hashlib.sha256(payload).hexdigest(),
                "Cache-Control": "no-store",
            },
        )

    return app
