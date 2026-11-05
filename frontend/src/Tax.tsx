import { Fragment, useState } from "react";
import type { Invoice, Posting, Split } from "./types";
import { money, days, Pair, PanelTitle } from "./shared";
import { TaxLog } from "./Chain";
function components(split: Split | null, gst: number, sign = 1) {
  return (["cgst", "sgst", "igst"] as const).map((k) => (
    <td key={k} className="num">
      {split ? money(sign * split[k]) : gst ? "Unknown" : money(0)}
    </td>
  ));
}
function Post({ p }: { p: Posting }) {
  const sign = p.kind === "credit" ? -1 : 1;
  return (
    <tr className="subrow">
      <td>
        ↳ {p.id}
        <small>
          {p.kind} · {p.date}
          {p.approved ? "" : " · pending"}
        </small>
      </td>
      <td className="num">
        {p.kind === "payment" ? "—" : money(p.base * sign)}
      </td>
      {components(p.split, p.gst, sign)}
      <td className="num">
        {p.kind === "debit" ? money(p.base + p.gst) : "—"}
      </td>
      <td>{p.approved ? "Approved" : "Pending"}</td>
    </tr>
  );
}
export function Tax({
  rows,
  current,
  choose,
}: {
  rows: Invoice[];
  current: Invoice | undefined;
  choose: (c: Invoice) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <section className="sheet">
        <PanelTitle end={<span>INR · adjusted for approved notes</span>}>
          Tax component register
        </PanelTitle>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                {[
                  "Invoice / buyer",
                  "Base value¹",
                  "CGST",
                  "SGST",
                  "IGST",
                  "Debit notes²",
                  "Debtor ITC Lockout Status",
                ].map((x) => (
                  <th key={x}>{x}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const split = c.LEDGER_SUMMARY.adjusted_tax_split;
                return (
                  <Fragment key={c.invoice}>
                    <tr
                      id={"row-" + c.invoice}
                      className={
                        c.invoice === current?.invoice ? "selected" : ""
                      }
                      onClick={() => choose(c)}
                    >
                      <td>
                        <button
                          className="id"
                          aria-expanded={open === c.invoice}
                          onClick={() => {
                            setOpen(open === c.invoice ? null : c.invoice);
                            choose(c);
                          }}
                        >
                          {open === c.invoice ? "−" : "+"} {c.invoice}
                        </button>
                        <small>{c.buyer}</small>
                      </td>
                      <td className="num">{money(c.matrix.principal)}</td>
                      {(["cgst", "sgst", "igst"] as const).map((k) => (
                        <td key={k} className="num">
                          {split.unallocated ? "Partial · " : ""}
                          {money(split[k])}
                        </td>
                      ))}
                      <td className="num">{money(c.matrix.debit)}</td>
                      <td>
                        <span className={c.itc_review ? "tax-alert" : ""}>
                          {c.itc_review
                            ? "! 180-day review"
                            : "No payment-age flag"}
                        </span>
                      </td>
                    </tr>
                    {open === c.invoice && (
                      <>
                        {c.source.lines.map((l) => (
                          <tr key={l.id} className="subrow">
                            <td>
                              ↳ {l.id}
                              <small>{l.description}</small>
                            </td>
                            <td>{money(l.principal)}</td>
                            {components(l.split, l.gst)}
                            <td>—</td>
                            <td>Invoice line</td>
                          </tr>
                        ))}
                        {c.source.ledger.map((p) => (
                          <Post key={p.id} p={p} />
                        ))}
                      </>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="footnote">
          ¹ Original taxable base. ² Tax-inclusive approved debit notes. Expand
          an invoice for individual postings.
        </p>
      </section>
      {current && (
        <div className="split below">
          <section className="sheet">
            <PanelTitle end={<span>{current.invoice}</span>}>
              Statement comparison
            </PanelTitle>
            <TaxLog c={current} />
          </section>
          <section className="sheet">
            <PanelTitle>ITC review record</PanelTitle>
            <dl>
              <Pair label="Invoice age">
                {days(current.as_of, current.source.issued)} days
              </Pair>
              <Pair label="Unallocated GST">
                {money(current.LEDGER_SUMMARY.adjusted_tax_split.unallocated)}
              </Pair>
              <Pair label="GSTIN / master">
                {current.master_match ? "Matched" : "Review required"}
              </Pair>
              <Pair label="Determination">
                {current.itc_review
                  ? "Tax reviewer required"
                  : "No automatic determination"}
              </Pair>
            </dl>
            <p className="footnote">
              The payment-age flag opens a review. Final credit eligibility
              requires the recipient’s tax records.
            </p>
          </section>
        </div>
      )}
    </>
  );
}
