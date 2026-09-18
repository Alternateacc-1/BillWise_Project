import { useEffect, useState } from "react";
import {
  confirmBill,
  createSample,
  getLetter,
  getReport,
  health,
  saveCorrections,
  uploadBill,
  type Flag,
  type Report,
  type ReportItem,
} from "./api";

type View = "upload" | "review" | "report";

const SEVERITY_STYLES: Record<string, string> = {
  red: "bg-red-50 border-red-300 text-red-900",
  amber: "bg-amber-50 border-amber-300 text-amber-900",
  green: "bg-green-50 border-green-300 text-green-900",
  gray: "bg-slate-50 border-slate-300 text-slate-700",
};

const SEVERITY_LABELS: Record<string, string> = {
  red: "Above the listed ceiling",
  amber: "May need clarification",
  green: "Within the published ceiling",
  gray: "Not compared",
};

function Badge({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold ${SEVERITY_STYLES[severity]}`}
    >
      {SEVERITY_LABELS[severity]}
    </span>
  );
}

function Evidence({ flag }: { flag: Flag }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-slate-600 underline hover:text-slate-900"
      >
        {open ? "Hide evidence" : `Show evidence (${flag.rule_id})`}
      </button>
      {open && (
        <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
          {JSON.stringify(flag.evidence, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ItemCard({ item }: { item: ReportItem }) {
  return (
    <div className={`rounded border p-3 ${SEVERITY_STYLES[item.severity]}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">
          {item.index}. {item.name}
        </span>
        <span className="font-mono text-sm">
          {item.line_total ? `Rs ${item.line_total}` : "Rs ?"}
        </span>
      </div>
      <div className="mt-1">
        <Badge severity={item.severity} />
      </div>
      {item.flags
        .filter((f) => f.explanation)
        .map((flag, n) => (
          <div key={n} className="mt-2 text-sm">
            <p>{flag.explanation}</p>
            {Object.keys(flag.evidence).length > 0 && <Evidence flag={flag} />}
          </div>
        ))}
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<View>("upload");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [readerNote, setReaderNote] = useState("");
  const [letter, setLetter] = useState("");
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});

  useEffect(() => {
    health()
      .then((h) => setReaderNote(h.reader))
      .catch(() => setReaderNote(""));
  }, []);

  async function load(billId: string) {
    const data = await getReport(billId);
    setReport(data);
    const needsReview = data.by_item.some(
      (i) => i.gray_reason === "could_not_verify",
    );
    setView(needsReview ? "review" : "report");
  }

  async function onSample() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const { bill_id } = await createSample();
      await load(bill_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(file: File) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const result = await uploadBill(file);
      if (result.items_read === 0) {
        setNote(result.note || "We could not read any lines from that file.");
        setBusy(false);
        return;
      }
      await load(result.bill_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (!report) return;
    setBusy(true);
    setError("");
    try {
      if (Object.keys(edits).length > 0) {
        await saveCorrections(report.bill_id, edits);
      }
      const updated = await confirmBill(report.bill_id);
      setReport(updated);
      setView("report");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onLetter() {
    if (!report) return;
    setBusy(true);
    try {
      const { letter: text } = await getLetter(report.bill_id);
      setLetter(text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function edit(index: number, field: string, value: string) {
    setEdits((prev) => ({
      ...prev,
      [index]: { ...(prev[index] ?? {}), [field]: value },
    }));
  }

  const unverified =
    report?.by_item.filter((i) => i.gray_reason === "could_not_verify") ?? [];

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-white p-6 text-slate-900">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">BillSahi</h1>
        <p className="text-sm text-slate-600">
          Check a hospital or pharmacy bill against India&rsquo;s published
          price ceilings.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {/* ---------------------------------------------------------- upload */}
      {view === "upload" && (
        <div className="space-y-4">
          <div className="rounded border border-slate-300 p-4">
            <label className="block text-sm font-medium">
              Upload a bill (PDF, JPG, PNG or WEBP, up to 10 MB)
            </label>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp"
              disabled={busy}
              className="mt-2 block w-full text-sm"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void onUpload(file);
              }}
            />
            {readerNote && (
              <p className="mt-2 text-xs text-slate-500">{readerNote}</p>
            )}
          </div>

          <button
            onClick={onSample}
            disabled={busy}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "Working..." : "Try a sample bill"}
          </button>

          {note && (
            <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              {note}
            </div>
          )}
        </div>
      )}

      {/* ---------------------------------------------------------- review */}
      {view === "review" && report && (
        <div className="space-y-4">
          <div className="rounded border border-slate-300 bg-slate-50 p-3 text-sm">
            <p className="font-medium">Optional: help us read these lines</p>
            <p className="mt-1 text-slate-600">
              We could not confidently read {unverified.length}{" "}
              {unverified.length === 1 ? "line" : "lines"}. You can correct them,
              or skip — we simply will not compare their prices.
            </p>
          </div>

          {unverified.map((item) => (
            <div key={item.index} className="rounded border border-slate-300 p-3">
              <p className="text-sm text-slate-600">
                Line {item.index}, page {item.page}
              </p>
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-4">
                <input
                  className="col-span-2 rounded border border-slate-300 px-2 py-1 text-sm"
                  defaultValue={item.name}
                  onChange={(e) => edit(item.index, "name", e.target.value)}
                />
                <input
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                  defaultValue={item.quantity ?? ""}
                  placeholder="Qty"
                  onChange={(e) => edit(item.index, "quantity", e.target.value)}
                />
                <input
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                  defaultValue={item.line_total ?? ""}
                  placeholder="Amount"
                  onChange={(e) => edit(item.index, "line_total", e.target.value)}
                />
              </div>
            </div>
          ))}

          <div className="flex gap-2">
            <button
              onClick={onConfirm}
              disabled={busy}
              className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? "Working..." : "Continue"}
            </button>
            <button
              onClick={() => setView("report")}
              className="rounded border border-slate-300 px-4 py-2 text-sm"
            >
              Skip
            </button>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------- report */}
      {view === "report" && report && (
        <div className="space-y-4">
          <div className="rounded border border-slate-300 p-4">
            <p className="font-medium">{report.hospital_name}</p>
            <p className="text-sm text-slate-600">
              Bill date {report.bill_date}
            </p>
            <p className="mt-2 text-sm">
              {report.stats.auto_high}/{report.stats.total_items} lines verified
              at high confidence &middot; bill total{" "}
              <span className="font-medium">{report.stats.reconciliation}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-sm">
              <span className="rounded border border-red-300 bg-red-50 px-2 py-1 text-red-900">
                {report.counts.red} above ceiling
              </span>
              <span className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-amber-900">
                {report.counts.amber} need clarification
              </span>
              <span className="rounded border border-green-300 bg-green-50 px-2 py-1 text-green-900">
                {report.counts.green} within ceiling
              </span>
              <span className="rounded border border-slate-300 bg-slate-50 px-2 py-1 text-slate-700">
                {report.counts.gray} not compared
              </span>
            </div>
            <p className="mt-3 text-xs text-slate-600">
              Of the {report.counts.gray} not compared,{" "}
              {report.gray_breakdown.no_public_ceiling} have no public price
              ceiling at all (room, nursing, consumables, lab tests) — we
              checked those for arithmetic and duplication only.{" "}
              {report.gray_breakdown.could_not_verify} could not be confidently
              identified.
            </p>
            <p className="mt-2 text-sm">
              Total amount affected across all points raised:{" "}
              <span className="font-medium">
                Rs {report.total_amount_affected}
              </span>
            </p>
          </div>

          {report.bill_level_flags.map((flag, n) => (
            <div
              key={n}
              className={`rounded border p-3 text-sm ${SEVERITY_STYLES[flag.severity]}`}
            >
              <p className="font-medium">Whole bill</p>
              <p className="mt-1">{flag.explanation}</p>
              <Evidence flag={flag} />
            </div>
          ))}

          <div className="space-y-2">
            {report.by_item.map((item) => (
              <ItemCard key={item.index} item={item} />
            ))}
          </div>

          <div className="rounded border border-slate-300 p-4">
            <button
              onClick={onLetter}
              disabled={busy}
              className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? "Working..." : "Write a clarification letter"}
            </button>
            {letter && (
              <textarea
                readOnly
                value={letter}
                rows={18}
                className="mt-3 w-full rounded border border-slate-300 p-3 font-mono text-xs"
              />
            )}
          </div>

          <p className="text-xs text-slate-500">
            Prices as per NPPA data retrieved {report.reference_retrieved_on}.
          </p>

          <button
            onClick={() => {
              setReport(null);
              setLetter("");
              setEdits({});
              setView("upload");
            }}
            className="rounded border border-slate-300 px-4 py-2 text-sm"
          >
            Check another bill
          </button>
        </div>
      )}
    </div>
  );
}
