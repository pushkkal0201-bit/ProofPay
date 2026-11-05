import { Fragment, useState } from "react";
import { Pair, PanelTitle, money } from "./shared";
import { billingTax, liability } from "./ledgerPolicy";
import { Communications } from "./Communications";
import type { Invoice, LineProof } from "./types";
type Inspect = "Evidence" | "Raw JSON" | "Tax log";
interface Props {
  rows: Invoice[];
  current: Invoice | undefined;
  choose: (c: Invoice) => void;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}
function TaxCell({ c }: { c: Invoice }) {
  const split = billingTax(c);
  return (
    <>
      <span>{money(c.matrix.gst)}</span>
      <small>
        {split ? split.map((n) => money(n)).join(" / ") : "Split unreported"}
      </small>
    </>
  );
}
export function Chain({ rows, current, choose, refresh, notify }: Props) {
  const [shown, show] = useState(true),
    [expanded, expand] = useState<string[]>([]);
  function select(c: Invoice) {
    choose(c);
    show(true);
  }
  return (
    <div className={shown && current ? "split audit-split" : "block"}>
      <div className="audit-left">
        <section className="sheet">
          <PanelTitle end={<span>{rows.length} records · INR</span>}>
            Audit Ledger
          </PanelTitle>
          <div className="scroll">
            <table className="audit-grid">
              <thead>
                <tr>
                  {[
                    "Invoice ID",
                    "Customer Entity",
                    "Base Amount",
                    "Tax (CGST/SGST/IGST)",
                    "Net Due",
                    "Aging (DPD)",
                    "Dispute Lock",
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const penalty = liability(c),
                    open = expanded.includes(c.invoice);
                  return (
                    <Fragment key={c.invoice}>
                      <tr
                        id={"row-" + c.invoice}
                        data-invoice={c.invoice}
                        className={[
                          current?.invoice === c.invoice ? "selected" : "",
                          penalty?.beyondCeiling ? "statutory-breach" : "",
                        ].join(" ")}
                        onClick={() => select(c)}
                      >
                        <td>
                          <div className="flex items-center gap-1">
                            <button
                              aria-label={"Expand lines for " + c.invoice}
                              aria-expanded={open}
                              onClick={(e) => {
                                e.stopPropagation();
                                expand((xs) =>
                                  open
                                    ? xs.filter((id) => id !== c.invoice)
                                    : [...xs, c.invoice],
                                );
                              }}
                            >
                              {open ? "−" : "+"}
                            </button>
                            <button className="id" onClick={() => select(c)}>
                              {c.invoice}
                            </button>
                          </div>
                        </td>
                        <td className="buyer">{c.buyer}</td>
                        <td className="num">{money(c.matrix.principal)}</td>
                        <td className="num tax-cell">
                          <TaxCell c={c} />
                        </td>
                        <td className="num net">{money(c.collectible)}</td>
                        <td
                          className={
                            "num " + (penalty?.beyondCeiling ? "overdue" : "")
                          }
                        >
                          {c.dpd}
                        </td>
                        <td>
                          <span className={c.reasons.length ? "lock" : "clear"}>
                            {c.reasons.length ? "Locked" : "Clear"}
                          </span>
                        </td>
                      </tr>
                      {open &&
                        c.proof.map((p) => (
                          <tr className="subrow" key={p.line}>
                            <td colSpan={7}>
                              ↳ {p.line} · {p.description} ·{" "}
                              {p.gaps.join(" ") ||
                                p.anchors.map((a) => a.id).join(" / ")}
                            </td>
                          </tr>
                        ))}
                      {penalty && (
                        <tr
                          className={
                            "liability " +
                            (penalty.beyondCeiling ? "ceiling" : "")
                          }
                        >
                          <td colSpan={7}>
                            <strong>STATUTORY OVERDUE LIAB:</strong> Day{" "}
                            {penalty.age}/45 | Accrued Interest:{" "}
                            {penalty.interest === null
                              ? "Pending rate review"
                              : money(penalty.interest)}
                            {penalty.rate !== null &&
                              " | " + penalty.rate.toFixed(2) + "% p.a."}
                            <small>
                              Section 16, MSMED Act · 3× supplied RBI bank rate
                              · monthly rests · estimate at {c.as_of}
                            </small>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!rows.length && <p className="empty">No matching invoices.</p>}
        </section>
        {current && (
          <Communications
            key={current.review_key}
            c={current}
            refresh={refresh}
            notify={notify}
          />
        )}
      </div>
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
            <Pair label={a.kind === "eway" ? "Transit stamp" : "Timestamp"}>
              {a.timestamp}
            </Pair>
            <Pair label="Signatory">{a.signer ?? "—"}</Pair>
            {a.signature && (
              <Pair label="Verified signature key">{a.signature.key_id}</Pair>
            )}
            <Pair label="Reviewed by">{a.reviewer}</Pair>
          </dl>
          {a.crop && (
            <details>
              <summary>Signed delivery note / OCR</summary>
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
            </details>
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
          <span className="eyebrow">Verification Engine</span>
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
      <section className="tax-status">
        <span className="eyebrow">Tax Match Status</span>
        <strong>
          {c.statement === "Matched"
            ? "MATCHED"
            : c.statement === "Mismatch"
              ? "DISCREPANCY"
              : "UNOBSERVED"}
        </strong>
        <p>
          {c.itc_review
            ? "ITC payment review open"
            : "ITC eligibility unconfirmed"}{" "}
          · {c.source.gstin}
        </p>
      </section>
      <div className="tabs">
        {(["Evidence", "Raw JSON", "Tax log"] as const).map((t) => (
          <button key={t} aria-pressed={t === tab} onClick={() => set(t)}>
            {t === "Evidence" ? "Fulfillment Match" : t}
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
