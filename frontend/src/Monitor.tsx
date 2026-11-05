import { useEffect, useState } from "react";
import type { Invoice } from "./types";
import { days, money, Pair, PanelTitle, request } from "./shared";
interface Point {
  date: string;
  amount: number;
}
interface Curve {
  points: Point[];
  basis: string;
}
function Calculator({ c }: { c: Invoice }) {
  const terms = c.source.terms!;
  const lastRate = terms.rates.filter((r) => r.effective <= c.as_of).at(-1);
  const [rate, setRate] = useState(
    String((lastRate?.bank_rate_bps ?? 0) / 100),
  );
  const [curve, setCurve] = useState<Curve | null>(null),
    [error, setError] = useState(""),
    [day, setDay] = useState(0),
    [play, setPlay] = useState(false);
  useEffect(() => {
    let active = true;
    setCurve(null);
    setPlay(false);
    setDay(0);
    setError("");
    const bps = Math.round(Number(rate) * 100);
    if (!rate || bps <= 0 || bps > 10000) {
      setError("Enter a bank rate above 0 and up to 100%.");
      return;
    }
    const timer = setTimeout(() => {
      request("projection", {
        invoice: c.invoice,
        review_key: c.review_key,
        bank_rate_bps: bps,
      })
        .then((r) => r.json())
        .then((d: Curve) => {
          if (active) setCurve(d);
        })
        .catch((e: Error) => {
          if (active) setError(e.message);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [c.invoice, c.review_key, rate]);
  useEffect(() => {
    if (!play) return;
    const start = performance.now(),
      initial = day;
    const id = setInterval(() => {
      const v = Math.min(30, initial + (performance.now() - start) / 1000);
      setDay(v);
      if (v === 30) setPlay(false);
    }, 100);
    return () => clearInterval(id);
    // day is the initial playhead. Scrubbing stops playback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [play]);
  const i = Math.floor(day),
    now = curve?.points[i],
    next = curve?.points[Math.min(30, i + 1)],
    amount =
      now && next
        ? Math.round(now.amount + (next.amount - now.amount) * (day - i))
        : null;
  return (
    <section className="sheet">
      <PanelTitle end={<span>What-if / 30 days</span>}>
        Interest calculator
      </PanelTitle>
      <div className="inset">
        <div className="flex justify-between gap-4 items-end">
          <label>
            RBI bank rate (%)
            <input
              className="input narrow"
              type="number"
              step=".01"
              min=".01"
              max="100"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
            />
          </label>
          <div className="text-right">
            <span className="eyebrow">3× annual rate</span>
            <p>{(Number(rate) * 3).toFixed(2)}%</p>
          </div>
        </div>
        <div className="projection">
          <small>Projected interest · {now?.date ?? c.as_of}</small>
          <strong>{amount === null ? "—" : money(amount)}</strong>
        </div>
        <input
          aria-label="Projected days after snapshot"
          type="range"
          min="0"
          max="30"
          step=".1"
          value={day}
          onChange={(e) => {
            setPlay(false);
            setDay(Number(e.target.value));
          }}
        />
        <div className="flex justify-between micro">
          <span>Snapshot</span>
          <span>+30 days</span>
        </div>
        <button
          className="btn below"
          disabled={!curve}
          onClick={() => {
            if (day >= 30) setDay(0);
            setPlay(!play);
          }}
        >
          {play ? "Pause projection" : "Play · 1 day / sec"}
        </button>
        <p className="footnote">
          Scenario assumes no future postings. Monthly rests use the backend
          schedule; fractions of a day interpolate between daily estimates.
        </p>
        {error && <p role="alert">{error}</p>}
      </div>
    </section>
  );
}
export function Monitor({
  c,
  rows,
  choose,
}: {
  c: Invoice | undefined;
  rows: Invoice[];
  choose: (c: Invoice) => void;
}) {
  const eligible = rows.filter((r) => r.source.terms?.basis === "msmed");
  if (!c || c.source.terms?.basis !== "msmed")
    return (
      <section className="sheet">
        <PanelTitle>Statutory monitor</PanelTitle>
        <div className="inset">
          <p>{c?.invoice ?? "Selected invoice"} has no reviewed MSE terms.</p>
          {eligible.map((r) => (
            <button
              className="btn below"
              key={r.invoice}
              onClick={() => choose(r)}
            >
              Inspect {r.invoice} →
            </button>
          ))}
        </div>
      </section>
    );
  const t = c.source.terms,
    accept = t.acceptance!,
    span = days(c.due, accept),
    elapsed = days(c.as_of, accept),
    remain = days(c.due, c.as_of);
  return (
    <div className="split">
      <section className="sheet">
        <PanelTitle end={<span>{c.invoice}</span>}>
          Statutory deadline
        </PanelTitle>
        <div className="inset">
          <div className={"countdown " + (c.dpd > 45 ? "overdue" : "")}>
            {Math.abs(remain)}
            <span>days {remain < 0 ? "overdue" : "remaining"}</span>
          </div>
          <div
            className="ruler"
            style={
              {
                "--elapsed":
                  Math.max(
                    0,
                    Math.min(100, (elapsed / Math.max(1, span)) * 100),
                  ) + "%",
              } as React.CSSProperties
            }
          />
          <div className="flex justify-between micro">
            <span>Acceptance · {accept}</span>
            <span>Due · {c.due}</span>
          </div>
        </div>
        <dl>
          <Pair label="Supplier class">{t.supplier_class}</Pair>
          <Pair label="Agreement">
            {t.written_agreement
              ? "Written · 45-day ceiling"
              : "No written agreement · 15-day window"}
          </Pair>
          <Pair label="Effective term">{span} days</Pair>
          <Pair label="Contract due">{c.source.due}</Pair>
          <Pair label="Authority">{t.authority_ref}</Pair>
          <Pair label="Snapshot">{c.as_of}</Pair>
        </dl>
        <PanelTitle>Accrual periods</PanelTitle>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>From / through</th>
                <th>Open balance</th>
                <th>Annual rate</th>
              </tr>
            </thead>
            <tbody>
              {c.LEDGER_SUMMARY.interest_estimate.audit.map((a) => (
                <tr key={a.start}>
                  <td>
                    {a.start}
                    <small>{a.end}</small>
                  </td>
                  <td>{money(a.balance)}</td>
                  <td>{a.annual_bps / 100}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Calculator key={c.review_key} c={c} />
    </div>
  );
}
