import json
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from pydantic import ValidationError
from proofpay.__main__ import Handler, ROOT, init_db
from proofpay.agent import suggest
from proofpay.engine import analyze
from proofpay.models import Case


def fixture(number=1042):
    return Case.model_validate_json((ROOT / f"examples/PP-{number}.json").read_bytes())


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.c = fixture()

    def test_financial_matrix(self):
        r = analyze(self.c)
        self.assertEqual((r['balance'],r['dpd'],r['statement']), (13110000,41,'Matched'))
        self.assertIn('POD-817',r['draft'])
        self.assertIn('2026-11-07',r['draft'])

    def test_age_boundaries(self):
        for dpd, bucket in [(0,'Current'),(1,'1–30'),(30,'1–30'),(31,'31–45'),(45,'31–45'),(46,'46–90'),
                            (60,'46–90'),(61,'46–90'),(90,'46–90'),(91,'91+')]:
            with self.subTest(dpd=dpd):
                self.c.due=self.c.as_of-timedelta(days=dpd)
                self.assertEqual(analyze(self.c)['bucket'],bucket)

    def test_note_sign_and_pending(self):
        note=self.c.ledger[1];note.kind='debit'
        self.assertEqual(analyze(self.c)['balance'],14290000)
        note.approved=False
        r=analyze(self.c)
        self.assertEqual((r['balance'],r['draft']),(13700000,None))

    def test_evidence_scope(self):
        for key,value in [('quantity',1),('invoice','OTHER'),('line','L9'),('signer',None),('verified',False)]:
            with self.subTest(key=key):
                c=fixture(); setattr(c.evidence[0],key,value)
                self.assertIsNone(analyze(c)['draft'])

    def test_performance_complaint_needs_review(self):
        c=fixture(1046)
        p=analyze(c)['proof'][0]
        self.assertEqual(len(p['anchors']),2)
        self.assertTrue(p['gaps'])
        c.dispute='none';c.evidence[1].uptime_bps=9989
        self.assertIsNone(analyze(c)['draft'])

    def test_master_and_statement_conflicts(self):
        self.c.master_name='Different'
        self.assertIsNone(analyze(self.c)['draft'])
        c=fixture();c.statement_row.gst-=1
        self.assertEqual(analyze(c)['state'],'Review hold')

    def test_itc_separate_clock(self):
        self.c.as_of=self.c.issued+timedelta(days=180)
        self.c.due=self.c.as_of
        self.assertTrue(analyze(self.c)['itc_review'])
        self.c.reverse_charge=True
        self.assertFalse(analyze(self.c)['itc_review'])

    def test_credit_and_settlement(self):
        self.c.ledger[0].base+=13110000
        self.assertEqual(analyze(self.c)['state'],'Settled')
        self.c.ledger[0].base+=1
        self.assertEqual(analyze(self.c)['collectible'],0)
        self.assertEqual(analyze(self.c)['state'],'Credit balance')

    def test_invalid_snapshot(self):
        for change in ('duplicates','float','future','negative'):
            d=fixture().model_dump()
            if change=='duplicates': d['ledger']*=2
            if change=='float': d['lines'][0]['principal']=1.5
            if change=='future': d['ledger'][0]['date']='2029-01-01'
            if change=='negative': d['lines'][0]['gst']=-1
            with self.assertRaises(ValidationError): Case.model_validate(d)

    def test_model_cannot_invent_actions(self):
        with patch.dict(os.environ,{'PROOFPAY_MODEL':'demo'}), patch('proofpay.agent.ask_model',return_value={"task":"review_draft"}):
            result=suggest(self.c,analyze(self.c))
            self.assertEqual(result["task"],"Review the proposed wording and deadline.")
            self.assertEqual(len(result["inspections"]),3)
            with self.assertRaises(ValueError):
                suggest(fixture(1043),analyze(fixture(1043)))

    def test_corrupted_attachment(self):
        self.c.evidence[0].attachment.text += "altered"
        r=analyze(self.c)
        self.assertIsNone(r["draft"])
        self.assertIn("checksum", r["proof"][0]["gaps"][0])

    def test_agent_rejects_unknown_task(self):
        with patch.dict(os.environ,{'PROOFPAY_MODEL':'demo'}), patch('proofpay.agent.ask_model',return_value={"task":"send_payment_demand"}):
            with self.assertRaises(ValueError): suggest(self.c,analyze(self.c))



class ApiTests(unittest.TestCase):
    def test_case_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=str(Path(tmp)/'test.db');init_db(db)
            with ThreadingHTTPServer(('127.0.0.1',0),Handler) as srv:
                srv.database=db
                thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{srv.server_port}'
                def post(path,data,origin=None):
                    hdr={'Content-Type':'application/json'}
                    if origin:hdr['Origin']=origin
                    with urlopen(Request(base+path,data=json.dumps(data).encode(),headers=hdr)) as r:
                        return json.load(r)
                try:
                    for route in ['/','/style.css','/app.js','/api/schema']:
                        with urlopen(base+route) as r:self.assertEqual(r.status,200)
                    with urlopen(base+'/api/cases') as r: cases=json.load(r)
                    self.assertEqual(len(cases),7)
                    r=cases[0]; payload=dict(invoice=r['invoice'],review_key=r['review_key'])
                    self.assertTrue(post('/api/review',payload)['reviewed'])
                    self.assertTrue(post('/api/review',payload)['reviewed'])
                    with self.assertRaises(HTTPError) as stale:post('/api/review',{**payload,'review_key':'old'})
                    self.assertEqual(stale.exception.code,409)
                    with self.assertRaises(HTTPError) as origin:post('/api/review',payload,'https://example.com')
                    self.assertEqual(origin.exception.code,403)
                    revision=dict(r['source'],dispute='other')
                    post('/api/revise',dict(source=revision,review_key=r['review_key']))
                    with self.assertRaises(HTTPError) as conflict:
                        post('/api/revise',dict(source=revision,review_key=r['review_key']))
                    self.assertEqual(conflict.exception.code,409)
                    with urlopen(base+'/api/cases') as resp:
                        modified=json.load(resp)[0]
                    self.assertFalse(modified['reviewed'])
                    self.assertIsNone(modified['draft'])
                    d=r['source'];d['invoice']='NEW'
                    self.assertEqual(post('/api/cases',d)['invoice'],'NEW')
                    with self.assertRaises(HTTPError) as dup:post('/api/cases',d)
                    self.assertEqual(dup.exception.code,409)
                finally:
                    srv.shutdown();thread.join()
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],1)
