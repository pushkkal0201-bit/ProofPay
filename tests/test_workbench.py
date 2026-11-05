import json
import unittest
from email import policy
from email.parser import BytesParser
from pydantic import ValidationError
from engine.workbench import Handoff, Projection, handoff, project
from proofpay.__main__ import ROOT
from proofpay.models import Case
from proofpay.engine import analyze


def fixture(invoice):
    return Case.model_validate_json((ROOT/'examples'/f'PP-{invoice}.json').read_bytes())


class WorkbenchTests(unittest.TestCase):
    def test_simulation_reprices_only_future_days(self):
        case = fixture(1047)
        original = case.model_dump_json()
        params = Projection(invoice=case.invoice,review_key='test',bank_rate_bps=800)
        curve = project(case,params)['points']
        self.assertEqual(len(curve),31)
        self.assertEqual(curve[0]['amount'],analyze(case)['LEDGER_SUMMARY']['interest_estimate']['amount'])
        self.assertGreater(curve[-1]['amount'],curve[1]['amount'])
        self.assertEqual(original,case.model_dump_json())

    def test_edited_channel_body(self):
        report = analyze(fixture(1047))
        body = Handoff(invoice=report['invoice'],review_key='test',channel='email',text='Edited payment request.')
        raw, mime = handoff(report,body)
        self.assertEqual(mime,'message/rfc822')
        self.assertEqual(BytesParser(policy=policy.default).parsebytes(raw).get_content().strip(),body.text)
        raw,_ = handoff(report,body.model_copy(update={'channel':'whatsapp'}))
        self.assertEqual(json.loads(raw)['text']['body'],body.text)
        self.assertTrue(handoff(report,body.model_copy(update={'channel':'pdf'}))[0].startswith(b'%PDF'))

    def test_holds_and_channel_consent(self):
        report = analyze(fixture(1049))
        self.assertTrue(report['itc_review'])
        self.assertEqual(report['statement'],'Mismatch')
        for channel in ('pdf','email','whatsapp'):
            with self.assertRaises(ValueError):
                handoff(report,Handoff(invoice='PP-1049',review_key='test',channel=channel,text='Draft'))
        with self.assertRaises(ValueError):
            handoff(analyze(fixture(1042)),Handoff(invoice='PP-1042',review_key='test',channel='whatsapp',text='Draft'))

    def test_bad_scan_hash(self):
        data = fixture(1047).model_dump()
        data['evidence'][0]['crop']['sha256']='0'*64
        with self.assertRaises(ValidationError):
            Case.model_validate(data)
