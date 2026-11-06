import { useEffect, useRef, useState } from "react";
import { PanelTitle, request } from "./shared";
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
            <pre className="json">{JSON.stringify(step.result, null, 2)}</pre>
          </details>)}
        </>}
      </div>
    </div>
  </section>;
}
