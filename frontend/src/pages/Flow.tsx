import { Fragment, useCallback, useEffect, useRef, useState, type CSSProperties, type ChangeEvent, type Dispatch, type DragEvent, type KeyboardEvent, type MouseEvent, type ReactNode, type RefObject, type SetStateAction } from 'react'
import {
  SAMPLE_BILL_ID,
  confirmBill,
  createBill,
  createSampleBill,
  getBill,
  updateItems,
  type ApiError,
  type BillReport,
  type ItemCorrection,
  type Severity,
} from '../lib/api'
import { Lockup } from '../Logo'
import { formatINR } from '../lib/money'
import billIllustration from '../../public/bill-illustration.svg?raw'
import runnerSvg from '../../public/runner.svg?raw'

// Frame b ships hidden inline; the gait animation drives both frames by opacity instead.
const RUNNER = runnerSvg.replace(' style="display:none"', '')
import Letter from './Letter'
import Report, { ReportDetail } from './Report'
import { Chip, CHIP_LABEL } from '../Chip'

export const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-bg'
const btnPrimary = `rounded-full bg-ink px-6 py-3 text-base font-medium text-white transition-opacity disabled:opacity-40 ${focusRing}`
const btnSecondary = `rounded-full border border-ink/20 bg-card px-6 py-3 text-base font-medium transition-colors hover:border-ink disabled:opacity-40 ${focusRing}`

type StepNo = 1 | 2 | 3 | 4
// Per-step accents: deliberately outside the verdict palette (red/amber/green/gray) so a step never reads as a verdict.
const ACCENT: Record<StepNo, string> = { 1: '#4A5B8C', 2: '#6B4A6B', 3: '#8C5A3C', 4: '#4A5560' }

const STEPS: { n: StepNo; title: string }[] = [
  { n: 1, title: 'Upload' },
  { n: 2, title: 'Check the reading' },
  { n: 3, title: 'Report' },
  { n: 4, title: 'Letter' },
]

/**
 * 4 MB, NOT 10 -- AND THE CEILING IS NOT OURS TO CHOOSE.
 *
 * API Gateway base64-encodes a binary body into the Lambda invocation event,
 * which inflates it by about a third, and Lambda caps a synchronous event at
 * 6 MB. So roughly 4.5 MB of file is the real ceiling, whatever we claim.
 *
 * Measured against the deployed stack 2026-09-20: 4 MB reached our code,
 * 5 MB and 8 MB came back 413 from the gateway.
 *
 * THE 413 IS GENERATED BEFORE OUR CODE RUNS, so it carries no CORS headers,
 * so the browser cannot read it and reports a bare "Network error" instead.
 * A user with a normal phone photo saw a network failure for a file we had
 * just told them was within the limit.
 *
 * Advertising a limit the infrastructure will not honour is the same class of
 * problem as the rest of this project: stating something we cannot back.
 */
const MAX_BYTES = 4 * 1024 * 1024

/** Drop a forced ?mock= state so the mock sequence can advance. No-op without one. */
/**
 * Read ONCE, at module load, before anything can rewrite the URL.
 *
 * Reading it at click time returned null: the landing-to-flow transition
 * rewrites history and the query string is gone by then. A demo switch has to
 * survive the app's own navigation, so it is captured up front.
 */
const FIXTURE_PARAM = new URLSearchParams(window.location.search).get('fixture')

function clearMockParam() {
  if (new URLSearchParams(window.location.search).has('mock')) history.replaceState(history.state, '', window.location.pathname)
}
const mb = (bytes: number) => (bytes / (1024 * 1024)).toFixed(1)
const fileSize = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${mb(bytes)} MB`)

/** Returns an error message, or null if the file may be uploaded. */
export function validateFile(file: File): string | null {
  const isImage = file.type.startsWith('image/')
  const isPdf = file.type === 'application/pdf'
  if (!isImage && !isPdf) {
    const ext = file.name.includes('.') ? `.${file.name.split('.').pop()}` : 'that'
    return `We can't read ${ext} files. Please upload a photo (JPG, PNG, HEIC) or a PDF.`
  }
  if (file.size === 0) return 'That file is empty. Please choose another one.'
  if (file.size > MAX_BYTES) return `This file is ${mb(file.size)} MB. The limit is 4 MB — try a smaller photo, or a compressed PDF.`
  return null
}

type UploadState =
  | { kind: 'idle'; error?: string }
  | { kind: 'uploading'; progress: number }
  | { kind: 'error'; error: ApiError }
  | { kind: 'done' }

interface Props {
  initialFile: File | null
  onDone: () => void
}

export default function Flow({ initialFile, onDone }: Props) {
  const mockParam = new URLSearchParams(window.location.search).get('mock')
  const startAtReview = !!mockParam

  const [active, setActive] = useState<StepNo>(startAtReview ? 2 : 1)
  const [reached, setReached] = useState<StepNo>(startAtReview ? 2 : 1)
  const [file, setFile] = useState<File | null>(initialFile)
  const [upload, setUpload] = useState<UploadState>(startAtReview ? { kind: 'done' } : { kind: 'idle' })
  const [billId, setBillId] = useState<string | null>(startAtReview ? SAMPLE_BILL_ID : null)
  const [report, setReport] = useState<BillReport | null>(null)
  const [corrections, setCorrections] = useState<Record<number, ItemCorrection>>({})
  const [letterText, setLetterText] = useState('')
  const [correctionsSaved, setCorrectionsSaved] = useState(false)

  // Step changes go through history so the browser back button walks the steps.
  const goStep = useCallback((n: StepNo) => {
    history.pushState({ page: 'flow', step: n }, '', window.location.pathname + window.location.search)
    setActive(n)
    setReached((r) => (n > r ? n : r))
  }, [])
  useEffect(() => {
    history.replaceState({ ...history.state, page: 'flow', step: active }, '', window.location.pathname + window.location.search)
    const onPop = (e: PopStateEvent) => {
      if (e.state?.page === 'flow' && e.state.step) setActive(e.state.step as StepNo)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // ----- step 1: upload -----
  const startUpload = useCallback(
    async (f: File) => {
      const err = validateFile(f)
      if (err) {
        setUpload({ kind: 'idle', error: err })
        return
      }
      setFile(f)
      setReport(null)
      setCorrections({})
      setCorrectionsSaved(false)
      setBillId(null)
      clearMockParam() // a fresh upload follows the real sequence, not a forced state
      setUpload({ kind: 'uploading', progress: 0 })
      const res = await createBill(f, (p) => setUpload({ kind: 'uploading', progress: p }))
      if (!res.ok) {
        setUpload({ kind: 'error', error: res.error })
        return
      }
      setUpload({ kind: 'done' })
      setBillId(res.data.bill_id)
      goStep(2)
    },
    [goStep],
  )

  /**
   * Run a bundled demo bill instead of uploading one.
   *
   * There was no sample path in the original contract, and local mode has no
   * OCR at all -- so on a machine without AWS credentials there was nothing
   * that worked, which is the first thing anyone tries.
   */
  const startSample = useCallback(async () => {
    setFile(null)
    setReport(null)
    setCorrections({})
    setCorrectionsSaved(false)
    setBillId(null)
    clearMockParam()
    setUpload({ kind: 'uploading', progress: 1 })
    // ?fixture=bill_06 runs the retail-pharmacy layout, which is the one
    // worth showing: nothing on it is price-controlled, so it exercises the
    // "we could not compare any of these" path rather than the happy one.
    const res = await createSampleBill(FIXTURE_PARAM ?? undefined)
    if (!res.ok) {
      setUpload({ kind: 'error', error: res.error })
      return
    }
    setUpload({ kind: 'done' })
    setBillId(res.data.bill_id)
    goStep(2)
  }, [goStep])

  // A file dropped on the landing page starts uploading immediately.
  const autoStarted = useRef(false)
  useEffect(() => {
    if (initialFile && !autoStarted.current) {
      autoStarted.current = true
      void startUpload(initialFile)
    }
  }, [initialFile, startUpload])

  // ----- step 2: polling -----
  // Advance happens once, when a ready report arrives — never in an effect, so browser back can revisit step 2.
  const onPolled = useCallback(
    (r: BillReport) => {
      setReport(r)
      if (r.status === 'ready') goStep(3)
    },
    [goStep],
  )
  const poll = usePoll(billId, active === 2 && upload.kind === 'done' && report?.status !== 'ready', onPolled)

  const [submit, setSubmit] = useState<{ kind: 'idle' } | { kind: 'busy' } | { kind: 'error'; error: ApiError; retry: () => void }>({ kind: 'idle' })

  const doConfirm = useCallback(async () => {
    if (!billId) return
    if (report?.status === 'ready') return goStep(3) // revisiting a finished reading
    clearMockParam()
    setSubmit({ kind: 'busy' })
    const res = await confirmBill(billId)
    if (!res.ok) return setSubmit({ kind: 'error', error: res.error, retry: doConfirm })
    setSubmit({ kind: 'idle' })
    onPolled(res.data)
    if (res.data.status !== 'ready') poll.resume()
  }, [billId, report?.status, goStep, onPolled, poll])

  const doSave = useCallback(async () => {
    if (!billId) return
    clearMockParam()
    setSubmit({ kind: 'busy' })
    const res = await updateItems(billId, Object.values(corrections))
    if (!res.ok) return setSubmit({ kind: 'error', error: res.error, retry: doSave })
    setSubmit({ kind: 'idle' })
    setCorrectionsSaved(true)
    onPolled(res.data)
    if (res.data.status !== 'ready') poll.resume()
  }, [billId, corrections, onPolled, poll])

  const unreadable = report?.items.filter((i) => i.gray_reason === 'could_not_read') ?? []


  // Is the active step busy? Drives the animated connector leaving it.
  const working: Record<StepNo, boolean> = {
    1: upload.kind === 'uploading',
    2: active === 2 && !poll.error && !poll.timedOut && (!report || report.status === 'processing' || submit.kind === 'busy'),
    3: false,
    4: false,
  }

  // Completion effect, once: fires on the step just left behind when a new step is reached.
  const [justDone, setJustDone] = useState<StepNo | 0>(0)
  const prevReached = useRef(reached)
  useEffect(() => {
    if (reached > prevReached.current) {
      setJustDone(prevReached.current)
      const t = setTimeout(() => setJustDone(0), 700)
      prevReached.current = reached
      return () => clearTimeout(t)
    }
    prevReached.current = reached
  }, [reached])

  // Content cross-fade: `shown` lags `active` by the 0.2s fade-out (skipped when motion is reduced).
  const [shown, setShown] = useState<StepNo>(active)
  const [leaving, setLeaving] = useState(false)
  useEffect(() => {
    if (shown === active) return
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return setShown(active)
    setLeaving(true)
    const t = setTimeout(() => {
      setShown(active)
      setLeaving(false)
    }, 200)
    return () => clearTimeout(t)
  }, [active, shown])

  return (
    <main className="mx-auto w-full max-w-[1480px] px-5 py-10 sm:py-14">
      <header className="mb-10 flex items-center justify-between print:hidden">
        <Lockup />
        <button type="button" onClick={onDone} className={`rounded-full px-2 text-[19px] font-bold text-ink transition-opacity duration-200 [transition-timing-function:ease] hover:opacity-65 ${focusRing}`}>
          Home
        </button>
      </header>

      <ol className="flow-steps list-none">
        {STEPS.map(({ n, title }, i) => {
          const state: StepState = n === active ? 'active' : n <= reached ? 'done' : 'todo'
          // Visibility ladder: distance ahead of the active step, only for steps not yet reached —
          // completed steps stay fully visible and interactive when the user has gone back.
          const ahead = n > reached ? Math.min(3, n - active) : 0
          const ladder = ahead ? `is-ahead-${ahead}` : ''
          const mounted = n <= reached // never render a step's real content before it is reached
          const prev = STEPS[i - 1]?.n
          const prevState: StepState | null = prev ? (prev === active ? 'active' : prev <= reached ? 'done' : 'todo') : null
          const arrow = !prev ? null : prevState === 'done' ? 'is-complete' : prevState === 'active' && working[prev] ? 'is-working' : ''
          return (
            <Fragment key={n}>
              {prev && (
                <li aria-hidden="true" className={`flow-arrow ${arrow} ${ladder} print:hidden`} style={{ '--accent': ACCENT[prev] } as CSSProperties}>
                  <ArrowSvg id={`arrow-${n}`} />
                  {arrow === 'is-working' && <span aria-hidden="true" className="flow-runner" dangerouslySetInnerHTML={{ __html: RUNNER }} />}
                </li>
              )}
              <li
                className={`flow-step is-${state} ${ladder} ${n === 1 ? 'is-upload' : ''} ${justDone === n ? 'is-just-done' : ''} ${n === 3 ? 'print-report' : n === 4 ? 'print-letter-page print:hidden' : 'print:hidden'}`}
                aria-current={state === 'active' ? 'step' : undefined}
                aria-hidden={ahead ? 'true' : undefined}
                style={{ '--accent': ACCENT[n] } as CSSProperties}
                onClick={state === 'done' ? () => goStep(n) : undefined}
              >
                {(state === 'active' && working[n]) || justDone === n ? <Trace /> : null}
                <StepHead n={n} title={title} state={state} onOpen={() => goStep(n)} />
                {state === 'done' && (
                  <div className="flow-done print:hidden">
                    {n === 1 && <UploadDone file={file} mock={!!mockParam} onReplace={() => goStep(1)} />}
                    {n === 2 && report && (
                      <ReviewDone reading={report.reading} corrected={correctionsSaved ? Object.keys(corrections).length : 0} />
                    )}
                    {n === 3 && report && <ReportDone summary={report.summary} />}
                    {n === 4 && <LetterDone text={letterText} />}
                  </div>
                )}
                {mounted && (
                  <div
                    id={`step-${n}-body`}
                    className={`flow-body ${n === shown ? 'is-shown' : ''} ${n === shown && leaving ? 'is-leaving' : ''} ${n === 3 || n === 4 ? 'print:block' : ''}`}
                  >
                    <StepBody replay={n === shown ? active : 0}>
                      {n === 1 && (
                        <UploadStep
                          state={upload}
                          file={file}
                          onPick={startUpload}
                          onSample={startSample}
                          onRetry={() => file && startUpload(file)}
                        />
                      )}
                      {n === 2 && (
                        <ReviewStep
                          report={report}
                          poll={poll}
                          unreadable={unreadable}
                          corrections={corrections}
                          setCorrections={setCorrections}
                          submit={submit}
                          onConfirm={doConfirm}
                          onSave={doSave}
                        />
                      )}
                      {n === 3 && report && (
                        <Report report={report} onLetter={() => goStep(4)} onWrong={() => goStep(2)} onNewBill={() => goStep(1)} />
                      )}
                      {n === 4 && billId && <Letter billId={billId} onDone={onDone} onText={setLetterText} />}
                    </StepBody>
                  </div>
                )}
              </li>
            </Fragment>
          )
        })}
      </ol>

      {/* Report detail: full width under the row, tied to the report column by a down arrow. Rendered only while step 3 is active. */}
      {active === 3 && report && (
        <>
          <div aria-hidden="true" className="flow-ghost print:hidden">
            {STEPS.map(({ n }, i) => (
              <Fragment key={n}>
                {i > 0 && <span className="flow-ghost-gap" />}
                <span className={`flow-ghost-cell ${n === 3 ? 'is-active' : n < 3 ? 'is-done' : ''}`}>
                  {n === 3 && (
                    <span className="flow-arrow is-complete is-down">
                      <ArrowSvg id="arrow-detail" />
                    </span>
                  )}
                </span>
              </Fragment>
            ))}
          </div>
          <section aria-label="Report details" className="flow-detail print-report">
            <ReportDetail report={report} />
          </section>
        </>
      )}
    </main>
  )
}

// ---------- polling ----------

interface Poll {
  error: ApiError | null
  timedOut: boolean
  resume: () => void
}

/** Every 2s; 5s after 30s; gives up at 3 minutes. resume() restarts the clock. */
function usePoll(billId: string | null, enabled: boolean, onReport: (r: BillReport) => void): Poll {
  const [error, setError] = useState<ApiError | null>(null)
  const [timedOut, setTimedOut] = useState(false)
  const [epoch, setEpoch] = useState(0)

  useEffect(() => {
    if (!billId || !enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const startedAt = Date.now()
    setTimedOut(false)
    setError(null)

    const tick = async () => {
      const res = await getBill(billId)
      if (cancelled) return
      if (!res.ok) {
        setError(res.error)
        return
      }
      onReport(res.data)
      if (res.data.status === 'processing') {
        const elapsed = Date.now() - startedAt
        if (elapsed >= 180_000) return setTimedOut(true)
        timer = setTimeout(tick, elapsed >= 30_000 ? 5000 : 2000)
      }
    }
    void tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [billId, enabled, epoch, onReport])

  const resume = useCallback(() => setEpoch((e) => e + 1), [])
  return { error, timedOut, resume }
}

// ---------- panels ----------

type StepState = 'active' | 'done' | 'todo'

const ICONS: Record<StepNo, ReactNode> = {
  1: <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" />,
  2: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4.3-4.3" />
    </>
  ),
  3: <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8zM14 3v5h5M9 13h6M9 17h6" />,
  4: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </>
  ),
}

function Circle({ n, state }: { n: StepNo; state: StepState }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full transition-colors ${
        state === 'todo' ? 'border border-ink/30 text-muted' : state === 'active' ? 'flow-circle-active text-white' : 'bg-[#141414] text-white'
      }`}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={state === 'done' ? 3 : 2} strokeLinecap="round" strokeLinejoin="round">
        {state === 'done' ? <path d="M5 12l5 5L20 7" /> : ICONS[n]}
      </svg>
    </span>
  )
}

/** Connector: gradient track + chevron. The gradient id must be unique per arrow — its stops resolve currentColor at the defining SVG. */
function ArrowSvg({ id }: { id: string }) {
  return (
    <svg className="flow-arrow-svg" width="120" height="24" viewBox="0 0 120 24" aria-hidden="true" fill="none">
      <defs>
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="120" y2="0">
          <stop offset="0" stopColor="currentColor" stopOpacity="0" />
          <stop offset="1" stopColor="currentColor" />
        </linearGradient>
      </defs>
      <line className="flow-arrow-track" x1="1" y1="12" x2="114" y2="12" stroke={`url(#${id})`} strokeWidth="2" strokeLinecap="round" />
      <path className="flow-arrow-head" d="M108 5l7 7-7 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Travelling border while a step works; draws in solid when it completes. pathLength=100 makes the dash math unit-free. */
function Trace() {
  return (
    <svg aria-hidden="true" className="flow-trace">
      <rect className="flow-trace-base" width="100%" height="100%" rx="23" />
      <rect className="flow-trace-run" width="100%" height="100%" rx="23" pathLength={100} />
    </svg>
  )
}

/** Circle + title. Completed columns are one button (circle, title, result line) that goes back; upcoming ones are the placeholder. */
function StepHead({ n, title, state, onOpen }: { n: StepNo; title: string; state: StepState; onOpen: () => void }) {
  const inner = (
    <>
      <Circle n={n} state={state} />
      <h2 id={`step-${n}-h`} className="flow-title min-w-0 flex-1 font-bold tracking-tight">
        <span className="sr-only">Step {n}: </span>
        {title}
      </h2>
    </>
  )
  if (state === 'done') {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation() // the whole card is clickable too
          onOpen()
        }}
        aria-label={`Go back to step ${n}, ${title}`}
        className={`flow-head flex w-full items-center gap-4 rounded-2xl text-left ${focusRing}`}
      >
        {inner}
      </button>
    )
  }
  return <div className="flow-head flex items-center gap-4 print:hidden">{inner}</div>
}

// ---------- completed-card bodies: each step's own result, nothing computed ----------

const RECONCILIATION_SHORT: Record<BillReport['reading']['reconciliation'], string> = {
  reconciled: 'Totals reconciled',
  mismatch: "Totals don't match",
  // Not a mismatch: the printed total is BELOW the line sum, which is a
  // discount or round-off we could not read. The patient is being asked for
  // less than the bill itemises, so there is nothing to query.
  below_line_sum: 'Total below line items',
  no_total_found: 'No printed total',
}

const doneLink = `rounded px-1 text-[13px] text-muted underline underline-offset-4 hover:text-ink ${focusRing}`

/** "WhatsApp_Imag….jpeg": the head truncates with an ellipsis, the extension never does. */
function MiddleEllipsis({ name }: { name: string }) {
  const dot = name.lastIndexOf('.')
  const keep = dot > 0 ? Math.min(name.length - dot, 6) : 0
  return (
    <span className="flex max-w-full text-sm font-semibold" title={name}>
      <span className="min-w-0 truncate">{name.slice(0, name.length - keep)}</span>
      <span className="shrink-0">{name.slice(name.length - keep)}</span>
    </span>
  )
}

function DocTile() {
  return (
    <div aria-hidden="true" className="flex h-[120px] w-full items-center justify-center rounded-xl border border-line bg-surface text-muted">
      <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8zM14 3v5h5M9 13h6M9 17h6" />
      </svg>
    </div>
  )
}

function UploadDone({ file, mock, onReplace }: { file: File | null; mock: boolean; onReplace: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!file || !file.type.startsWith('image/')) return setUrl(null)
    const u = URL.createObjectURL(file)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [file])
  const type = file ? (file.type.split('/')[1] || file.name.slice(file.name.lastIndexOf('.') + 1)).toUpperCase() : ''
  return (
    <>
      {url ? (
        <img src={url} alt="" className="max-h-[180px] w-full rounded-xl border border-line object-cover" />
      ) : (
        <DocTile />
      )}
      {file ? <MiddleEllipsis name={file.name} /> : mock ? <span className="text-sm font-semibold">Mock bill</span> : null}
      {file && (
        <span className="text-[13px] text-muted">
          {fileSize(file.size)} · {type}
        </span>
      )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onReplace()
        }}
        className={doneLink}
      >
        Replace
      </button>
    </>
  )
}

function ReviewDone({ reading, corrected }: { reading: BillReport['reading']; corrected: number }) {
  return (
    <>
      <span className="text-sm font-semibold">
        {reading.lines_verified} of {reading.lines_total} lines read at high confidence
      </span>
      <span className="text-[13px] text-muted">{RECONCILIATION_SHORT[reading.reconciliation]}</span>
      {corrected > 0 && (
        <span className="text-[13px] text-muted">
          {corrected} {corrected === 1 ? 'line' : 'lines'} corrected
        </span>
      )}
    </>
  )
}

function ReportDone({ summary }: { summary: BillReport['summary'] }) {
  const rows: { tone: Severity; label: string; count: number }[] = [
    { tone: 'red', label: CHIP_LABEL.red, count: summary.above_ceiling },
    { tone: 'amber', label: CHIP_LABEL.amber, count: summary.needs_clarification },
    { tone: 'green', label: CHIP_LABEL.green, count: summary.within_ceiling },
    { tone: 'gray', label: 'No published ceiling', count: summary.no_public_ceiling },
    { tone: 'gray', label: 'Could not be read', count: summary.could_not_read },
  ]
  return (
    <>
      <ul className="flex w-full flex-col gap-2">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center justify-between gap-2 text-[13px]">
            {/* labels may wrap inside the pill: the column is narrow and the label must stay whole */}
            <Chip tone={row.tone} label={row.label} className="whitespace-normal text-left leading-snug" />
            <span className="tabular-nums font-semibold">{row.count}</span>
          </li>
        ))}
      </ul>
      <span className="mt-1 text-[13px] text-muted">Amount affected</span>
      <span className="-mt-2 text-sm font-semibold">{formatINR(summary.total_amount_affected)}</span>
    </>
  )
}

function LetterDone({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async (e: MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked: the full letter is one click away on step 4 */
    }
  }
  return (
    <>
      <span className="text-sm font-semibold">{text ? 'Letter ready' : 'Not written yet'}</span>
      {text && <span className="text-[13px] text-muted">{text.slice(0, 60).trimEnd()}…</span>}
      {text && (
        <button type="button" onClick={copy} className={doneLink}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      )}
    </>
  )
}

/** Fades/rises in whenever `replay` changes — without remounting, so step state (letter text, open groups) survives. */
function StepBody({ replay, children }: { replay: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.classList.remove('is-in')
    void el.offsetWidth // restart the transition from the hidden state
    const id = requestAnimationFrame(() => el.classList.add('is-in'))
    return () => cancelAnimationFrame(id)
  }, [replay])
  return (
    <div ref={ref} className="flow-body-inner">
      {children}
    </div>
  )
}

// ---------- step 1 ----------

function UploadStep({
  state,
  file,
  onPick,
  onSample,
  onRetry,
}: {
  state: UploadState
  file: File | null
  onPick: (f: File) => void
  onSample: () => void
  onRetry: () => void
}) {
  const [over, setOver] = useState(false)
  const pickRef = useRef<HTMLInputElement>(null)
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = '' // allow re-picking the same file after an error
    if (f) onPick(f)
  }
  const idle = state.kind === 'idle' || state.kind === 'done' // a finished upload can be replaced from step 1
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const f = e.dataTransfer.files[0]
    if (f) onPick(f) // startUpload validates and reports to state.error
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return // let the buttons inside handle their own keys
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      pickRef.current?.click()
    }
  }

  let content: ReactNode
  if (state.kind === 'uploading') {
    const pct = Math.round(state.progress * 100)
    content = (
      <div className="w-full max-w-md">
        <p className="text-sm text-muted">Uploading {file?.name}…</p>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-card" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Upload progress">
          <div className="h-full bg-ink transition-[width]" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-2 text-right text-xs text-muted">{pct}%</p>
      </div>
    )
  } else if (state.kind === 'error') {
    content = (
      <div className="w-full max-w-md">
        <p role="alert" className="rounded-2xl border border-ink/20 bg-card px-4 py-3 text-sm">
          The upload didn't go through ({state.error.message}). Your file is still here.
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-3">
          <button type="button" onClick={onRetry} className={btnPrimary}>
            Try again
          </button>
          <FilePicker label="Choose a different file" accept="image/*,application/pdf" onChange={pick} secondary />
        </div>
      </div>
    )
  } else {
    content = (
      <>
        <div className="flex flex-col gap-3 sm:flex-row">
          <FilePicker label="Take a photo" accept="image/*" capture="environment" onChange={pick} />
          <FilePicker label="Choose a file" accept="image/*,application/pdf" onChange={pick} inputRef={pickRef} secondary />
        </div>
        <p className="mt-4 text-sm text-muted">or drop a photo or PDF here</p>
        <p className="mt-4 text-sm text-muted">
          No bill to hand?{' '}
          <button
            type="button"
            onClick={onSample}
            className={`rounded px-1 font-semibold text-ink underline underline-offset-4 ${focusRing}`}
          >
            Try a sample bill
          </button>
        </p>
        <ul className="mt-4 flex flex-wrap justify-center gap-2" aria-label="Accepted formats">
          {['JPG', 'PNG', 'PDF', 'Up to 4 MB'].map((c) => (
            <li key={c} className="rounded-full border border-line bg-card px-2.5 py-1 text-xs font-medium text-muted">
              {c}
            </li>
          ))}
        </ul>
        {state.kind === 'idle' && state.error && (
          <p role="alert" className="mt-5 max-w-md rounded-2xl border border-ink/20 bg-card px-4 py-3 text-sm">
            {state.error}
          </p>
        )}
      </>
    )
  }

  return (
    <div>
      <p className="text-muted">A photo or PDF of the bill, up to 4 MB. Clear, flat and well lit reads best.</p>
      <div
        className={`flow-drop ${over ? 'is-over' : ''}`}
        role="group"
        aria-label="Upload a bill: drop a photo or PDF here, or press Enter to choose a file"
        tabIndex={idle ? 0 : -1}
        onKeyDown={idle ? onKey : undefined}
        onDragOver={
          idle
            ? (e) => {
                e.preventDefault()
                setOver(true)
              }
            : undefined
        }
        onDragLeave={idle ? () => setOver(false) : undefined}
        onDrop={idle ? onDrop : undefined}
      >
        <div aria-hidden="true" className="flow-drop-art bill-illustration" dangerouslySetInnerHTML={{ __html: billIllustration }} />
        <div className="relative flex flex-col items-center text-center">{content}</div>
      </div>
    </div>
  )
}

function FilePicker({
  label,
  accept,
  capture,
  onChange,
  inputRef,
  secondary,
}: {
  label: string
  accept: string
  capture?: 'environment'
  onChange: (e: ChangeEvent<HTMLInputElement>) => void
  inputRef?: RefObject<HTMLInputElement | null>
  secondary?: boolean
}) {
  // The input itself is the focusable control; the label is styled as the button.
  return (
    <label className={`relative inline-flex cursor-pointer items-center justify-center has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ink has-[:focus-visible]:ring-offset-2 ${secondary ? btnSecondary : btnPrimary}`}>
      <input ref={inputRef} type="file" accept={accept} capture={capture} onChange={onChange} className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
      {label}
    </label>
  )
}

// ---------- step 2 ----------

function ReviewStep({
  report,
  poll,
  unreadable,
  corrections,
  setCorrections,
  submit,
  onConfirm,
  onSave,
}: {
  report: BillReport | null
  poll: Poll
  unreadable: BillReport['items']
  corrections: Record<number, ItemCorrection>
  setCorrections: Dispatch<SetStateAction<Record<number, ItemCorrection>>>
  submit: { kind: 'idle' } | { kind: 'busy' } | { kind: 'error'; error: ApiError; retry: () => void }
  onConfirm: () => void
  onSave: () => void
}) {
  const status = report?.status

  // Network error while polling — the bill id is kept, retry resumes.
  if (poll.error) {
    return (
      <Notice role="alert" action={{ label: 'Try again', onClick: poll.resume }}>
        We lost contact with the server ({poll.error.message}). Your bill is still uploaded — try again.
      </Notice>
    )
  }
  if (poll.timedOut) {
    return (
      <Notice role="alert" action={{ label: 'Keep waiting', onClick: poll.resume }}>
        Reading is taking longer than usual (over 3 minutes). Your bill is still uploaded.
      </Notice>
    )
  }
  if (status === 'failed') {
    return (
      <Notice role="alert">
        We couldn't read this bill. Open step 1 to try another photo — a flatter, better-lit shot usually helps.
      </Notice>
    )
  }
  if (!report || status === 'processing') {
    return (
      <div aria-live="polite" className="flex items-center gap-3 py-2">
        <span className="h-3 w-3 animate-pulse rounded-full bg-ink" aria-hidden="true" />
        <p className="animate-pulse font-medium">Reading your bill…</p>
        <p className="sr-only">Two independent readers are checking each line.</p>
      </div>
    )
  }

  // needs_review, or ready when the user came back to look again
  const ready = status === 'ready'
  const get = (index: number, field: keyof ItemCorrection, fallback: string) =>
    corrections[index]?.[field] != null ? String(corrections[index][field]) : fallback

  const edit = (index: number, field: keyof ItemCorrection, value: string) => {
    const item = unreadable.find((i) => i.index === index)!
    setCorrections((c) => ({
      ...c,
      [index]: {
        index,
        name: c[index]?.name ?? item.name,
        quantity: c[index]?.quantity ?? item.quantity ?? '',
        rate: c[index]?.rate ?? item.rate ?? '',
        amount: c[index]?.amount ?? item.amount,
        [field]: value,
      },
    }))
  }

  const busy = submit.kind === 'busy'

  return (
    <div>
      <p className="text-muted">
        {unreadable.length === 0
          ? 'Every line read cleanly — there is nothing to correct here.'
          : `Our two readers disagreed on ${unreadable.length === 1 ? 'one line' : `${unreadable.length} lines`}. Check ${
              unreadable.length === 1 ? 'it' : 'them'
            } against the bill and fix anything that's wrong. The rest of the bill read cleanly and isn't shown here.`}
      </p>

      <ul className="mt-5 space-y-4">
        {unreadable.map((item) => (
          <li key={item.index} className="rounded-2xl bg-surface p-4">
            <div className="flex flex-col gap-4 sm:flex-row">
              <div className="h-20 w-full shrink-0 overflow-hidden rounded-xl bg-card ring-1 ring-ink/10 sm:h-24 sm:w-20">
                {report.bill_image_url ? (
                  <img src={report.bill_image_url} alt={`Bill, line ${item.index}`} className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full items-center justify-center text-center text-[10px] leading-tight text-muted" aria-hidden="true">
                    bill image
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-muted">Line {item.index}</p>
                <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <Field label="Name" value={get(item.index, 'name', item.name)} onChange={(v) => edit(item.index, 'name', v)} wide />
                  <Field label="Quantity" value={get(item.index, 'quantity', item.quantity ?? '')} onChange={(v) => edit(item.index, 'quantity', v)} />
                  <Field label="Rate (₹)" value={get(item.index, 'rate', item.rate ?? '')} onChange={(v) => edit(item.index, 'rate', v)} />
                  <Field label="Amount (₹)" value={get(item.index, 'amount', item.amount)} onChange={(v) => edit(item.index, 'amount', v)} />
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {submit.kind === 'error' && (
        <Notice role="alert" action={{ label: 'Try again', onClick: submit.retry }} className="mt-5">
          That didn't save ({submit.error.message}). Your edits are still here.
        </Notice>
      )}

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <button type="button" onClick={onConfirm} disabled={busy} className={btnPrimary}>
          {busy ? 'Working…' : ready ? 'Continue to report' : 'Looks right, continue'}
        </button>
        <button type="button" onClick={onSave} disabled={busy || Object.keys(corrections).length === 0} className={btnSecondary}>
          Save corrections
        </button>
      </div>
      <p className="mt-3 text-sm text-muted">
        Continuing without fixing a line just means that line goes unchecked — nothing else on the bill is affected.
      </p>
    </div>
  )
}

function Field({ label, value, onChange, wide }: { label: string; value: string; onChange: (v: string) => void; wide?: boolean }) {
  return (
    <label className={`block text-xs font-medium text-muted ${wide ? 'sm:col-span-2' : ''}`}>
      {label}
      <input
        type="text"
        inputMode={label === 'Name' ? 'text' : 'decimal'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1 block w-full rounded-xl border border-ink/20 bg-card px-3 py-2 text-base text-ink ${focusRing}`}
      />
    </label>
  )
}

function Notice({
  children,
  role,
  action,
  className = '',
}: {
  children: ReactNode
  role?: 'alert' | 'status'
  action?: { label: string; onClick: () => void }
  className?: string
}) {
  return (
    <div role={role} className={`rounded-2xl border border-ink/20 px-4 py-3 text-sm ${className}`}>
      <p>{children}</p>
      {action && (
        <button type="button" onClick={action.onClick} className={`mt-3 ${btnPrimary} px-5 py-2 text-sm`}>
          {action.label}
        </button>
      )}
    </div>
  )
}
