import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { BillItem, BillReport, GrayReason } from '../lib/api'
import { Lockup } from '../Logo'
import { Chip } from '../Chip'
import { formatINR } from '../lib/money'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-bg'
const btnPrimary = `rounded-full bg-ink px-[18px] py-2.5 text-[14px] font-medium text-white ${focusRing}`
const btnSecondary = `rounded-full border border-ink/20 bg-card px-[18px] py-2.5 text-[14px] font-medium transition-colors hover:border-ink ${focusRing}`
const btnQuiet = `rounded-full border border-line bg-card px-[18px] py-2.5 text-[14px] font-semibold transition-colors hover:border-[#141414] ${focusRing}`
const btnLink = `rounded-full px-2 py-1 text-sm font-medium text-muted underline-offset-4 hover:text-ink hover:underline ${focusRing}`
const btnText = `rounded py-1 text-[13px] font-medium text-muted underline-offset-4 hover:text-ink hover:underline ${focusRing}`

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
  not_cross_checked:
    'Only one reader ran on this bill, so nothing confirmed these lines and we have not compared their prices. This is not a sign they were read wrongly — it means they were not double-checked.',
  pack_size_unknown:
    'We know what these are and we read them correctly, but the bill does not say how many units each line covers — ten tablets or ten strips changes the per-unit price tenfold. Rather than guess, we have not compared them.',
}

interface Props {
  report: BillReport
  onLetter: () => void
  onWrong: () => void
  onNewBill: () => void
}

/** The Report column: a teaser. Summary, five fading preview rows, actions. The findings live in <DetailedAnalysis/> below the step row. */
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
      <p className="text-[17px] font-medium leading-[1.4]">
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
        <p className="mt-3 text-[13px] text-muted">
          This does not mean the bill is fine. It means we found nothing to check it against.
          Each group below says which lines, and why.
        </p>
      )}
      <p className="mt-3 text-[13px] text-muted">
        {reading.lines_verified} of {reading.lines_total} lines read at high confidence;{' '}
        {RECONCILIATION[reading.reconciliation]}.
      </p>
      {/* "Verified by BOTH readers" is FALSE when only one ran, and the count
        * alone does not say which. Same bill on the deployed stack: 0 of 7
        * high-confidence with two readers, 4 of 7 with one. */}
      {reading.single_reader_lines > 0 && (
        <p className="mt-1 text-[11px] text-muted">
          {reading.single_reader_lines} of {reading.lines_total}{' '}
          {reading.single_reader_lines === 1 ? 'line was' : 'lines were'} seen by only one reader,
          so nothing cross-checked {reading.single_reader_lines === 1 ? 'it' : 'them'}. A single
          reader cannot disagree with itself — read the confidence above with that in mind.
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
      <p className="mt-1 text-[11px] text-muted">Reference: {report.reference_version}</p>

      <Teaser items={report.items} />

      <div className="mt-5 flex flex-col items-start gap-2 print:hidden">
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
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1">
          <button type="button" onClick={onWrong} className={btnText}>
            Something looks wrong
          </button>
          <button type="button" onClick={onNewBill} className={btnText}>
            Upload a different bill
          </button>
        </div>
      </div>
    </div>
  )
}


const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`

/** Five thin rows, name + chip, fading out: "there is more below". The real list is in the detailed block. */
function Teaser({ items }: { items: BillItem[] }) {
  if (items.length === 0) return null
  return (
    <div aria-hidden="true" className="report-teaser mt-5">
      {items.slice(0, 5).map((item) => (
        <div key={item.index} className="flex items-center justify-between gap-3">
          <span className="min-w-0 flex-1 truncate text-[11px] text-muted">
            <span className="mr-1.5 text-[10px]">Line {item.index}</span>
            {item.name}
          </span>
          <Chip tone={item.severity} size="s" className="shrink-0" />
        </div>
      ))}
    </div>
  )
}

// ---------- detailed analysis: five panels on an arc ----------

/** Plain, once per panel, never per row. */
const PANEL_TEXT = {
  no_public_ceiling:
    'These are services and items with no published ceiling price in India — they vary from hospital to hospital. We still checked them for duplication and arithmetic.',
  could_not_read:
    'We could not read these lines clearly enough to trust them, so we did not compare their prices. Check them against your paper bill.',
  fallback: 'Our two readers did not agree on these lines, so we left them out rather than guess. Nothing here has been compared.',
}

interface Panel {
  title: string
  items: BillItem[]
  evidence: boolean
  intro?: string
  /** Panel 5 groups by the reason the engine actually gave, so the sentence above a line is true of that line. */
  groups?: { reason: string; text: string; items: BillItem[] }[]
}

function buildPanels(items: BillItem[]): Panel[] {
  const gray = items.filter((i) => i.severity === 'gray')
  const known: GrayReason[] = ['no_public_ceiling', 'could_not_read']
  // The fallback bucket: gray with a reason we do not give a panel of its own. The adapter knows three
  // more reasons than the two panels above (could_not_identify, pack_size_unknown, not_cross_checked);
  // each keeps its own explanation here rather than being described as a reader disagreement.
  const other = gray.filter((i) => !known.includes(i.gray_reason as GrayReason))
  const reasons = [...new Set(other.map((i) => i.gray_reason ?? 'unknown'))]
  const groups = reasons.map((reason) => ({
    reason,
    text: (GRAY_EXPLANATION as Record<string, string>)[reason] ?? PANEL_TEXT.fallback,
    items: other.filter((i) => (i.gray_reason ?? 'unknown') === reason),
  }))
  return [
    { title: 'Worth asking about', items: items.filter((i) => i.severity === 'red' || i.severity === 'amber'), evidence: true },
    { title: 'Checked, no issue', items: items.filter((i) => i.severity === 'green'), evidence: true },
    { title: 'No published ceiling', items: gray.filter((i) => i.gray_reason === 'no_public_ceiling'), evidence: false, intro: PANEL_TEXT.no_public_ceiling },
    { title: 'Could not be read', items: gray.filter((i) => i.gray_reason === 'could_not_read'), evidence: false, intro: PANEL_TEXT.could_not_read },
    { title: 'Not identified', items: other, evidence: false, intro: undefined, groups },
  ]
}

/** matchMedia as state, for the <1100px stacked layout. */
function useStacked(): boolean {
  const [stacked, setStacked] = useState(() => matchMedia('(max-width: 1099.98px)').matches)
  useEffect(() => {
    const mq = matchMedia('(max-width: 1099.98px)')
    const on = () => setStacked(mq.matches)
    mq.addEventListener('change', on)
    window.addEventListener('resize', on)
    return () => {
      mq.removeEventListener('change', on)
      window.removeEventListener('resize', on)
    }
  }, [])
  return stacked
}

/**
 * Full-width block under the step row. Header toggles it; inside, an arc carousel of the five panels
 * (three visible, centre in focus) — or a plain stack below 1100px and in print.
 */
export function DetailedAnalysis({ report, open, onToggle }: { report: BillReport; open: boolean; onToggle: () => void }) {
  const panels = buildPanels(report.items)
  const [cur, setCur] = useState(0)
  const stacked = useStacked()
  const id = useId()
  // Entrance plays the first time the block opens, then never again (the class is dropped after it ends).
  const [entering, setEntering] = useState<'no' | 'yes' | 'done'>('no')
  useEffect(() => {
    if (open && entering === 'no') setEntering('yes')
  }, [open, entering])
  useEffect(() => {
    if (entering !== 'yes') return
    const t = window.setTimeout(() => setEntering('done'), 1200) // longest animation ends at 0.16 + 0.55s
    return () => clearTimeout(t)
  }, [entering])
  // Off-centre panels are absolutely positioned, so the track's height is the centre panel's own height —
  // which puts the Prev/Next column (top: 50%) at the vertical centre of the panel in focus.
  const trackRef = useRef<HTMLDivElement>(null)
  const centreRef = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const track = trackRef.current
    const centre = centreRef.current
    if (!track || !centre || stacked) {
      if (track) track.style.height = ''
      return
    }
    const fit = () => (track.style.height = `${centre.offsetHeight}px`)
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(centre)
    return () => ro.disconnect()
  }, [cur, stacked, report])
  const go = (n: number) => setCur(Math.max(0, Math.min(panels.length - 1, n)))
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      go(cur - 1)
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      go(cur + 1)
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={`${id}-body`}
        className={`flex w-full items-center gap-4 rounded-2xl py-2 print:hidden ${focusRing}`}
      >
        <span aria-hidden="true" className="w-5 shrink-0" /> {/* balances the chevron so the heading is truly centred */}
        <span className="flex-1 text-center text-[28px] font-bold leading-[1.2] tracking-[-0.5px]">Detailed analysis</span>
        <span aria-hidden="true" className={`flow-detail-chevron shrink-0 ${open ? 'is-open' : ''}`}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </span>
      </button>

      <div id={`${id}-body`} className={`flow-detail-body ${open ? 'is-open' : ''}`}>
        <div className={`flow-detail-inner flow-detail-surface ${entering === 'yes' ? 'is-entering' : ''}`}>
          <div
            className={`arc ${stacked ? 'is-stacked' : ''}`}
            tabIndex={stacked ? -1 : 0}
            onKeyDown={stacked ? undefined : onKey}
            role="group"
            aria-roledescription="carousel"
            aria-label="Detailed analysis, five panels"
          >
            <div ref={trackRef} className="arc-track">
              {panels.map((p, i) => {
                const d = i - cur
                const pos = stacked ? '' : d === 0 ? 'is-centre' : d === -1 ? 'is-left' : d === 1 ? 'is-right' : d < 0 ? 'is-far-left' : 'is-far-right'
                const off = !stacked && d !== 0
                return (
                  <section
                    key={p.title}
                    ref={d === 0 ? centreRef : undefined}
                    className={`arc-panel flow-detail-col ${pos}`}
                    aria-hidden={off || undefined}
                    inert={off || undefined}
                    aria-labelledby={`${id}-p${i}`}
                  >
                    <div className="arc-panel-inner">
                      <PanelBody panel={p} headingId={`${id}-p${i}`} />
                    </div>
                  </section>
                )
              })}
            </div>
            {!stacked && (
              <div className="arc-controls print:hidden">
                <button type="button" onClick={() => go(cur - 1)} disabled={cur === 0} aria-label="Previous panel" className={`arc-btn ${focusRing}`}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M15 6l-6 6 6 6" />
                  </svg>
                </button>
                <button type="button" onClick={() => go(cur + 1)} disabled={cur === panels.length - 1} aria-label="Next panel" className={`arc-btn ${focusRing}`}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M9 6l6 6-6 6" />
                  </svg>
                </button>
              </div>
            )}
            <p aria-live="polite" className="sr-only">
              {stacked ? '' : `Panel ${cur + 1} of ${panels.length}, ${panels[cur].title}`}
            </p>
          </div>

          <footer className="mt-8 hidden border-t border-ink/10 pt-4 text-xs text-muted print:block">
            Reference: {report.reference_version}. Ceilings are compared as published on that date. This report is
            information to help you ask questions about a bill; it is not legal or medical advice. Prepared with BillWise.
          </footer>
        </div>
      </div>
    </div>
  )
}

function PanelBody({ panel, headingId }: { panel: Panel; headingId: string }) {
  const empty = panel.items.length === 0
  return (
    <>
      <h3 id={headingId} className="text-[16px] font-bold tracking-tight">
        {panel.title} <span className="font-normal text-muted">({panel.items.length})</span>
      </h3>
      {panel.intro && <p className="mt-2 text-[12px] leading-[1.5] text-muted">{panel.intro}</p>}
      <div className="mt-3">
        {empty ? (
          <p className="text-[13px] text-muted">{panel.evidence ? 'Nothing here.' : 'Nothing here — every line was accounted for.'}</p>
        ) : panel.evidence ? (
          <ul className="space-y-2">
            {panel.items.map((item) => (
              <li key={item.index}>
                <FindingCard item={item} />
              </li>
            ))}
          </ul>
        ) : panel.groups && panel.groups.length > 0 ? (
          panel.groups.map((g, i) => (
            <div key={g.reason} className={i > 0 ? 'mt-5' : ''}>
              <p className="text-[12px] leading-[1.5] text-muted">{g.text}</p>
              <Rows items={g.items} />
            </div>
          ))
        ) : (
          <Rows items={panel.items} />
        )}
      </div>
    </>
  )
}

/** One row per item: line, name, amount. The name wraps; the amount never shrinks into it. */
function Rows({ items }: { items: BillItem[] }) {
  return (
    <ul className="mt-1 divide-y divide-ink/10">
      {items.map((item) => (
        <li key={item.index} className="flex items-baseline gap-x-3 py-1.5">
          <span className="shrink-0 text-[11px] font-medium text-muted">Line {item.index}</span>
          <span className="min-w-0 flex-[1_1_auto] truncate text-[13px] font-medium">{item.name}</span>
          <span className="shrink-0 whitespace-nowrap pl-3 text-[13px] tabular-nums">{formatINR(item.amount)}</span>
        </li>
      ))}
    </ul>
  )
}

/** The published ceiling as the engine states it: per unit, before GST — only when the field is there. */
function ceilingRow(item: BillItem): { label: string; value: string } | null {
  const ev = item.evidence ?? {}
  const unit = typeof ev.ceiling_unit === 'string' ? ev.ceiling_unit : 'unit'
  if (typeof ev.ceiling_ex_gst === 'string') return { label: `Ceiling per ${unit}, before GST`, value: ev.ceiling_ex_gst }
  if (typeof ev.allowance_per_unit === 'string') return { label: `Allowance per ${unit}, with GST`, value: ev.allowance_per_unit }
  return null
}

/** Two lines per finding: name + chip, then the figures + the evidence link. Figures verbatim from the API. */
function FindingCard({ item }: { item: BillItem }) {
  const accent =
    item.severity === 'red' ? 'border-l-red-700' : item.severity === 'amber' ? 'border-l-amber-400' : item.severity === 'green' ? 'border-l-green-700' : 'border-l-transparent'
  const ceiling = ceilingRow(item)
  const affected = item.amount_affected && item.amount_affected !== '0' && item.amount_affected !== '0.00'
  return (
    <article className={`rounded-xl border border-ink/10 border-l-4 px-4 py-3 ${accent}`} aria-labelledby={`item-${item.index}`}>
      <div className="flex items-center justify-between gap-3">
        <h4 id={`item-${item.index}`} className="min-w-0 truncate text-[15px] font-semibold leading-snug">
          <span className="text-muted">Line {item.index}</span> · {item.name}
        </h4>
        <Chip tone={item.severity} size="s" className="shrink-0" />
      </div>
      <Evidence item={item}>
        <span className="text-[13px] leading-snug">
          Billed <span className="tabular-nums">{formatINR(item.amount)}</span>
          {ceiling && (
            <>
              {' · '}
              <span title={ceiling.label}>Ceiling</span> <span className="tabular-nums">{formatINR(ceiling.value)}</span>
            </>
          )}
          {affected && (
            <>
              {' · '}Difference <span className="font-semibold tabular-nums">{formatINR(item.amount_affected!)}</span>
            </>
          )}
        </span>
      </Evidence>
    </article>
  )
}

/** Three one-line rows at most, only from fields the API sent. (rule_id and match tier were shown here until 2026-09-20 — see the change log.) */
function evidenceRows(item: BillItem): { dt: string; dd: string }[] {
  const ev = item.evidence ?? {}
  const ref = (ev.reference && typeof ev.reference === 'object' ? (ev.reference as Record<string, unknown>) : {}) as Record<string, unknown>
  const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : null)
  const rows: { dt: string; dd: string }[] = []
  const what = [str(ref.formulation), str(ref.strength)].filter(Boolean).join(', ')
  if (what) rows.push({ dt: 'What it is', dd: what })
  const c = ceilingRow(item)
  if (c) rows.push({ dt: 'The ceiling', dd: `${formatINR(c.value)} ${c.label.replace(/^w+/, (w) => w.toLowerCase())}` })
  const so = str(ref.so_number) ?? str(ev.so_number)
  const soDate = str(ref.so_date) ?? str(ev.so_date)
  if (so) rows.push({ dt: 'Where that comes from', dd: `NPPA order S.O. ${so}${soDate ? `, ${soDate}` : ''}` })
  return rows.slice(0, 3)
}

function Evidence({ item, children }: { item: BillItem; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const rows = evidenceRows(item)
  const notes = item.notes ?? []
  const has = !!item.headline || rows.length > 0 || notes.length > 0
  return (
    <div className="mt-1">
      <div className="flex items-baseline justify-between gap-3">
        {children}
        {has && (
          <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)} className={`${btnLink} shrink-0 px-0 py-0 text-[12px] print:hidden`}>
            {open ? 'Hide evidence' : 'Show evidence'}
          </button>
        )}
      </div>
      {!has && null}
      <div id={id} className={`mt-2 rounded-xl bg-surface p-3 text-[13px] leading-[1.5] ${open && has ? '' : 'hidden'} ${has ? 'print:block' : ''}`}>
        {/* Price rules (R5) already say everything in the rows below; for the others the headline IS the explanation. */}
        {item.headline && rows.length < 2 && <p className={rows.length > 0 ? 'mb-2' : ''}>{item.headline}</p>}
        {rows.length > 0 && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
            {rows.map((r) => (
              <div key={r.dt} className="contents">
                <dt className="text-muted">{r.dt}</dt>
                <dd className="min-w-0 break-words">{r.dd}</dd>
              </div>
            ))}
          </dl>
        )}
        {notes.length > 0 && (
          <div className={rows.length > 0 || item.headline ? 'mt-2 border-t border-ink/10 pt-2' : ''}>
            {notes.map((n, i) => (
              <p key={i}>{n}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
