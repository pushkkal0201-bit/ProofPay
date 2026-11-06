import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { liability } from "./ledgerPolicy";
import { Chain } from "./Chain";
import { Tax } from "./Tax";
import { Monitor } from "./Monitor";
import { Review } from "./Review";
import { Communications } from "./Communications";
import { download, Glyph, money, request } from "./shared";
import type { Invoice, View } from "./types";

const modes: { id: View; name: string; title: string }[] = [
  { id: "chain", name: "Audit Ledger", title: "Receivables & disputes" },
  { id: "tax", name: "Tax ledger", title: "ITC & tax ledger" },
  { id: "msme", name: "Statutory monitor", title: "MSME statutory monitor" },
  { id: "comms", name: "Dispatch", title: "Resolution & dispatch" },
];
function workspaceFromUrl(): View {
  return modes.find(mode => mode.id === window.location.hash.slice(1))?.id ?? "chain";
}
function App() {
  const [data, load] = useState<Invoice[]>([]),
    [selected, select] = useState("PP-1047"),
    [view, setView] = useState<View>(workspaceFromUrl),
    [search, filter] = useState(""),
    [message, notify] = useState(""),
    [loading, wait] = useState(true);
  const [scope, setScope] = useState("All invoices");
  const input = useRef<HTMLInputElement>(null),
    upload = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const sync = () => setView(workspaceFromUrl());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const refresh = useCallback(async () => {
    const result: Invoice[] = await (await request("cases")).json();
    load(result);
  }, []);
  useEffect(() => {
    refresh()
      .catch((e) => notify(String(e)))
      .finally(() => wait(false));
  }, [refresh]);
  const rows = data.filter(
    (c) =>
      (c.invoice + " " + c.buyer)
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (scope === "All invoices" ||
        (scope === "On hold"
          ? c.state === "Review hold"
          : liability(c)?.beyondCeiling)),
  );
  const current = rows.find((c) => c.invoice === selected) ?? rows[0],
    mode = modes.find((m) => m.id === view)!;
  const choose = (c: Invoice) => select(c.invoice);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (e.ctrlKey || e.altKey || e.metaKey || e.isComposing) return;
      const el = e.target as HTMLElement;
      if (el.closest('input,textarea,select,[contenteditable="true"]')) {
        if (e.key === "Escape") el.blur();
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        input.current?.focus();
        return;
      }
      const m = modes.find((_, i) => String(i + 1) === e.key);
      if (m) {
        e.preventDefault();
        window.location.hash = m.id;
        return;
      }
      if (!current) return;
      if (["j", "k", "ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        const ix = rows.findIndex((c) => c.invoice === current.invoice),
          step = e.key === "j" || e.key === "ArrowDown" ? 1 : -1;
        const next = rows[Math.max(0, Math.min(rows.length - 1, ix + step))];
        if (next) {
          select(next.invoice);
          const row = document.getElementById("row-" + next.invoice);
          row?.scrollIntoView({ block: "nearest" });
          row
            ?.querySelector<HTMLButtonElement>("button.id")
            ?.focus({ preventScroll: true });
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [current, rows]);
  async function importFile(file?: File) {
    if (!file) return;
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (
        !parsed ||
        typeof parsed !== "object" ||
        !("invoice" in parsed) ||
        typeof parsed.invoice !== "string"
      )
        throw Error("Expected an invoice source JSON.");
      const prior = data.find((c) => c.invoice === parsed.invoice);
      if (
        prior &&
        !window.confirm("Archive and replace " + prior.invoice + "?")
      )
        return;
      await request(
        prior ? "revise" : "cases",
        prior ? { source: parsed, review_key: prior.review_key } : parsed,
      );
      await refresh();
      select(parsed.invoice);
      filter("");
      setScope("All invoices");
      notify("Imported " + parsed.invoice);
    } catch (e) {
      notify(String(e));
    } finally {
      if (upload.current) upload.current.value = "";
    }
  }
  return (
    <>
      <header className="mast">
        <a className="brand" href="/" aria-label="ProofPay home">
          <Glyph type="brand" />
          ProofPay
        </a>
        <span className="mast-divider">/</span>
        <span className="mast-text">Receivables operations</span>
        <div className="ml-auto flex items-center gap-3">
          <span className="env">Local workspace</span>
          <span className="mono micro">INR</span>
        </div>
      </header>
      <nav className="nav" aria-label="Workbench screens">
        {modes.map((m, i) => (
          <button
            key={m.id}
            aria-current={view === m.id ? "page" : undefined}
            onClick={() => window.location.hash = m.id}
          >
            {m.name}
            <kbd>{i + 1}</kbd>
          </button>
        ))}
      </nav>
      <main>
        <div className="page-head">
          <div>
            <h1>{mode.title}</h1>
          </div>
          <div className="flex gap-2">
            <button className="btn" onClick={() => upload.current?.click()}>
              Import invoice
            </button>
            <input
              aria-label="Invoice JSON file"
              type="file"
              ref={upload}
              hidden
              accept="application/json,.json"
              onChange={(e) => importFile(e.target.files?.[0])}
            />
            <button
              className="btn primary"
              disabled={!current}
              onClick={() => {
                if (current)
                  download(
                    new Blob([JSON.stringify(current, null, 2)], {
                      type: "application/json",
                    }),
                    current.invoice + "-packet.json",
                  );
              }}
            >
              Export packet
            </button>
          </div>
        </div>
        <section className="metrics" aria-label="Portfolio totals">
          <div>
            <small>Open receivables</small>
            <strong>
              {money(data.reduce((s, c) => s + c.collectible, 0))}
            </strong>
          </div>
          <div>
            <small>Invoice records</small>
            <strong>{data.length}</strong>
          </div>
          <div>
            <small>Evidence holds</small>
            <strong>
              {data.filter((c) => c.proof.some((p) => p.gaps.length)).length}
            </strong>
          </div>
          <div>
            <small>Past MSME ceiling</small>
            <strong
              className={
                data.some((c) => liability(c)?.beyondCeiling) ? "overdue" : ""
              }
            >
              {data.filter((c) => liability(c)?.beyondCeiling).length}
            </strong>
          </div>
        </section>
        <div className="toolbar">
          <label className="search">
            <Glyph type="search" />
            <input
              aria-label="Filter by invoice or buyer"
              placeholder="Find invoice or buyer"
              ref={input}
              value={search}
              onChange={(e) => filter(e.target.value)}
            />
            <kbd>/</kbd>
          </label>
          <select
            aria-label="Filter scope"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            {["All invoices", "On hold", "Past MSME ceiling"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {(view === "msme" || view === "comms") && (
            <select
              aria-label="Active invoice"
              value={current?.invoice ?? ""}
              onChange={(e) => select(e.target.value)}
            >
              {rows.map((r) => (
                <option key={r.invoice}>{r.invoice}</option>
              ))}
            </select>
          )}
          <span className="ml-auto micro">
            {current ? "Snapshot " + current.as_of : ""}
          </span>
        </div>
        {message && (
          <div className="notice" role="status">
            {message}
            <button aria-label="Dismiss message" onClick={() => notify("")}>
              ×
            </button>
          </div>
        )}
        {loading ? (
          <div className="empty" role="status">
            Loading invoice snapshots…
          </div>
        ) : view === "chain" ? (
          <Chain
            rows={rows}
            current={current}
            choose={choose}
            refresh={refresh}
            notify={notify}
          />
        ) : view === "tax" ? (
          <Tax rows={rows} current={current} choose={choose} />
        ) : view === "msme" ? (
          <Monitor c={current} rows={rows} choose={choose} />
        ) : current ? (
          <Communications
            key={current.review_key}
            c={current}
            refresh={refresh}
            notify={notify}
          />
        ) : (
          <p className="empty">No matching invoices.</p>
        )}
        {current && <Review key={current.review_key} invoice={current} />}
        <footer>
          <span>
            <kbd>J</kbd> <kbd>K</kbd> Select invoice <b>·</b> <kbd>1–4</kbd>{" "}
            Switch screen <b>·</b> <kbd>/</kbd> Find
          </span>
          <span>
            {current?.invoice ?? "—"} / {mode.name}
          </span>
        </footer>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
