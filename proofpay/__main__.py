import argparse
import hashlib
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .models import Case
from .engine import analyze
from .agent import suggest
from engine.intake import VersionConflict, post_portfolio, CashReceipt, match_statement, parse_record, reconcile_batch, review_profile
from engine.notices import render_notice
from engine.workbench import Projection, Handoff, project, handoff

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "proofpay" / "static"


def snapshot(case):
    return case.model_dump_json()


def review_key(raw, report):
    return hashlib.sha256((raw + (report["draft"] or "")).encode()).hexdigest()


def init_db(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS cash_receipts (creditor TEXT, buyer TEXT, ref TEXT, data TEXT, PRIMARY KEY(creditor,buyer,ref))")
        db.execute("CREATE TABLE IF NOT EXISTS history (id TEXT, data TEXT, archived_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("CREATE TABLE IF NOT EXISTS reviews (hash TEXT PRIMARY KEY, reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        for source in sorted((ROOT / "examples").glob("*.json")):
            case = Case.model_validate_json(source.read_bytes())
            db.execute("INSERT OR IGNORE INTO cases VALUES (?,?)", (case.invoice, snapshot(case)))


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, mime="application/json"):
        data = json.dumps(value, ensure_ascii=False).encode() if mime == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}:
            return self.reply(403,{"error":"Use the local application origin."})
        paths = {"/":("index.html","text/html"),"/app.js":("app.js","text/javascript"),
                 "/space-grotesk.ttf":("space-grotesk.ttf","font/ttf"),
                 "/style.css":("style.css","text/css")}
        if self.path in paths:
            name, mime = paths[self.path]
            return self.reply(200, (STATIC/name).read_bytes(), mime)
        if self.path == "/api/schema":
            return self.reply(200, Case.model_json_schema())
        if self.path == "/api/cases":
            with sqlite3.connect(self.server.database) as db:
                results = []
                for row, in db.execute("SELECT data FROM cases ORDER BY id"):
                    case = Case.model_validate_json(row)
                    r = analyze(case)
                    key = review_key(row,r)
                    r.update(review_key=key, reviewed=bool(db.execute("SELECT 1 FROM reviews WHERE hash=?", (key,)).fetchone()), source=case.model_dump(mode="json"))
                    results.append(r)
                return self.reply(200,results)
        self.reply(404, {"error":"Unknown route"})

    def do_POST(self):
        host = self.headers.get("Host","")
        if host not in {f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"} or self.headers.get("Origin", "http://"+host) != "http://"+host:
            return self.reply(403,{"error":"Use the local application origin."})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415,{"error":"Expected JSON."})
        try:
            length = int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 1000000:
                return self.reply(413,{"error":"Expected 1 to 1,000,000 bytes."})
            data = json.loads(self.rfile.read(length))
            if self.path == "/api/parse-proof":
                return self.reply(200,parse_record(data["text"]))
            if self.path == "/api/profile":
                return self.reply(200,review_profile(data))
            with sqlite3.connect(self.server.database) as db:
                if self.path == "/api/portfolio":
                    result = post_portfolio(db, data, analyze, snapshot, review_key)
                    return self.reply_after_commit(db,200,result)
                if self.path == "/api/cases":
                    case = Case.model_validate(data)
                    db.execute("INSERT INTO cases VALUES (?,?)",(case.invoice,snapshot(case)))
                    return self.reply_after_commit(db,201,{"invoice":case.invoice})
                if self.path == "/api/revise":
                    case = Case.model_validate(data["source"])
                    db.execute("BEGIN IMMEDIATE")
                    prior = db.execute("SELECT data FROM cases WHERE id=?", (case.invoice,)).fetchone()
                    if not prior:
                        return self.reply(404,{"error":"Unknown invoice"})
                    old = Case.model_validate_json(prior[0])
                    digest = review_key(prior[0], analyze(old))
                    if digest != data["review_key"] or case.as_of < old.as_of:
                        return self.reply(409,{"error":"Stale revision. Refresh and check the snapshot date."})
                    db.execute("INSERT INTO history(id,data) VALUES (?,?)",(case.invoice, prior[0]))
                    db.execute("UPDATE cases SET data=? WHERE id=?", (snapshot(case),case.invoice))
                    return self.reply_after_commit(db,200,{"invoice":case.invoice})
                if self.path not in ("/api/review","/api/agent","/api/notice","/api/projection","/api/handoff"):
                    return self.reply(404,{"error":"Unknown route"})
                if self.path == "/api/review":
                    db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT data FROM cases WHERE id=?", (data["invoice"],)).fetchone()
                if not row:
                    return self.reply(404,{"error":"Unknown invoice"})
                case = Case.model_validate_json(row[0])
                report = analyze(case)
                if self.path in ("/api/projection","/api/handoff"):
                    if data.get("review_key") != review_key(row[0],report):
                        return self.reply(409,{"error":"Snapshot changed. Reload before continuing."})
                    if self.path == "/api/projection":
                        return self.reply(200,project(case,Projection.model_validate(data)))
                    payload,mime = handoff(report,Handoff.model_validate(data))
                    if mime == "application/json":
                        return self.reply(200,json.loads(payload))
                    return self.reply(200,payload,mime)
                if self.path == "/api/notice":
                    if data["review_key"] != review_key(row[0],report) or not report["draft"]:
                        return self.reply(409,{"error":"A current eligible draft is required."})
                    return self.reply(200,render_notice(report),"application/pdf")
                if self.path == "/api/agent":
                    try:
                        return self.reply(200,suggest(case,report))
                    except (OSError,ValueError,TypeError,KeyError,IndexError):
                        return self.reply(503,{"error":"Inference provider unavailable or invalid response. Case unchanged."})
                key = review_key(row[0],report)
                if not report["draft"] or data["review_key"] != key:
                    return self.reply(409,{"error":"Review requires a current eligible draft."})
                db.execute("INSERT OR IGNORE INTO reviews(hash) VALUES (?)",(key,))
                return self.reply_after_commit(db,200,{"reviewed":True})
        except VersionConflict as err:
            self.reply(409,{"error":str(err)})
        except sqlite3.IntegrityError:
            self.reply(409,{"error":"Invoice already exists. Use the revision workflow."})
        except (ArithmeticError,KeyError,ValueError,TypeError,sqlite3.InterfaceError,sqlite3.ProgrammingError) as err:
            self.reply(400,{"error":str(err)[:1200]})

    def reply_after_commit(self, db, status, value):
        db.commit()
        self.reply(status,value)


def main():
    parser = argparse.ArgumentParser(description="ProofPay local workbench")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--db",default="proofpay.sqlite3")
    parser.add_argument("--analyze",type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--profile",type=Path,help="Triage a compact rupee-denominated profile")
    mode.add_argument("--parse-proof",type=Path,help="Extract candidates from labeled fulfillment text")
    mode.add_argument("--batch",type=Path,help="Reconcile an invoice portfolio and shared cash receipts")
    parser.add_argument("--statement",type=Path,help="Normalized GSTR-2B CSV for the batch scope")
    args = parser.parse_args()
    if args.statement and not args.batch:
        parser.error("--statement requires --batch")
    if args.parse_proof:
        print(json.dumps(parse_record(args.parse_proof.read_text(encoding="utf-8")),indent=2))
        return
    if args.profile:
        print(json.dumps(review_profile(json.loads(args.profile.read_bytes())),indent=2))
        return
    if args.batch:
        data = json.loads(args.batch.read_bytes())
        cases, unmatched = reconcile_batch([Case.model_validate(c) for c in data["cases"]],
                                           [CashReceipt.model_validate(r) for r in data.get("payments",[])])
        if args.statement:
            cases = match_statement(cases,args.statement.read_text(encoding="utf-8-sig"))
        print(json.dumps(dict(reports=[analyze(c) for c in cases],sources=[c.model_dump(mode="json") for c in cases],
                              unapplied_cash=unmatched),indent=2))
        return
    if args.analyze:
        print(json.dumps(analyze(Case.model_validate_json(args.analyze.read_bytes())),indent=2))
        return
    init_db(args.db)
    with ThreadingHTTPServer(("127.0.0.1",args.port), Handler) as server:
        server.database=args.db
        print(f"ProofPay is ready at http://127.0.0.1:{server.server_port}",flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
