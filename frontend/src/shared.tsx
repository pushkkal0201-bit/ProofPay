import type { ReactNode } from "react";

export const money = (n: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(n / 100);
export const days = (a: string, b: string) =>
  Math.round((Date.parse(a) - Date.parse(b)) / 86400000);
export function download(blob: Blob, name: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
export async function request(url: string, body?: unknown): Promise<Response> {
  const res = await fetch(
    "/api/" + url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!res.ok) {
    const issue: unknown = await res.json().catch(() => null);
    throw new Error(
      issue && typeof issue === "object" && "error" in issue
        ? String(issue.error)
        : "Request failed (" + res.status + ")",
    );
  }
  return res;
}
export function Pair({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="pair">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
export function PanelTitle({
  children,
  end,
}: {
  children: ReactNode;
  end?: ReactNode;
}) {
  return (
    <div className="panel-title">
      <h2>{children}</h2>
      {end}
    </div>
  );
}
export function Glyph({
  type,
}: {
  type: "chain" | "tax" | "msme" | "comms" | "search" | "brand";
}) {
  const paths = {
    chain: "M3 4h6v5H3z M15 15h6v5h-6z M6 9v6h9",
    tax: "M3 4h18v16H3z M3 9h18 M9 9v11 M15 9v11",
    msme: "M3 17h18 M5 17v-4 M10 17V9 M15 17V5 M20 17V2",
    comms: "M3 5h18v13H8l-5 3z M6 9h12 M6 13h8",
    search: "M16 16l5 5 M18 10a7 7 0 1 1-14 0 7 7 0 1 1 14 0",
    brand: "M3 20V3h11l6 5v6l-6 5H8 M8 14V8h5l2 2-2 4z",
  };
  return (
    <svg
      width={type === "brand" ? 26 : 16}
      height={type === "brand" ? 26 : 16}
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={type === "brand" ? 2 : 1.5}
    >
      <path d={paths[type]} />
    </svg>
  );
}
