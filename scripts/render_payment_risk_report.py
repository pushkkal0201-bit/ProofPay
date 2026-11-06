"""Render a read-only risk evaluation report as a standalone HTML dashboard.

Usage: python scripts/render_payment_risk_report.py report.json report.html
"""
import html
import json
import sys
from pathlib import Path


def render(report: dict) -> str:
    def esc(value):
        return html.escape(str(value), quote=True)

    def metric(value):
        return "Not defined" if value is None else f"{value:.3f}"

    def row(name, key):
        a = report["evaluation"].get(key)
        b = report["prevalence_baseline"].get(key)
        return f"<tr><th scope='row'>{esc(name)}</th><td>{metric(a)}</td><td>{metric(b)}</td></tr>"

    features = "".join(f"<li>{esc(item)}</li>" for item in report["features"])
    limitations = "".join(f"<li>{esc(item)}</li>" for item in report["limitations"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofPay | Payment Risk Research</title>
<style>
:root{{font-family:system-ui,Arial,sans-serif;color:#e9edf6;background:#101824}}
body{{max-width:960px;margin:0 auto;padding:32px 18px;line-height:1.6}}
header{{border-bottom:1px solid #354052;margin-bottom:28px;padding-bottom:18px}}
small{{color:#9faec4}}h1{{margin:0;font-size:2rem}}h2{{font-size:1.2rem}}
section{{background:#192436;border:1px solid #33425b;border-radius:14px;padding:22px;margin:18px 0}}
table{{width:100%;border-collapse:collapse;text-align:left}}th,td{{padding:12px;border-bottom:1px solid #354052}}
td{{font-variant-numeric:tabular-nums}}.notice{{border-left:4px solid #e6b65b;padding-left:14px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px}}.cards p{{flex:1;min-width:170px;background:#23334a;border-radius:10px;padding:16px}}
strong{{display:block;font-size:1.25rem}}
</style></head><body>
<header><small>PROOFPAY / EXPERIMENTAL RESEARCH</small><h1>Payment delay risk evaluation</h1>
<p>Offline, out-of-time holdout comparison. Not a collection decision or compliance determination.</p></header>
<section><h2>Evaluation dataset</h2><div class="cards">
<p>Training invoices<strong>{esc(report["training_rows"])}</strong></p>
<p>Test invoices<strong>{esc(report["test_rows"])}</strong></p>
<p>Training ends<strong>{esc(report["train_end"])}</strong></p>
<p>Test begins<strong>{esc(report["test_start"])}</strong></p></div>
<p>Model: {esc(report["model"])}</p></section>
<section><h2>Model versus prevalence baseline</h2>
<table><thead><tr><th>Metric</th><th>Model</th><th>Baseline</th></tr></thead><tbody>
{row("Brier score (lower is better)", "brier")}
{row("Average precision (higher is better)", "average_precision")}
{row("ROC-AUC (higher is better)", "roc_auc")}
</tbody></table></section>
<section><h2>Issue-time features</h2><ul>{features}</ul></section>
<section><h2>Interpretation and limitations</h2><div class="notice">
<p>Scores are evaluated on historical settled invoices only. The model must not be used for statutory decisions or automated collection.</p>
</div><ul>{limitations}</ul></section></body></html>"""


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/render_payment_risk_report.py report.json report.html")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(render(data), encoding="utf-8")
    print(f"Report written to {sys.argv[2]}")
