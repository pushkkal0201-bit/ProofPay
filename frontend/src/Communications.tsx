import { useState } from "react";
import type { Channel, Invoice } from "./types";
import { download, PanelTitle, request } from "./shared";

interface Props {
  c: Invoice;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}
interface WhatsAppBody {
  text: { body: string };
}

export function Communications({ c, refresh, notify }: Props) {
  const initial = c.draft ?? "";
  const storageKey = "dispatch:" + c.review_key;
  const [text, setText] = useState(() => {
    try {
      return sessionStorage.getItem(storageKey) ?? initial;
    } catch {
      return initial;
    }
  });
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState("");
  const [emailFile, setEmailFile] = useState<Blob | null>(null);
  function edit(s: string) {
    setText(s);
    setLink("");
    setEmailFile(null);
    try {
      sessionStorage.setItem(storageKey, s);
    } catch {
      notify("Session storage unavailable; edits are held in this view.");
    }
  }
  async function prepare(channel: Channel) {
    setBusy(true);
    try {
      const r = await request("handoff", {
        invoice: c.invoice,
        review_key: c.review_key,
        channel,
        text,
      });
      if (channel === "pdf") {
        download(await r.blob(), c.invoice + "-notice.pdf");
        notify("PDF demand notice generated.");
      } else if (channel === "email") {
        setEmailFile(await r.blob());
        const uri =
          "mailto:?subject=" +
          encodeURIComponent("Payment reconciliation | " + c.invoice) +
          "&body=" +
          encodeURIComponent(text);
        if (uri.length < 8000) {
          window.location.href = uri;
          notify(
            "Email prepared for your mail client. Select the recipient and send there.",
          );
        } else
          notify(
            "Email prepared. Download the .eml file to open this long notice in your mail client.",
          );
      } else {
        const payload: WhatsAppBody = await r.json();
        setLink("https://wa.me/?text=" + encodeURIComponent(payload.text.body));
        notify(
          "WhatsApp link ready. Open it to choose the recipient and send.",
        );
      }
    } catch (e) {
      notify(String(e));
    } finally {
      setBusy(false);
    }
  }
  const allowed = {
    email: !!c.COMMUNICATIONS_DRAFT.email,
    whatsapp: !!c.COMMUNICATIONS_DRAFT.whatsapp,
    pdf: !!c.COMMUNICATIONS_DRAFT.pdf_available,
  };
  const locked = !initial;
  return (
    <section className="sheet dispatch">
      <PanelTitle end={<span>{c.invoice}</span>}>
        Resolution &amp; Dispatch
      </PanelTitle>
      <div className="envelope">
        <span>FROM</span>
        <b>{c.source.creditor}</b>
        <span>TO</span>
        <b>{c.buyer} · Accounts payable</b>
      </div>
      {locked ? (
        <div className="lock-message">
          <b>Dispatch locked</b>
          <p>{c.reasons.join(" ") || c.action}</p>
        </div>
      ) : (
        <>
          <label className="editor-heading" htmlFor="correspondence">
            Notification text{" "}
            <span>
              {text === initial ? "System compiled" : "Manually edited"}
            </span>
          </label>
          <textarea
            id="correspondence"
            className="editor"
            value={text}
            maxLength={20000}
            onChange={(e) => edit(e.target.value)}
            disabled={busy}
          />
        </>
      )}
      <div className="dispatch-actions">
        {(["email", "whatsapp", "pdf"] as const).map((channel) => (
          <button
            key={channel}
            className={"btn " + (channel === "email" ? "primary" : "")}
            disabled={busy || !allowed[channel] || !text.trim()}
            onClick={() => prepare(channel)}
          >
            {
              {
                email: "Dispatch Email",
                whatsapp: "Sync WhatsApp Link",
                pdf: "Generate PDF Demand Notice",
              }[channel]
            }
          </button>
        ))}
      </div>
      {link && (
        <a className="handoff" href={link} target="_blank" rel="noreferrer">
          Open WhatsApp message ↗
        </a>
      )}
      {emailFile && (
        <button
          className="handoff"
          onClick={() => download(emailFile, c.invoice + ".eml")}
        >
          Download prepared email (.eml)
        </button>
      )}
      {!locked && (
        <div className="editor-meta">
          <button
            disabled={text === initial || busy}
            onClick={() => edit(initial)}
          >
            Restore compiled text
          </button>
          <button
            disabled={c.reviewed || busy || text !== initial}
            onClick={async () => {
              try {
                await request("review", {
                  invoice: c.invoice,
                  review_key: c.review_key,
                });
                await refresh();
                notify("Compiled text marked reviewed.");
              } catch (e) {
                notify(String(e));
              }
            }}
          >
            {c.reviewed
              ? "Compiled text reviewed"
              : "Mark compiled text reviewed"}
          </button>
        </div>
      )}
    </section>
  );
}
