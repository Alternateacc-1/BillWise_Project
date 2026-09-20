import { useId, useState, type ReactNode } from 'react'
import type { BillItem, BillReport } from '../lib/api'
import { Lockup } from '../Logo'
import { Chip } from '../Chip'
import { formatINR } from '../lib/money'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-bg'
const btnPrimary = `rounded-full bg-ink px-6 py-3 text-base font-medium text-white ${focusRing}`
const btnSecondary = `rounded-full border border-ink/20 bg-card px-6 py-3 text-base font-medium transition-colors hover:border-ink ${focusRing}`
const btnQuiet = `rounded-full border border-line bg-card px-6 py-[13px] text-base font-semibold transition-colors hover:border-[#141414] ${focusRing}`
const btnLink = `rounded-full px-2 py-1 text-sm font-medium text-muted underline-offset-4 hover:text-ink hover:underline ${focusRing}`

const RECONCILIATION: Record<BillReport['reading']['reconciliation'], string> = {
  reconciled: 'line items add up to the printed total',
  mismatch: 'line items do not add up to the printed total',
  // The engine distinguishes the DIRECTION, and the difference matters. A
  // printed total BELOW the line sum is the patient being asked for LESS than
  // the bill itemises -- an unread discount or round-off, not a discrepancy.
  // Calling it "does not add up" would query a pharmacy over its own discount.
  below_line_sum: 'the printed total is below the line items, which usually means a discount or round-off we could not read',
  no_total_found: 'no printed total was found to check against',
}

const GRAY_EXPLANATION = {
  no_public_ceiling:
    'No published price ceiling exists in India for this item, so there is nothing to compare it against. We still checked it for duplication and arithmetic.',
  could_not_read: 'We could not read this line reliably, so we have not compared its price.',
  // The two the provisional contract had no room for. Folding either into
  // could_not_read would blame our reading for something else entirely.
  could_not_identify:
    'We read these lines clearly but could not work out which medicine they are, so there is no ceiling to compare them against.',
  pack_size_unknown:
    'We know what these are and we read them correctly, but the bill does not say how many units each line covers — ten tablets or ten strips changes the per-unit price tenfold. Rather than guess, we have not compared them.',
}

interface Props {
  report: BillReport
  onLetter: () => void
  onWrong: () => void
  onNewBill: () => void
}

/** Upper box: the summary and the actions. The result groups live in <ReportDetail/> below the step row. */
export default function Report({ report, onLetter, onWrong, onNewBill }: Props) {
  const { summary, reading } = report
  const findingsTotal = summary.above_ceiling + summary.needs_clarification

  return (
    <div>
      {/* Print-only header: the panel chrome is hidden on paper. */}
      <div className="hidden print:block">
        <Lockup />
        <h1 className="mt-4 text-2xl font-bold">Bill check report</h1>
        <p className="text-sm text-muted">
          {report.hospital_name} · bill dated {report.bill_date}
        </p>
      </div>

      {/* THE DENOMINATOR COMES FIRST, ALWAYS.
        *
        * "We found nothing above the listed ceiling" reads as "your bill is
        * fine". On a bill where nothing could be compared it is true and it is
        * a lie. Measured on a real retail pharmacy bill: six of six lines
        * gray, ZERO compared, and this sentence rendered calm and green.
        *
        * Falsely reassuring a patient about a medical bill is the same failure
        * as falsely accusing a pharmacy, pointed the other way -- and every
        * guard in the engine points at the accusing direction only. So the
        * count of what we CHECKED leads, and a report that checked nothing
        * says exactly that in its first sentence. */}
      <p className="text-xl font-medium leading-snug sm:text-2xl">
        {summary.compared === 0 ? (
          <>
            We could not compare any of the {count(reading.lines_total, 'charge')} on this bill
            against a published ceiling.
          </>
        ) : findingsTotal === 0 ? (
          <>
            We compared {summary.compared} of {count(reading.lines_total, 'charge')} against a
            published ceiling and found nothing above it.
          </>
        ) : (
          <>
            We compared {summary.compared} of {count(reading.lines_total, 'charge')} against a
            published ceiling, and found {count(summary.above_ceiling, 'item')} above it and{' '}
            {count(summary.needs_clarification, 'item')} that may need clarification — amount affected{' '}
            <span className="whitespace-nowrap">{formatINR(summary.total_amount_affected)}</span>.
          </>
        )}
      </p>
      {summary.compared === 0 && (
        <p className="mt-3 text-muted">
          This does not mean the bill is fine. It means we found nothing to check it against.
          Each group below says which lines, and why.
        </p>
      )}
      <p className="mt-3 text-muted">
        {reading.lines_verified} of {reading.lines_total} lines read at high confidence;{' '}
        {RECONCILIATION[reading.reconciliation]}.
      </p>
      {/* "Verified by BOTH readers" is FALSE when only one ran, and the count
        * alone does not say which. Same bill on the deployed stack: 0 of 7
        * high-confidence with two readers, 4 of 7 with one. */}
      {reading.single_reader && (
        <p className="mt-1 text-sm text-muted">
          Only one reader ran on this bill, so nothing cross-checked the reading. A single reader
          cannot disagree with itself — read the confidence above with that in mind.
        </p>
      )}
      {/* R2 reports ONLY at the whole-bill level, so without this a bill whose
        * total does not match its lines rendered as a bill with nothing wrong. */}
      {report.bill_findings.length > 0 && (
        <ul className="mt-4 space-y-2">
          {report.bill_findings.map((f, n) => (
            <li
              key={n}
              className={`rounded-2xl border border-ink/10 border-l-4 p-4 text-sm ${
                f.severity === 'red' ? 'border-l-red-700' : 'border-l-amber-400'
              }`}
            >
              <p className="text-xs font-medium text-muted">Whole bill · {f.rule_id}</p>
              <p className="mt-1">{f.headline}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-sm text-muted">Reference: {report.reference_version}</p>

      <div className="mt-6 flex flex-wrap items-center gap-3 print:hidden">
        {/* Offering to complain about a bill we found nothing wrong with is a
          * credibility leak in the exact place the product earns trust. It
          * stays reachable, as a quiet button, saying what it can actually
          * say. */}
        {findingsTotal > 0 ? (
          <button type="button" onClick={onLetter} className={btnPrimary}>
            Write a clarification letter
          </button>
        ) : (
          <button type="button" onClick={onLetter} className={btnQuiet}>
            Write a letter asking about the charges we could not check
          </button>
        )}
        <button type="button" onClick={() => window.print()} className={btnSecondary}>
          Print / Save as PDF
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 print:hidden">
        <button type="button" onClick={onWrong} className={btnQuiet}>
          Something looks wrong
        </button>
        <button type="button" onClick={onNewBill} className={btnQuiet}>
          Upload a different bill
        </button>
      </div>
    </div>
  )
}

/** Lower box: four columns, one per outcome. Filtering by severity/reason only — API order is kept within each column. */
export function ReportDetail({ report }: { report: BillReport }) {
  const { items } = report
  const found = items.filter((i) => i.severity === 'red' || i.severity === 'amber')
  const fine = items.filter((i) => i.severity === 'green')
  const gray = (r: string) => items.filter((i) => i.severity === 'gray' && i.gray_reason === r)
  const noCeiling = gray('no_public_ceiling')
  const unread = gray('could_not_read')
  // The engine's other two gray reasons. Without their own columns these
  // lines either vanished or were counted as misreads.
  const unidentified = gray('could_not_identify')
  const packUnknown = gray('pack_size_unknown')

  return (
    <div>
      <div className="flow-detail-grid">
        {/* Column 1 has no single summary field; its count is the two summary counts it covers, added. */}
        {/* EVERY COUNT IS `array.length`, NOT A SUMMARY FIELD. The two are
          * computed on different partitions and they had drifted -- a header
          * reading (10) above a list of 9. A count taken from the array it
          * labels cannot disagree with it. */}
        <Column title="What we found" count={found.length + report.bill_findings.length}>
          {found.length === 0 ? (
            <p className="text-muted">Nothing to ask about.</p>
          ) : (
            <ul className="space-y-4">
              {found.map((item) => (
                <li key={item.index}>
                  <FindingCard item={item} />
                </li>
              ))}
            </ul>
          )}
        </Column>
        <Column title="Checked, no issue" count={fine.length}>
          <Rows items={fine} chip />
        </Column>
        <Column title="No published ceiling" count={noCeiling.length} explanation={GRAY_EXPLANATION.no_public_ceiling}>
          <Rows items={noCeiling} />
        </Column>
        {unidentified.length > 0 && (
          <Column
            title="Could not be identified"
            count={unidentified.length}
            explanation={GRAY_EXPLANATION.could_not_identify}
          >
            <Rows items={unidentified} />
          </Column>
        )}
        {packUnknown.length > 0 && (
          <Column
            title="Price could not be determined"
            count={packUnknown.length}
            explanation={GRAY_EXPLANATION.pack_size_unknown}
          >
            <Rows items={packUnknown} />
          </Column>
        )}
        {unread.length > 0 && (
          <Column title="Could not be read" count={unread.length} explanation={GRAY_EXPLANATION.could_not_read}>
            <Rows items={unread} />
          </Column>
        )}
      </div>

      <footer className="mt-8 hidden border-t border-ink/10 pt-4 text-xs text-muted print:block">
        Reference: {report.reference_version}. Ceilings are compared as published on that date. This report is
        information to help you ask questions about a bill; it is not legal or medical advice. Prepared with BillWise.
      </footer>
    </div>
  )
}

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`

function Column({ title, count, explanation, children }: { title: string; count: number; explanation?: string; children: ReactNode }) {
  const id = useId()
  return (
    <section className="flow-detail-col" aria-labelledby={id}>
      <h3 id={id} className="text-[18px] font-bold tracking-tight">
        {title} <span className="font-normal text-muted">({count})</span>
      </h3>
      {explanation && <p className="mt-2 text-sm text-muted">{explanation}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

/** One row per item. Gray columns carry their explanation in the header, so rows are just line, name and amount. */
function Rows({ items, chip = false }: { items: BillItem[]; chip?: boolean }) {
  if (items.length === 0) return <p className="text-sm text-muted">None.</p>
  return (
    <ul className="divide-y divide-ink/10">
      {items.map((item) => (
        <li key={item.index} className="py-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-xs font-medium text-muted">Line {item.index}</span>
            <span className="min-w-0 flex-1 font-medium">{item.name}</span>
            <span className="whitespace-nowrap">{formatINR(item.amount)}</span>
            {chip && <Chip tone={item.severity} />}
          </div>
          {chip && item.headline && <p className="mt-1 text-sm text-muted">{item.headline}</p>}
          <Evidence item={item} />
        </li>
      ))}
    </ul>
  )
}

const hasEvidence = (item: BillItem) => (item.evidence && Object.keys(item.evidence).length > 0) || (item.notes && item.notes.length > 0)

/** The listed ceiling for the line, only if the API sent one: the line total when it did, else the per-unit figure, labelled as such. */
function listedCeiling(item: BillItem): { label: string; value: string } | null {
  const ev = item.evidence ?? {}
  // THESE KEY NAMES WERE GUESSED AND NONE OF THEM EXISTED, so the ceiling row
  // never rendered on any bill. R5 emits `amber_threshold` -- the published
  // ceiling per unit WITH GST added, which is the figure the line is actually
  // measured against -- and `ceiling_ex_gst` before tax. Showing the allowance
  // is the honest one: it is what the verdict compares to.
  if (typeof ev.amber_threshold === 'string') {
    return { label: 'Allowed per unit (incl. GST)', value: ev.amber_threshold }
  }
  if (typeof ev.ceiling_ex_gst === 'string') {
    return { label: 'Published ceiling (before GST)', value: ev.ceiling_ex_gst }
  }
  return null
}

function FindingCard({ item }: { item: BillItem }) {
  const accent = item.severity === 'red' ? 'border-l-red-700' : item.severity === 'amber' ? 'border-l-amber-400' : 'border-l-transparent'
  const ceiling = listedCeiling(item)
  return (
    <article className={`rounded-2xl border border-ink/10 border-l-4 p-5 ${accent}`} aria-labelledby={`item-${item.index}`}>
      <p className="text-xs font-medium text-muted">Line {item.index}</p>
      <h4 id={`item-${item.index}`} className="text-lg font-bold leading-snug">
        {item.name}
      </h4>
      {/* Three figures, all verbatim from the API: nothing here is subtracted or derived. */}
      <dl className="mt-3 grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1">
        <dt className="text-[13px] text-muted">Billed</dt>
        <dd className="text-right text-[15px] tabular-nums">{formatINR(item.amount)}</dd>
        {ceiling && (
          <>
            <dt className="text-[13px] text-muted">{ceiling.label}</dt>
            <dd className="text-right text-[15px] tabular-nums">{formatINR(ceiling.value)}</dd>
          </>
        )}
        {item.amount_affected && (
          <>
            <dt className="text-[13px] text-muted">Difference</dt>
            <dd className="text-right text-[17px] font-bold tabular-nums">{formatINR(item.amount_affected)}</dd>
          </>
        )}
      </dl>
      <div className="mt-3">
        <Chip tone={item.severity} />
      </div>
      <Evidence item={item} headline />
    </article>
  )
}

function Evidence({ item, headline = false }: { item: BillItem; headline?: boolean }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const entries = Object.entries(item.evidence ?? {})
  if (!headline && !hasEvidence(item)) return null
  return (
    <div className="mt-3">
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} className={`${btnLink} px-0 print:hidden`}>
        {open ? 'Hide evidence' : 'Show evidence'}
      </button>
      <div id={id} className={`mt-2 rounded-xl bg-surface p-4 text-sm ${open ? '' : 'hidden'} print:block`}>
        {headline && <p className={entries.length > 0 ? 'mb-3' : ''}>{item.headline}</p>}
        {entries.length > 0 && (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[max-content_1fr]">
            {entries.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="font-medium text-muted">{label(k)}</dt>
                <dd className="break-words">{show(v)}</dd>
              </div>
            ))}
          </dl>
        )}
        {item.notes && item.notes.length > 0 && (
          <div className={entries.length > 0 ? 'mt-4 border-t border-ink/10 pt-3' : ''}>
            <p className="font-medium text-muted">Also noted</p>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {item.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

/** "so_number" -> "SO number"; "ceiling_per_unit" -> "Ceiling per unit". Labels only — values are printed verbatim. */
function label(key: string): string {
  const words = key.split('_')
  return words.map((w, i) => (w === 'so' ? 'SO' : i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(' ')
}

function show(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v)
  return JSON.stringify(v)
}
