import { useState } from "react";
import type { AgentReply, Channel, Invoice } from "./types";
import { download, Pair, PanelTitle, request } from "./shared";
export function Communications({
  c,
  refresh,
  notify,
}: {
  c: Invoice;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}) {
  const choices: Record<Channel, string | null> = {
    email: c.COMMUNICATIONS_DRAFT.email,
    whatsapp: c.COMMUNICATIONS_DRAFT.whatsapp,
    pdf: c.draft,
  };
  const [channel, setChannel] = useState<Channel>(
    choices.email ? "email" : choices.whatsapp ? "whatsapp" : "pdf",
  );
  const [edits, setEdits] = useState<Partial<Record<Channel, string>>>(() => {
    try {
      return (
        JSON.parse(sessionStorage.getItem("pp:" + c.review_key) ?? "{}") ?? {}
      );
    } catch {
      return {};
    }
  });
  const [advice, setAdvice] = useState<AgentReply | null>(null),
    [busy, setBusy] = useState(false);
  const baseline = choices[channel] ?? "",
    text = edits[channel] ?? baseline;
  function edit(value: string) {
    const next = { ...edits, [channel]: value };
    setEdits(next);
    try {
      sessionStorage.setItem("pp:" + c.review_key, JSON.stringify(next));
    } catch {
      notify(
        "Browser storage unavailable; edit retained in this tab until navigation.",
      );
    }
  }
  async function prepare() {
    setBusy(true);
    try {
      const r = await request("handoff", {
        invoice: c.invoice,
        review_key: c.review_key,
        channel,
        text,
      });
      const ext = { email: "eml", whatsapp: "json", pdf: "pdf" }[channel];
      download(await r.blob(), c.invoice + "-draft." + ext);
      notify("Prepared " + channel + " draft. No message sent.");
    } catch (e) {
      notify(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="split equal">
        <section className="sheet">
          <PanelTitle end={<span>Read only</span>}>Engine payload</PanelTitle>
          <dl>
            <Pair label="Invoice">{c.invoice}</Pair>
            <Pair label="Decision">{c.state}</Pair>
            <Pair label="Evidence">
              {c.proof.flatMap((p) => p.anchors.map((a) => a.id)).join(" / ") ||
                "—"}
            </Pair>
          </dl>
          <pre className="letter">
            {baseline || c.reasons.join("\n") || c.action}
          </pre>
          <div className="inset">
            <button
              className="btn"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const r: AgentReply = await (
                    await request("agent", { invoice: c.invoice })
                  ).json();
                  setAdvice(r);
                } catch (e) {
                  notify(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Inspect with RAV-AI
            </button>
            {advice && (
              <p className="footnote">
                {advice.mode} · {advice.task} · {advice.trace.join(" → ")}
              </p>
            )}
          </div>
        </section>
        <section className="sheet">
          <PanelTitle end={<span>{c.invoice}</span>}>Draft editor</PanelTitle>
          <div className="tabs">
            {(["email", "whatsapp", "pdf"] as const).map((k) => (
              <button
                key={k}
                disabled={!choices[k]}
                aria-pressed={k === channel}
                onClick={() => setChannel(k)}
              >
                {k === "email"
                  ? "Email"
                  : k === "pdf"
                    ? "PDF notice"
                    : "WhatsApp API"}
              </button>
            ))}
          </div>
          <textarea
            aria-label="Editable communication draft"
            className="editor"
            maxLength={20000}
            value={text}
            disabled={!baseline}
            onChange={(e) => edit(e.target.value)}
            placeholder="Draft withheld by policy."
          />
          <div className="inset">
            <div className="flex flex-wrap gap-2">
              <button
                className="btn primary"
                disabled={!baseline || !text.trim() || busy}
                onClick={prepare}
              >
                {channel === "pdf"
                  ? "Generate edited PDF"
                  : channel === "whatsapp"
                    ? "Export API body"
                    : "Download email draft"}
              </button>
              <button
                className="btn"
                disabled={text === baseline}
                onClick={() => edit(baseline)}
              >
                Reset edits
              </button>
            </div>
            <p className="footnote">
              {channel === "whatsapp"
                ? "Insert an authorized recipient and verify session or template eligibility before delivery."
                : channel === "email"
                  ? "Open the .eml in your mail client to add the recipient and send."
                  : "The PDF uses the edited text and the verified financial summary."}
            </p>
          </div>
        </section>
      </div>
      <div className="bottom-tools">
        <span>
          Engine draft · {c.reviewed ? "review recorded" : "awaiting review"}
        </span>
        <button
          className="btn"
          disabled={!c.draft || c.reviewed || busy}
          onClick={async () => {
            try {
              await request("review", {
                invoice: c.invoice,
                review_key: c.review_key,
              });
              await refresh();
              notify("Engine draft review recorded.");
            } catch (e) {
              notify(String(e));
            }
          }}
        >
          Mark engine draft reviewed
        </button>
      </div>
    </>
  );
}
