export interface Split {
  cgst: number;
  sgst: number;
  igst: number;
}
export interface Attachment {
  filename: string;
  text: string;
  sha256: string;
}
export interface Crop {
  png_base64: string;
  sha256: string;
  ocr_text: string;
  origin: string;
}
export interface Evidence {
  id: string;
  line: string;
  invoice: string;
  kind: "POD" | "BOL" | "acceptance" | "telemetry" | "eway";
  timestamp: string;
  source: string;
  reviewer: string;
  verified: boolean;
  signer: string | null;
  uptime_bps: number | null;
  quantity: number | null;
  attachment: Attachment | null;
  crop?: Crop | null;
  signature?: { key_id: string; ed25519_base64: string } | null;
}
export interface Line {
  id: string;
  description: string;
  principal: number;
  gst: number;
  split: Split | null;
  clause: string;
  quantity: number;
}
export interface Posting {
  id: string;
  kind: "payment" | "credit" | "debit";
  date: string;
  base: number;
  gst: number;
  split: Split | null;
  approved: boolean;
}
export interface Statement {
  invoice: string;
  issued: string;
  supplier_gstin: string;
  recipient_gstin: string;
  principal: number;
  gst: number;
  split: Split | null;
}
export interface Terms {
  basis: "msmed" | "contract";
  acceptance: string | null;
  supplier_class: string | null;
  authority_ref: string;
  written_agreement: boolean | null;
  rates: { effective: string; bank_rate_bps: number; source: string }[];
}
export interface Snapshot {
  invoice: string;
  buyer: string;
  creditor: string;
  issued: string;
  due: string;
  as_of: string;
  gstin: string;
  supplier_gstin: string | null;
  lines: Line[];
  evidence: Evidence[];
  ledger: Posting[];
  statement_row: Statement | null;
  terms: Terms | null;
  dispute_text: string | null;
}
export interface LineProof {
  line: string;
  description: string;
  anchors: Evidence[];
  gaps: string[];
  clause: string;
}
export interface Segment {
  start: string;
  end: string;
  days: number;
  balance: number;
  annual_bps: number;
  source: string;
  opening_capitalized: number;
}
export interface Summary {
  adjusted_tax_split: Split & { unallocated: number };
  effective_due: string;
  contract_due: string;
  interest_estimate: {
    basis: string;
    status: string;
    amount: number | null;
    audit: Segment[];
  };
}
export interface Invoice {
  statutory_clock: {
    eligible: boolean;
    day_45: string | null;
    days_until_due: number;
  };
  tax_compliance: {
    payment_status: string;
    statement_window: string;
    payment_deadline: string;
  };
  invoice: string;
  buyer: string;
  balance: number;
  collectible: number;
  as_of: string;
  dpd: number;
  bucket: string;
  due: string;
  state: string;
  action: string;
  proof: LineProof[];
  itc_review: boolean;
  master_match: boolean;
  statement: string;
  reasons: string[];
  draft: string | null;
  reviewed: boolean;
  review_key: string;
  source: Snapshot;
  matrix: {
    principal: number;
    gst: number;
    debit: number;
    credit: number;
    payment: number;
  };
  LEDGER_SUMMARY: Summary;
  COMMUNICATIONS_DRAFT: {
    email: string | null;
    whatsapp: string | null;
    pdf_available: boolean;
  };
}
export type View = "chain" | "tax" | "msme" | "comms";
export type Channel = "email" | "whatsapp" | "pdf";
