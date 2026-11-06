import { useEffect, useRef, useState } from "react";
import { money, PanelTitle, request } from "./shared";
import type { Invoice } from "./types";

interface Configuration {
  model: string | null;
  provider: string;
  configured: boolean;
}
interface Investigation {
  invoice: string;
  review_key: string;
  mode: string;
  provider: string;
  task: string;
  inspections: { tool: string; result: unknown }[];
}
const labels: Record<string, string> = {
  read_evidence: "Delivery evidence",
  read_ledger: "Financial ledger",
  read_gst: "Tax records",
};


interface EvidenceLine {
  line: string;
  description: string;
  clause: string;
  gaps: string[];
  references: string[];
  milestones: { milestone: string; required: boolean; result: string; evidence_ids: string[] }[];
  submitted_records: { id: string; kind: string; quantity: number | null; verified: boolean; timestamp: string }[];
}
interface LedgerView {
  currency: string;
  unit: string;
  original_principal: number;
  original_gst: number;
  credits: number;
  debits: number;
  payments: number;
  total_owed: number;
  effective_due: string;
  contract_due: string;
  dpd: number;
  bucket: string;
  interest_estimate: { amount: number | null; status: string; authority: string };
}
interface TaxView {
  master_match: boolean;
  statement: string;
  itc_review: boolean;
  adjusted_split: { cgst: number; sgst: number; igst: number; unallocated?: number };
}
interface Inspection {
  tool: string;
  result: unknown;
}
function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}
function evidenceLines(value: unknown): EvidenceLine[] {
  return Array.isArray(value) ? value as EvidenceLine[] : [];
}
function DisplayInspection({ step }: { step: Inspection }) {
  if (step.tool === "read_evidence") {
    return <div className="review-records">{evidenceLines(step.result).map(line => <section className="review-block" key={line.line}>
      <h3>{line.line} · {line.description}</h3>
      <p className="footnote">Contract reference · {line.clause}</p>
      <div className="scroll"><table className="review-table"><thead><tr><th>Reference</th><th>Type</th><th>Accepted qty</th><th>Reviewed</th><th>Timestamp</th></tr></thead><tbody>
        {line.submitted_records.map(record => <tr key={record.id}><td className="id">{record.id}</td><td>{record.kind}</td><td>{record.quantity ?? "—"}</td><td>{record.verified ? "Verified" : "Unverified"}</td><td>{record.timestamp}</td></tr>)}
      </tbody></table></div>
      <h4>Milestone checks</h4>
      <div className="scroll"><table className="review-table"><thead><tr><th>Milestone</th><th>Required</th><th>Result</th><th>Evidence</th></tr></thead><tbody>
        {line.milestones.map(item => <tr key={item.milestone}><td>{item.milestone.replaceAll("_", " ")}</td><td>{item.required ? "Yes" : "No"}</td><td>{item.result.toUpperCase()}</td><td>{item.evidence_ids.join(", ") || "—"}</td></tr>)}
      </tbody></table></div>
      {line.gaps.length > 0 && <p className="hold">Open checks · {line.gaps.join("; ")}</p>}
    </section>)}</div>;
  }
  if (step.tool === "read_ledger") {
    const ledger = objectValue(step.result) as unknown as LedgerView;
    const rows: [string, number][] = [
      ["Invoice principal", ledger.original_principal], ["Invoice tax", ledger.original_gst],
      ["Approved debits", ledger.debits], ["Approved credits", ledger.credits],
      ["Payments received", ledger.payments], ["Net outstanding", ledger.total_owed],
    ];
    return <div className="review-records"><dl className="review-fields">{rows.map(([label, amount]) => <div key={label}><dt>{label}</dt><dd>{money(amount)}</dd></div>)}</dl>
      <dl className="review-fields"><div><dt>Effective due</dt><dd>{ledger.effective_due}</dd></div><div><dt>Contract due</dt><dd>{ledger.contract_due}</dd></div><div><dt>Age</dt><dd>{ledger.dpd} days · {ledger.bucket}</dd></div><div><dt>Interest estimate</dt><dd>{ledger.interest_estimate?.amount == null ? ledger.interest_estimate?.status : money(ledger.interest_estimate.amount)}</dd></div><div><dt>Rate source</dt><dd>{ledger.interest_estimate?.authority ?? "Not supplied"}</dd></div></dl></div>;
  }
  if (step.tool === "read_gst") {
    const tax = objectValue(step.result) as unknown as TaxView;
    const split = tax.adjusted_split ?? {cgst:0,sgst:0,igst:0};
    return <dl className="review-fields"><div><dt>Account master</dt><dd>{tax.master_match ? "Matched" : "Review required"}</dd></div><div><dt>GSTR-2B statement</dt><dd>{tax.statement}</dd></div><div><dt>ITC age review</dt><dd>{tax.itc_review ? "Review required" : "No age flag"}</dd></div><div><dt>CGST / SGST / IGST</dt><dd>{[split.cgst,split.sgst,split.igst].map(money).join(" / ")}</dd></div>{split.unallocated != null && <div><dt>Unallocated tax</dt><dd>{money(split.unallocated)}</dd></div>}</dl>;
  }
  return <pre className="json">{JSON.stringify(step.result, null, 2)}</pre>;
}

export function Review({ invoice }: { invoice: Invoice }) {
  const [config, setConfig] = useState<Configuration | null>(null);
  const [result, setResult] = useState<Investigation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    request("review-config")
      .then(response => response.json())
      .then((value: Configuration) => { if (mounted.current) setConfig(value); })
      .catch((failure: unknown) => { if (mounted.current) setError(String(failure)); });
    return () => { mounted.current = false; };
  }, []);
  async function investigate() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await request("agent", {
        invoice: invoice.invoice,
        review_key: invoice.review_key,
        require_model: true,
      });
      const value: Investigation = await response.json();
      if (value.review_key !== invoice.review_key) throw new Error("Reload the invoice before reviewing.");
      if (mounted.current) setResult(value);
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return <section className="sheet below" aria-label="Model-assisted review">
    <PanelTitle end={invoice.invoice}>Dispute review</PanelTitle>
    <div className="inset">
      <p className="micro">{config?.configured
        ? `${config.provider} / ${config.model}`
        : "Review model setup required"}</p>
      <p className="footnote">Inspect the buyer’s objection against the ledger, tax record and delivery references.</p>
      {config && !config.configured && <p className="footnote">
        Install Ollama and download a local model, then launch Start-Model-Review.cmd.
        The model runs on your computer. The README includes the setup commands.
      </p>}
      {config?.provider === "openai" && <p className="footnote">
        Running this review sends the objection and selected accounting records to the configured OpenAI model.
      </p>}
      <button className="btn primary" disabled={busy || !config?.configured} onClick={investigate}>
        {busy ? "Reviewing records…" : "Run model review"}
      </button>
      <div role="status" aria-live="polite">
        {busy && <p className="footnote">Waiting for the configured model. A cold start can take a few minutes.</p>}
        {error && <p className="hold">{error}</p>}
        {result && <>
          <p className="below"><strong>{result.task}</strong></p>
          <p className="micro">Proposed review task · {result.mode}</p>
          {result.inspections.map((step, index) => <details key={step.tool}>
            <summary>{index + 1}. {labels[step.tool] ?? step.tool}</summary>
            <DisplayInspection step={step} />
            <details className="review-raw"><summary>Raw record JSON</summary><pre className="json">{JSON.stringify(step.result, null, 2)}</pre></details>
          </details>)}
        </>}
      </div>
    </div>
  </section>;
}
