import { Fragment, useState } from "react";
import { Badge, Pair, PanelTitle, money } from "./shared";
import type { Invoice, LineProof } from "./types";

type Inspect = "Evidence" | "Raw JSON" | "Tax log";
export function Chain({
  rows,
  current,
  choose,
}: {
  rows: Invoice[];
  current: Invoice | undefined;
  choose: (c: Invoice) => void;
}) {
  const [shown, show] = useState(true);
  const select = (c: Invoice) => {
    choose(c);
    show(true);
  };
  const [expanded, expand] = useState<string[]>([]);
  return (
    <div className={shown ? "split" : "block"}>
      <section className="sheet">
        <PanelTitle end={<span>{rows.length} invoices</span>}>
          Fulfillment register
        </PanelTitle>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                {[
                  "Invoice ID",
                  "e-Way bill ID",
                  "Gateway uptime",
                  "Verified signatory",
                  "DPD",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const anchors = c.proof.flatMap((p) => p.anchors);
                const signed = anchors.find((a) => a.signer);
                const telemetry = anchors.find((a) => a.kind === "telemetry");
                return (
                  <Fragment key={c.invoice}>
                    <tr
                      id={"row-" + c.invoice}
                      data-invoice={c.invoice}
                      className={
                        current?.invoice === c.invoice ? "selected" : ""
                      }
                      onClick={() => select(c)}
                    >
                      <td>
                        <div className="flex items-start gap-2">
                          <button
                            aria-label={"Expand lines for " + c.invoice}
                            aria-expanded={expanded.includes(c.invoice)}
                            onClick={(e) => {
                              e.stopPropagation();
                              expand((xs) =>
                                xs.includes(c.invoice)
                                  ? xs.filter((x) => x !== c.invoice)
                                  : [...xs, c.invoice],
                              );
                            }}
                          >
                            {expanded.includes(c.invoice) ? "−" : "+"}
                          </button>
                          <div>
                            <button className="id" onClick={() => select(c)}>
                              {c.invoice}
                            </button>
                            <small>{c.buyer}</small>
                          </div>
                        </div>
                      </td>
                      <td>
                        {anchors.find((a) => a.kind === "eway")?.id ?? "—"}
                      </td>
                      <td>
                        {telemetry?.uptime_bps != null
                          ? (telemetry.uptime_bps / 100).toFixed(2) + "%"
                          : "—"}
                      </td>
                      <td>{signed?.signer?.split(",")[0] ?? "—"}</td>
                      <td className={c.dpd > 45 ? "overdue num" : "num"}>
                        {c.dpd}
                      </td>
                    </tr>
                    {expanded.includes(c.invoice) &&
                      c.proof.map((p) => (
                        <tr className="subrow" key={p.line}>
                          <td colSpan={5}>
                            ↳ {p.line} · {p.description} ·{" "}
                            {p.gaps.length
                              ? p.gaps.join(" ")
                              : p.anchors.map((a) => a.id).join(" / ")}
                          </td>
                        </tr>
                      ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <p className="empty">No invoices match this filter.</p>
        )}
        {current && (
          <section className="line-detail">
            <PanelTitle end={<span>{current.invoice}</span>}>
              Invoice ledger
            </PanelTitle>
            <dl>
              <Pair label="Buyer">{current.buyer}</Pair>
              <Pair label="Issue / effective due">
                {current.source.issued} / {current.due}
              </Pair>
              <Pair label="Open balance">{money(current.balance)}</Pair>
              <Pair label="Decision">
                <Badge item={current} />
              </Pair>
            </dl>
            {current.source.dispute_text && (
              <blockquote>{current.source.dispute_text}</blockquote>
            )}
          </section>
        )}
      </section>
      {shown && current && (
        <Inspector
          key={current.invoice}
          c={current}
          close={() => show(false)}
        />
      )}
    </div>
  );
}
export function TaxLog({ c }: { c: Invoice }) {
  const row = c.source.statement_row;
  const comparisons: [
    string,
    string | number | null,
    string | number | null,
  ][] = row
    ? [
        ["Invoice", c.invoice, row.invoice],
        ["Issue date", c.source.issued, row.issued],
        ["Supplier GSTIN", c.source.supplier_gstin, row.supplier_gstin],
        ["Recipient GSTIN", c.source.gstin, row.recipient_gstin],
        ["Taxable base", c.matrix.principal, row.principal],
        ["GST", c.matrix.gst, row.gst],
      ]
    : [];
  if (row?.split)
    for (const k of ["cgst", "sgst", "igst"] as const)
      comparisons.push([
        k.toUpperCase(),
        c.source.lines.some((l) => l.gst && !l.split)
          ? null
          : c.source.lines.reduce((sum, l) => sum + (l.split?.[k] ?? 0), 0),
        row.split[k],
      ]);
  return (
    <>
      <Pair label="GSTR-2B result">{c.statement}</Pair>
      {!row ? (
        <p className="empty">No statement row supplied for this invoice.</p>
      ) : (
        <div className="scroll">
          <table className="compact">
            <thead>
              <tr>
                <th>Field</th>
                <th>Invoice</th>
                <th>Statement</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map(([l, a, b]) => (
                <tr key={l}>
                  <td>{l}</td>
                  <td>{typeof a === "number" ? money(a) : (a ?? "—")}</td>
                  <td>{typeof b === "number" ? money(b) : b}</td>
                  <td>{a === b ? "Match" : "Mismatch"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
function EvidenceLine({ p }: { p: LineProof }) {
  return (
    <section className="evidence">
      <div className="eyebrow">
        {p.line} / {p.description}
      </div>
      <p className="contract">{p.clause}</p>
      {p.gaps.map((x) => (
        <p className="hold" key={x}>
          {x}
        </p>
      ))}
      {p.anchors.map((a) => (
        <div key={a.id} className="anchor">
          <div className="flex items-center justify-between">
            <b>{a.id}</b>
            <span className="micro">{a.kind}</span>
          </div>
          <dl>
            <Pair label="Timestamp">{a.timestamp}</Pair>
            <Pair label="Signatory">{a.signer ?? "—"}</Pair>
            <Pair label="Reviewed by">{a.reviewer}</Pair>
          </dl>
          {a.crop && (
            <figure>
              <img
                src={"data:image/png;base64," + a.crop.png_base64}
                alt={"Signed delivery note crop for " + a.id}
              />
              <figcaption>{a.crop.origin}</figcaption>
              <details>
                <summary>OCR transcription &amp; image hash</summary>
                <pre>{a.crop.ocr_text}</pre>
                <code>{a.crop.sha256}</code>
              </details>
            </figure>
          )}
          {a.attachment && (
            <details>
              <summary>Source text / SHA-256</summary>
              <pre>{a.attachment.text}</pre>
              <code>{a.attachment.sha256}</code>
            </details>
          )}
        </div>
      ))}
    </section>
  );
}
function Inspector({ c, close }: { c: Invoice; close: () => void }) {
  const [tab, set] = useState<Inspect>("Evidence");
  return (
    <aside className="sheet inspector">
      <div className="pane-heading">
        <div className="flex justify-between items-center">
          <span className="eyebrow">Execution pane</span>
          <button
            className="micro"
            aria-label="Close execution pane"
            onClick={close}
          >
            Close ×
          </button>
        </div>
        <h2>{c.invoice}</h2>
        <p>{c.buyer}</p>
      </div>
      <div className="tabs">
        {(["Evidence", "Raw JSON", "Tax log"] as const).map((t) => (
          <button key={t} aria-pressed={t === tab} onClick={() => set(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Evidence" ? (
        c.proof.map((p) => <EvidenceLine key={p.line} p={p} />)
      ) : tab === "Raw JSON" ? (
        <pre className="json">
          {JSON.stringify(
            {
              review_key: c.review_key,
              source_evidence: c.source.evidence.map((a) => ({
                ...a,
                crop: a.crop
                  ? { sha256: a.crop.sha256, ocr_text: a.crop.ocr_text }
                  : null,
              })),
              reasons: c.reasons,
            },
            null,
            2,
          )}
        </pre>
      ) : (
        <TaxLog c={c} />
      )}
    </aside>
  );
}
