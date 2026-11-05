from datetime import date, timedelta
from decimal import Decimal
import json
import unittest
from engine.accrual import effective_due, estimate, rounded
from engine.intake import CashReceipt, match_statement, parse_record, reconcile_batch, review_profile
from engine.notices import render_notice
from engine.policy import Terms
from proofpay.__main__ import ROOT
from proofpay.models import Case
from proofpay.engine import analyze

DATA = ROOT/'tests'/'data'


def case():
    return Case.model_validate_json((ROOT/'examples'/'PP-1047.json').read_bytes())


class StatutoryTests(unittest.TestCase):
    def test_cap_and_default_clock(self):
        c=case()
        self.assertEqual(effective_due(c),date(2026,10,11))
        c.terms.written_agreement=False
        self.assertEqual(effective_due(c),date(2026,9,11))
        c.terms.written_agreement=True
        c.due=date(2026,9,1)
        self.assertEqual(effective_due(c),c.due)

    def test_interest_clock_and_tiers(self):
        c=case();due=effective_due(c);c.ledger=[]
        for days,tier in [(0,"Current"),(1,"Reminder"),(30,"Reminder"),(31,"Reconciliation"),
                          (45,"Reconciliation"),(46,"MSE legal review"),(90,"MSE legal review"),(91,"MSE legal review")]:
            c.as_of=due+timedelta(days=days);r=analyze(c)
            self.assertEqual(r['state'],tier)
            if days==1:
                self.assertEqual(r['LEDGER_SUMMARY']['interest_estimate']['amount'],rounded(Decimal(17700000)*18/36500))
        self.assertIn('section 18',r['draft'])

    def test_month_rest_rate_change_and_payment(self):
        c=case();due=effective_due(c)
        r=estimate(c,due)
        oct_interest=Decimal(17110000)*18*20/36500
        nov_interest=((17110000+oct_interest)*11+(13110000+oct_interest)*19)*18/36500
        dec_interest=(13110000+oct_interest+nov_interest)*Decimal('16.5')*15/36500
        self.assertEqual(r['amount'],rounded(oct_interest+nov_interest+dec_interest))
        self.assertEqual([s['annual_bps'] for s in r['audit']],[1800,1800,1800,1650])

    def test_missing_rate_and_evidence_hold(self):
        c=case();c.terms.rates=[]
        r=analyze(c);self.assertIsNone(r['LEDGER_SUMMARY']['interest_estimate']['amount'])
        self.assertIsNone(r['COMMUNICATIONS_DRAFT']['email'])
        c=case();c.evidence[0].kind='eway'
        self.assertIsNone(analyze(c)['draft'])

    def test_contract_simple_interest(self):
        c=case();c.terms=Terms(basis="contract",annual_bps=1200,authority_ref="Clause 5");c.ledger=[]
        r=analyze(c);days=(c.as_of-c.due).days
        self.assertEqual(r['LEDGER_SUMMARY']['interest_estimate']['amount'],rounded(Decimal(17700000)*12*days/36500))
        self.assertEqual(r['balance'],17700000)

    def test_wrong_tax_split(self):
        c=case()
        c.statement_row.split=c.statement_row.split.model_copy(update=dict(igst=2700000,cgst=0,sgst=0))
        self.assertEqual(analyze(c)['statement'],'Mismatch')
        summary=analyze(c)['LEDGER_SUMMARY']
        self.assertEqual(summary['adjusted_tax_split']['sgst'],1305000)


class AdapterTests(unittest.TestCase):
    def test_cash_allocations_replay_and_residual(self):
        data=json.loads((DATA/'portfolio.json').read_text())
        cases=[Case.model_validate(c) for c in data['cases']]
        payments=[CashReceipt.model_validate(r) for r in data['payments']]
        updated,unapplied=reconcile_batch(cases,payments)
        self.assertEqual(unapplied,{'BANK-14':100000})
        self.assertEqual(reconcile_batch(updated,payments)[0],updated)
        self.assertEqual(analyze(updated[0])['balance'],12410000)
        payments[0].allocations[0].amount-=1
        with self.assertRaises(ValueError):reconcile_batch(updated,payments)
        payments[0].buyer_gstin='wrong'
        with self.assertRaises(ValueError):reconcile_batch(cases,payments)

    def test_statement_scope_and_duplicates(self):
        text=(DATA/'statement.csv').read_text()
        c=case()
        self.assertEqual(analyze(match_statement([c],text)[0])['statement'],'Matched')
        self.assertIsNone(match_statement([c],text.splitlines()[0])[0].statement_row)
        with self.assertRaises(ValueError):match_statement([c],text+text.splitlines()[1])

    def test_candidate_and_compact_hold(self):
        text=(DATA/'receipt.txt').read_text()
        result=parse_record(text)
        self.assertEqual(result['fields']['timestamp'],'2026-08-27T11:30:00+05:30')
        self.assertFalse(result['verified'])
        self.assertIn('Ambiguous invoice',parse_record(text+'Invoice: OTHER')['issues'])
        report=review_profile(json.loads((DATA/'profile.json').read_text()))
        self.assertEqual(report['LEDGER_SUMMARY']['unverified_balance'],16700000)
        self.assertIsNone(report['COMMUNICATIONS_DRAFT']['email'])

    def test_channels_and_blocked_pdf(self):
        c=case();r=analyze(c)
        self.assertTrue(render_notice(r).startswith(b'%PDF'))
        self.assertIn('POD-817',r['COMMUNICATIONS_DRAFT']['whatsapp'])
        c.contact.whatsapp_opt_in=False
        self.assertIsNone(analyze(c)['COMMUNICATIONS_DRAFT']['whatsapp'])
        c.contact.contact_paused=True
        self.assertIsNone(analyze(c)['draft'])
        c.evidence=[]
        with self.assertRaises(ValueError):render_notice(analyze(c))


class PortfolioWriteTests(unittest.TestCase):
    def test_idempotency_and_rollback(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from proofpay.__main__ import init_db, snapshot, review_key
        from engine.intake import post_portfolio, VersionConflict
        source=json.loads((DATA/'portfolio.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'books.db';init_db(path)
            with sqlite3.connect(path) as db:
                d=Case.model_validate(source['cases'][1])
                db.execute("INSERT INTO cases VALUES (?,?)",(d.invoice,snapshot(d)))
            def versions(db):
                return {k:review_key(raw,analyze(Case.model_validate_json(raw))) for k,raw in
                        db.execute("SELECT id,data FROM cases WHERE id IN ('PP-1047','PP-1048')")}
            def post(body):
                with sqlite3.connect(path) as db:
                    return post_portfolio(db,body,analyze,snapshot,review_key)
            with sqlite3.connect(path) as db: initial=versions(db)
            body=dict(versions=initial,payments=source['payments'])
            with self.assertRaises(ValueError):post(dict(body,statement_csv="broken"))
            with sqlite3.connect(path) as db:
                self.assertEqual(versions(db),initial)
                self.assertEqual(db.execute("SELECT count(*) FROM cash_receipts").fetchone()[0],0)
            self.assertEqual(len(post(body)['changed']),2)
            with self.assertRaises(VersionConflict):post(body)
            with sqlite3.connect(path) as db:body['versions']=versions(db)
            self.assertEqual(post(body)['changed'],[])
            body['payments'][0]['received']+=1
            with self.assertRaises(VersionConflict):post(body)


class ProviderTests(unittest.TestCase):
    def test_openai_json_response_boundary(self):
        import os
        from unittest.mock import patch
        from proofpay.agent import ask_model
        with patch.dict(os.environ,{"PROOFPAY_PROVIDER":"openai","ENGINE_API_KEY":"test-only"}), patch("proofpay.agent.urlopen") as call:
            call.return_value.__enter__.return_value.read.return_value=json.dumps({
                "choices":[{"message":{"content":json.dumps({"tool":"read_gst"})}}]}).encode()
            self.assertEqual(ask_model("fixture",[]),{"tool":"read_gst"})
            req=call.call_args.args[0]
            self.assertEqual(req.full_url,"https://api.openai.com/v1/chat/completions")
            self.assertFalse(json.loads(req.data)["store"])

    def test_attached_quantity_conflict(self):
        c=case();c.evidence[0].quantity=3
        r=analyze(c)
        self.assertIsNone(r["draft"])
        self.assertIn("conflict",r["proof"][0]["gaps"][0])
