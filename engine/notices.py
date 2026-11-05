from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def render_notice(report):
    if not report["draft"]:
        raise ValueError("Evidence or account state precludes a notice.")
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#123e40")
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=23*mm, rightMargin=23*mm,
                            title="ProofPay | Payment reconciliation")
    content = [Paragraph("Payment reconciliation",styles["Title"]),
               Paragraph(f"Prepared for review | {escape(report['invoice'])} | {report['as_of']}",styles["Normal"]),
               Spacer(1,8*mm)]
    ledger = report["LEDGER_SUMMARY"]
    estimate = ledger["interest_estimate"]["amount"]
    def money(value):
        return f"INR {value // 100:,}.{value % 100:02d}" if value is not None else "Under review"
    rows = [["Open invoice amount", money(ledger["total_owed"])],
            ["Estimated interest (separate)", money(estimate)],
            ["Effective due date", ledger["effective_due"]]]
    table = Table(rows,colWidths=[85*mm,65*mm],hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#edf3ef")),
                               ("ALIGN",(1,0),(1,-1),"RIGHT"),("TOPPADDING",(0,0),(-1,-1),7),
                               ("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    content.extend([table,Spacer(1,6*mm)])
    for paragraph in report["draft"].split("\n\n"):
        content.extend([Paragraph(escape(paragraph).replace("\n","<br/>"),styles["BodyText"]),Spacer(1,3*mm)])
    doc.build(content)
    return output.getvalue()
