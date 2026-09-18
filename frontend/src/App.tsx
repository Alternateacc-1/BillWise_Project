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

/** Indian digit grouping: 12,94,761 -- not 1,294,761. */
const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
});

function rupees(value: string | null): string {
  if (value === null || value === "") return "₹?";
  const n = Number(value);
  return Number.isFinite(n) ? INR.format(n) : `₹${value}`;
}

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

function Evidence({ flag, notes = [] }: { flag: Flag; notes?: Flag[] }) {
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
        <div className="mt-2 space-y-2">
          {/* Secondary findings live here rather than competing for the
              item's headline verdict. Nothing is hidden; it is subordinate. */}
          {notes.map((note, n) => (
            <p key={n} className="text-xs text-slate-700">
              <span className="font-medium">{note.rule_id}:</span>{" "}
              {note.explanation}
            </p>
          ))}
          <pre className="overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
            {JSON.stringify(flag.evidence, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function LetterButton({
  onClick,
  busy,
  label,
}: {
  onClick: () => void;
  busy: boolean;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
    >
      {busy ? "Working..." : label}
    </button>
  );
}

/** A finding worth acting on. Expanded by default -- this is the point. */
function FindingCard({ item }: { item: ReportItem }) {
  return (
    <div className={`rounded border p-3 ${SEVERITY_STYLES[item.severity]}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">
          {item.index}. {item.name}
        </span>
        <span className="font-mono text-sm">
          {rupees(item.line_total)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <Badge severity={item.severity} />
        {item.amount_affected !== "0" && (
          <span className="text-xs">
            Amount affected: {rupees(item.amount_affected)}
          </span>
        )}
      </div>
      {item.headline && (
        <p className="mt-2 text-sm">{item.headline.explanation}</p>
      )}
      {item.headline && Object.keys(item.headline.evidence).length > 0 && (
        <Evidence flag={item.headline} notes={item.notes} />
      )}
    </div>
  );
}

/** Name and amount only. The explanation lives once, on the group header. */
function ItemList({ items }: { items: ReportItem[] }) {
  return (
    <ul className="divide-y divide-slate-200 text-sm">
      {items.map((item) => (
        <li key={item.index} className="flex justify-between gap-3 py-1.5">
          <span>
            {item.index}. {item.name}
          </span>
          <span className="font-mono text-slate-600">
            {rupees(item.line_total)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Group({
  title,
  subtitle,
  count,
  defaultOpen,
  children,
}: {
  title: string;
  subtitle?: string;
  count: number;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (count === 0) return null;
  return (
    <section className="rounded border border-slate-300">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 p-3 text-left"
      >
        <span className="font-medium">
          {title} <span className="text-slate-500">({count})</span>
        </span>
        <span className="text-sm text-slate-500">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="border-t border-slate-200 p-3">
          {/* Stated ONCE, here -- never repeated on every item below. */}
          {subtitle && (
            <p className="mb-3 text-sm text-slate-600">{subtitle}</p>
          )}
          {children}
        </div>
      )}
    </section>
  );
}

/** The reconciliation state, in words a patient can act on.
 *
 * `below_line_sum` deliberately reads as a NON-event. The bill charged less
 * than its lines add up to, which is what an unread discount or round-off
 * looks like, and presenting that as a discrepancy asks someone to query a
 * bill for undercharging them. */
function reconciliationLabel(state: string): string {
  switch (state) {
    case "reconciled":
      return "bill total reconciled";
    case "below_line_sum":
      return "bill total is below the line sum (likely a discount)";
    case "mismatch":
      return "bill total mismatch";
    case "no_total_found":
      return "no bill total found";
    default:
      return state;
  }
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

    // ?bill=<id> opens an existing report directly, so a report can be
    // revisited or shared. ?sample=<fixture> runs a specific bundled bill.
    const params = new URLSearchParams(window.location.search);
    const billId = params.get("bill");
    const sample = params.get("sample");
    if (billId) {
      void load(billId).catch((e) => setError((e as Error).message));
    } else if (sample) {
      void createSample(sample)
        .then((r) => load(r.bill_id))
        .catch((e) => setError((e as Error).message));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // Only offer to review what a correction can actually FIX. Re-typing the
  // name of a line whose pack size is unstated does not tell us how many
  // tablets are in a strip, so asking would waste the user's time and imply
  // we could act on the answer.
  const unverified =
    report?.by_item.filter(
      (i) =>
        i.severity === "gray" &&
        (i.gray_detail === "could_not_read" ||
          i.gray_detail === "could_not_identify"),
    ) ?? [];

  // Three groups, in the order a worried person needs them: what to act on,
  // what is fine, what we could not check.
  const findings = (report?.by_item ?? [])
    .filter((i) => i.severity === "red" || i.severity === "amber")
    .sort(
      (a, b) => Number(b.amount_affected) - Number(a.amount_affected),
    );
  const clear = (report?.by_item ?? []).filter((i) => i.severity === "green");
  const notCompared = (report?.by_item ?? []).filter(
    (i) => i.severity === "gray",
  );

  // Two labelled subgroups rather than one group with counts asserted in
  // prose. A header that says "10 ... 2" above a list of 10 items is a bug
  // waiting to happen; a count derived from the array it labels cannot lie.
  const noCeiling = notCompared.filter(
    (i) => i.gray_reason === "no_public_ceiling",
  );
  const couldNotRead = notCompared.filter(
    (i) => i.gray_detail === "could_not_read",
  );
  const couldNotIdentify = notCompared.filter(
    (i) => i.gray_detail === "could_not_identify",
  );
  const packSizeUnknown = notCompared.filter(
    (i) => i.gray_detail === "pack_size_unknown",
  );

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
          {/* ---- the honest line, first thing anyone reads ---------------- */}
          <div className="rounded border border-slate-300 p-4">
            <p className="font-medium">{report.hospital_name}</p>
            <p className="text-sm text-slate-600">
              Bill date {report.bill_date}
            </p>

            <p className="mt-3">
              We found{" "}
              <span className="font-semibold">
                {report.findings_count}{" "}
                {report.findings_count === 1 ? "thing" : "things"}
              </span>{" "}
              worth asking about, worth{" "}
              <span className="font-semibold">
                {rupees(report.total_amount_affected)}
              </span>
              .
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {report.gray_breakdown.no_public_ceiling} of the{" "}
              {report.stats.total_items} charges have no published ceiling in
              India, so we checked those for duplication and arithmetic only.
            </p>

            {/* The primary action, before sixteen cards rather than after. */}
            <div className="mt-4">
              <LetterButton
                onClick={onLetter}
                busy={busy}
                label="Write a clarification letter"
              />
            </div>

            <p className="mt-3 text-xs text-slate-500">
              {report.stats.auto_high}/{report.stats.total_items} lines read at
              high confidence &middot; {reconciliationLabel(report.stats.reconciliation)}{" "}
              &middot; prices as per NPPA data retrieved{" "}
              {report.reference_retrieved_on}
            </p>
          </div>

          {letter && (
            <div className="rounded border border-slate-300 p-4">
              <p className="mb-2 text-sm font-medium">Clarification letter</p>
              <textarea
                readOnly
                value={letter}
                rows={18}
                className="w-full rounded border border-slate-300 p-3 font-mono text-xs"
              />
            </div>
          )}

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

          {/* ---- 1. what we found ---------------------------------------- */}
          <Group
            title="What we found"
            count={findings.length}
            defaultOpen={true}
          >
            <div className="space-y-2">
              {findings.map((item) => (
                <FindingCard key={item.index} item={item} />
              ))}
            </div>
          </Group>

          {/* ---- 2. checked, no issue ------------------------------------ */}
          <Group
            title="Checked, no issue"
            subtitle="These are priced within the published ceiling."
            count={clear.length}
            defaultOpen={false}
          >
            <ItemList items={clear} />
          </Group>

          {/* ---- 3. not compared, split so the counts evidence themselves -- */}
          <Group
            title="No published ceiling"
            subtitle="Room rent, nursing, consumables and lab tests are not price-controlled in India, so there is no published rate to compare these against. They were still checked for duplication and arithmetic."
            count={noCeiling.length}
            defaultOpen={false}
          >
            <ItemList items={noCeiling} />
          </Group>

          <Group
            title="Could not be read"
            subtitle="Our two readers did not agree on these lines, or the arithmetic did not hold, so we did not trust our own reading enough to compare a price."
            count={couldNotRead.length}
            defaultOpen={false}
          >
            <ItemList items={couldNotRead} />
          </Group>

          <Group
            title="Price could not be determined"
            subtitle="We know what these are and we read them correctly, but the bill does not say how many units each line covers — ten tablets or ten strips changes the per-unit price tenfold. Rather than guess, we have not compared them."
            count={packSizeUnknown.length}
            defaultOpen={false}
          >
            <ItemList items={packSizeUnknown} />
          </Group>

          <Group
            title="Could not be identified"
            subtitle="We read these lines clearly but could not work out which medicine they are, so there is no ceiling to compare them against."
            count={couldNotIdentify.length}
            defaultOpen={false}
          >
            <ItemList items={couldNotIdentify} />
          </Group>

          <div className="flex flex-wrap gap-2 pt-2">
            <LetterButton
              onClick={onLetter}
              busy={busy}
              label="Write a clarification letter"
            />
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
        </div>
      )}
    </div>
  );
}
