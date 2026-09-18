const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* the server did not send JSON; keep the generic message */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export type Flag = {
  rule_id: string;
  severity: "red" | "amber" | "green" | "gray";
  item_index: number;
  amount_affected: string;
  evidence: Record<string, unknown>;
  suggested_question: string;
  explanation: string;
  gray_reason: string | null;
};

export type ReportItem = {
  index: number;
  name: string;
  quantity: string | null;
  unit_price: string | null;
  line_total: string | null;
  page: number;
  confidence: string;
  severity: "red" | "amber" | "green" | "gray";
  gray_reason: string | null;
  flags: Flag[];
};

export type Report = {
  bill_id: string;
  hospital_name: string;
  bill_date: string;
  reference_retrieved_on: string;
  by_item: ReportItem[];
  counts: Record<string, number>;
  bill_level_flags: Flag[];
  gray_breakdown: { no_public_ceiling: number; could_not_verify: number };
  total_amount_affected: string;
  stats: {
    total_items: number;
    auto_high: number;
    still_unverified: number;
    reconciliation: string;
    sum_of_line_totals: string | null;
    printed_grand_total: string | null;
  };
};

export const health = () =>
  request<{ status: string; provider: string; reader: string }>("/health");

export const createSample = () =>
  request<{ bill_id: string }>("/bills/sample", { method: "POST" });

export async function uploadBill(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<{ bill_id: string; items_read: number; note: string }>("/bills", {
    method: "POST",
    body: form,
  });
}

export const getReport = (billId: string) => request<Report>(`/bills/${billId}`);

export const saveCorrections = (
  billId: string,
  corrections: Record<string, Record<string, string>>,
) =>
  request<{ corrections: number }>(`/bills/${billId}/items`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corrections }),
  });

export const confirmBill = (billId: string) =>
  request<Report>(`/bills/${billId}/confirm`, { method: "POST" });

export const getLetter = (billId: string) =>
  request<{ letter: string }>(`/bills/${billId}/letter`, { method: "POST" });
