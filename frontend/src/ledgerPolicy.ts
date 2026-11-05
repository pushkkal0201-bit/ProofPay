import { days } from "./shared";
import type { Invoice } from "./types";

export function liability(c: Invoice) {
  const terms = c.source.terms;
  if (
    !terms?.acceptance ||
    !c.statutory_clock.eligible ||
    c.collectible <= 0 ||
    c.dpd <= 0
  )
    return null;
  const age = days(c.as_of, terms.acceptance);
  const estimate = c.LEDGER_SUMMARY.interest_estimate;
  const applicable = terms.rates.filter((r) => r.effective <= c.as_of).at(-1);
  return {
    age,
    beyondCeiling: age > 45,
    interest: estimate.amount,
    rate: applicable ? (applicable.bank_rate_bps * 3) / 100 : null,
  };
}

export function billingTax(c: Invoice) {
  const lines = c.source.lines;
  if (lines.some((line) => line.gst > 0 && !line.split)) return null;
  return (["cgst", "sgst", "igst"] as const).map((k) =>
    lines.reduce((sum, line) => sum + (line.split?.[k] ?? 0), 0),
  );
}
