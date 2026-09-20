/**
 * The ONLY file that touches the network or knows the backend's field names.
 *
 * The original was written against a provisional contract, with mocks behind
 * VITE_USE_MOCKS. This is that file pointed at the REAL backend. Its own
 * comment said "if a field name differs, only this file changes" -- that held,
 * and this is the change. Every page above it is untouched by the wiring.
 *
 * Every function returns ApiResult<T>; nothing here throws.
 *
 * THREE PLACES WHERE THE REAL BACKEND IS RICHER THAN THE PROVISIONAL CONTRACT,
 * and flattening any of them would make the UI say something untrue:
 *
 *  1. GRAY HAS FOUR REASONS, NOT TWO. The contract had no_public_ceiling and
 *     could_not_read. The engine also returns could_not_identify (we read the
 *     line perfectly and could not work out which medicine it is) and
 *     pack_size_unknown (we know the medicine and cannot tell how many units
 *     the line covers). Collapsing those into could_not_read would claim we
 *     MISREAD lines we read correctly -- on the real pharmacy bill that is
 *     five of six lines slandering our own reading.
 *  2. RECONCILIATION HAS A FOURTH STATE, below_line_sum: the printed total is
 *     BELOW what the lines add up to, which is a discount we did not read, not
 *     a discrepancy. Reporting it as "mismatch" would ask a pharmacy to
 *     explain its own discount.
 *  3. `compared` -- how many lines actually got a price verdict. The contract
 *     had no such field, so a report that compared NOTHING looked identical to
 *     a clean bill. See summariseFromItems() and Report.tsx.
 */
import sampleReport from '../mocks/report.sample.json'
import { sampleLetter } from '../mocks/letter.sample'

// ---------- types ----------

export type Severity = 'red' | 'amber' | 'green' | 'gray'
export type BillStatus = 'processing' | 'needs_review' | 'ready' | 'failed'

/** Four, not two. See the header note. */
export type GrayReason =
  | 'no_public_ceiling'
  | 'could_not_read'
  | 'could_not_identify'
  | 'pack_size_unknown'
  | 'not_cross_checked'

export type Reconciliation =
  | 'reconciled'
  | 'mismatch'
  | 'below_line_sum'
  | 'no_total_found'

export interface BillItem {
  index: number
  name: string
  amount: string // decimal string -- never parse to Number
  severity: Severity // the ONE headline verdict
  headline: string
  amount_affected?: string
  rule_id: string
  gray_reason?: GrayReason
  notes?: string[]
  evidence?: Record<string, unknown>
  quantity?: string
  rate?: string
  /** 'high' | 'low' -- needed to say how many lines were read confidently. */
  confidence?: string
}

export interface BillReading {
  lines_total: number
  lines_verified: number
  reconciliation: Reconciliation
  /**
   * HOW MANY lines only one reader saw -- NOT whether the second reader ran.
   *
   * The two readings are paired BY ROW INDEX, so when Textract finds 11 rows
   * and the vision model finds 9, the unmatched indices carry
   * `only_one_reader_ran` while the rest were cross-checked normally. A
   * boolean over that made the report say "only one reader ran on this bill"
   * when in fact most lines had two, which overstates the problem in the same
   * way the old summary understated it.
   *
   * "N of M lines verified by both readers" is FALSE when only one reader
   * ran, and the count alone does not say which. Measured on the deployed
   * stack, same bill, one variable changed: 0 of 7 lines high-confidence with
   * two readers became 4 of 7 with one -- plus a false finding -- while
   * Textract reported 96-99 confidence both times. A single reader cannot
   * disagree with itself. Bedrock is currently returning
   * INVALID_PAYMENT_INSTRUMENT in production, so this is the live case.
   */
  single_reader_lines: number
}

export interface BillSummary {
  above_ceiling: number
  needs_clarification: number
  within_ceiling: number
  not_compared: number
  no_public_ceiling: number
  could_not_read: number
  could_not_identify: number
  pack_size_unknown: number
  not_cross_checked: number
  /** Lines that actually received a price verdict. The denominator. */
  compared: number
  total_amount_affected: string
}

/** A finding about the BILL, not about one line -- R2's reconciliation, say. */
export interface BillFinding {
  rule_id: string
  severity: Severity
  headline: string
  amount_affected?: string
  evidence?: Record<string, unknown>
}

export interface BillReport {
  bill_id: string
  status: BillStatus
  hospital_name: string
  bill_date: string
  bill_image_url?: string | null
  reading: BillReading
  summary: BillSummary
  reference_version: string
  items: BillItem[]
  /**
   * Findings about the whole bill rather than any one line.
   *
   * The provisional contract had no field for these, so they would have been
   * dropped silently -- and R2, the rule that checks whether the bill adds up
   * at all, reports ONLY at this level. A bill whose total does not match its
   * lines would have rendered as a bill with nothing wrong.
   */
  bill_findings: BillFinding[]
}

export interface CreateBillResponse {
  bill_id: string
  upload_url?: string
  /** POST /bills only: how many lines the readers returned, and the reader's own note when that is zero. */
  items_read?: number
  note?: string
}

export interface LetterResponse {
  letter_text: string
}

export interface FeedbackPayload {
  message: string
  email?: string
}

export interface HealthResponse {
  status: string
  provider?: string
  reader?: string
}

/** What the user may edit in step 2. */
export interface ItemCorrection {
  index: number
  name: string
  quantity: string
  rate: string
  amount: string
}

export interface ApiError {
  status: number // 0 = network / no response
  message: string
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError }

// ---------- helpers ----------

const BASE = import.meta.env.VITE_API_BASE ?? ''
const mocksOn = () => import.meta.env.VITE_USE_MOCKS === 'true'
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))
const fail = (status: number, message: string): ApiResult<never> => ({
  ok: false,
  error: { status, message },
})

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const res = await fetch(BASE + path, init)
    if (!res.ok) return fail(res.status, `${init?.method ?? 'GET'} ${path} returned ${res.status}`)
    return { ok: true, data: (await res.json()) as T }
  } catch (e) {
    return fail(0, e instanceof Error ? e.message : 'Network error')
  }
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

// ---------- the adapter: engine shape -> UI shape ----------

/** One flag as the engine serialises it. */
interface RawFlag {
  rule_id?: string
  explanation?: string
  severity?: string
  evidence?: Record<string, unknown>
  suggested_question?: string
}

interface RawItem {
  index: number
  name: string
  quantity: string | null
  unit_price: string | null
  line_total: string | null
  confidence: string
  severity: Severity
  gray_reason: string | null
  gray_detail: string | null
  amount_affected: string
  headline: RawFlag | null
  notes: RawFlag[]
}

interface RawVerified {
  index: number
  reasons?: string[]
}

interface RawReport {
  bill_id: string
  hospital_name: string
  bill_date: string
  reference_retrieved_on: string
  by_item: RawItem[]
  items?: RawVerified[]
  bill_level_flags?: RawFlag[]
  stats?: { reconciliation?: string }
}

/**
 * Our four-state gray, recovered from the engine's reason + detail pair.
 *
 * `gray_reason` says WHETHER a price verdict was reached; `gray_detail` says
 * why not. The UI needs the detail, because "we could not read this" and "we
 * read it and cannot identify the medicine" are different admissions and only
 * one of them is about our reading.
 */
function grayReasonOf(item: RawItem): GrayReason | undefined {
  if (!item.gray_reason) return undefined
  if (item.gray_reason === 'no_public_ceiling') return 'no_public_ceiling'
  if (item.gray_detail === 'could_not_identify') return 'could_not_identify'
  if (item.gray_detail === 'pack_size_unknown') return 'pack_size_unknown'
  if (item.gray_detail === 'not_cross_checked') return 'not_cross_checked'
  return 'could_not_read'
}

function adaptItem(raw: RawItem): BillItem {
  return {
    index: raw.index,
    name: raw.name,
    amount: raw.line_total ?? '0',
    severity: raw.severity,
    headline: raw.headline?.explanation ?? '',
    amount_affected: raw.amount_affected,
    rule_id: raw.headline?.rule_id ?? '',
    gray_reason: grayReasonOf(raw),
    notes: (raw.notes ?? []).map((f) => f.explanation ?? '').filter(Boolean),
    evidence: raw.headline?.evidence,
    quantity: raw.quantity ?? undefined,
    rate: raw.unit_price ?? undefined,
    confidence: raw.confidence,
  }
}

/**
 * EVERY COUNT IS DERIVED FROM THE ITEMS THE UI WILL RENDER.
 *
 * Not from the server's own summary fields. Those are computed on a different
 * partition and they HAD drifted: the headline said "10 of 16 charges have no
 * published ceiling" above a group rendering 9, because the server counts by
 * gray_reason while the group also requires severity === 'gray', and one amber
 * item carries both. A count derived from the array it labels cannot lie.
 */
function summariseFromItems(items: BillItem[], billFlags: RawFlag[]): BillSummary {
  const gray = items.filter((i) => i.severity === 'gray')
  const by = (r: GrayReason) => gray.filter((i) => i.gray_reason === r).length
  const money = (v?: string) => Number(v ?? 0)

  return {
    above_ceiling: items.filter((i) => i.severity === 'red').length,
    // Bill-level flags are findings too and render as their own cards.
    needs_clarification:
      items.filter((i) => i.severity === 'amber').length + billFlags.length,
    within_ceiling: items.filter((i) => i.severity === 'green').length,
    not_compared: gray.length,
    no_public_ceiling: by('no_public_ceiling'),
    could_not_read: by('could_not_read'),
    could_not_identify: by('could_not_identify'),
    pack_size_unknown: by('pack_size_unknown'),
    not_cross_checked: by('not_cross_checked'),
    // A PRICE VERDICT, NOT A COLOUR. An item can be amber from the duplicate
    // or arithmetic rules while its price was never compared to anything --
    // an amber duplicate on a line with no ceiling, say. `gray_reason` is set
    // exactly when no price verdict was reached, so it is the test.
    compared: items.filter((i) => i.severity !== 'gray' && !i.gray_reason).length,
    total_amount_affected: (
      items
        .filter((i) => i.severity === 'red' || i.severity === 'amber')
        .reduce((s, i) => s + money(i.amount_affected), 0) +
      billFlags.reduce(
        (s, f) => s + money((f as { amount_affected?: string }).amount_affected),
        0,
      )
    ).toFixed(2),
  }
}

function adaptReport(raw: RawReport): BillReport {
  const items = (raw.by_item ?? []).map(adaptItem)
  const billFlags = raw.bill_level_flags ?? []
  const reconciliation = (raw.stats?.reconciliation ?? 'no_total_found') as Reconciliation

  return {
    bill_id: raw.bill_id,
    // The engine runs the whole pipeline synchronously and only ever hands
    // back a finished report, so anything we can GET is ready. The polling
    // machinery upstairs still works; it simply settles on the first tick.
    status: 'ready',
    hospital_name: raw.hospital_name,
    bill_date: raw.bill_date,
    reading: {
      lines_total: items.length,
      lines_verified: items.filter((i) => i.confidence === 'high').length,
      reconciliation,
      single_reader_lines: (raw.items ?? []).filter((v) =>
        (v.reasons ?? []).includes('only_one_reader_ran'),
      ).length,
    },
    summary: summariseFromItems(items, billFlags),
    reference_version: raw.reference_retrieved_on,
    items,
    bill_findings: billFlags.map((f) => ({
      rule_id: f.rule_id ?? '',
      severity: (f.severity ?? 'amber') as Severity,
      headline: f.explanation ?? '',
      amount_affected: (f as { amount_affected?: string }).amount_affected,
      evidence: f.evidence,
    })),
  }
}

// ---------- mock state (kept: it is how the UI is developed offline) ----------

export const SAMPLE_BILL_ID = sampleReport.bill_id
const report = sampleReport as unknown as BillReport
let mockCreatedAt = 0
let mockConfirmedAt = 0
let mockItems: BillItem[] = report.items

function mockOverride(): BillStatus | null {
  const v = new URLSearchParams(window.location.search).get('mock')
  return v === 'processing' || v === 'needs_review' || v === 'ready' || v === 'failed' ? v : null
}

function mockReport(): BillReport {
  const forced = mockOverride()
  let status: BillStatus
  const now = Date.now()
  if (forced) status = forced
  else if (now - mockCreatedAt < 6000) status = 'processing'
  else if (!mockConfirmedAt) status = 'needs_review'
  else if (now - mockConfirmedAt < 3000) status = 'processing'
  else status = 'ready'
  return { ...report, status, items: mockItems }
}

// ---------- the calls ----------

/** POST /bills -- multipart upload. onProgress gets 0..1 while the file is sent. */
export async function createBill(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<ApiResult<CreateBillResponse>> {
  if (mocksOn()) {
    for (let i = 1; i <= 5; i++) {
      await delay(150)
      onProgress?.(i / 5)
    }
    mockCreatedAt = Date.now()
    mockConfirmedAt = 0
    mockItems = report.items
    return { ok: true, data: { bill_id: report.bill_id } }
  }
  // XHR only because fetch has no upload-progress events.
  try {
    return await new Promise<ApiResult<CreateBillResponse>>((resolve) => {
      const form = new FormData()
      form.append('file', file)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', BASE + '/bills')
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(e.loaded / e.total)
      }
      xhr.onload = () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          // The backend explains a rejected upload (too large, wrong type) in
          // `detail`. Showing "returned 400" instead would waste the message.
          let msg = `POST /bills returned ${xhr.status}`
          try {
            const d = JSON.parse(xhr.responseText)?.detail
            if (typeof d === 'string' && d) msg = d
          } catch {
            /* keep the status message */
          }
          return resolve(fail(xhr.status, msg))
        }
        try {
          resolve({ ok: true, data: JSON.parse(xhr.responseText) as CreateBillResponse })
        } catch {
          resolve(fail(xhr.status, 'POST /bills returned invalid JSON'))
        }
      }
      xhr.onerror = () => resolve(fail(0, 'Network error'))
      xhr.send(form)
    })
  } catch (e) {
    return fail(0, e instanceof Error ? e.message : 'Network error')
  }
}

/**
 * POST /bills/sample -- run a bundled demo bill.
 *
 * The provisional contract had no sample path, and local mode has no OCR, so
 * without this there is nothing to press on a machine with no AWS credentials
 * -- which is the first thing a judge does.
 */
export async function createSampleBill(fixture?: string): Promise<ApiResult<CreateBillResponse>> {
  if (mocksOn()) {
    mockCreatedAt = Date.now()
    mockConfirmedAt = 0
    mockItems = report.items
    return { ok: true, data: { bill_id: report.bill_id } }
  }
  const q = fixture ? `?fixture=${encodeURIComponent(fixture)}` : ''
  return request<CreateBillResponse>(`/bills/sample${q}`, { method: 'POST' })
}

/** GET /bills/{id} -- poll this. */
export async function getBill(id: string): Promise<ApiResult<BillReport>> {
  if (mocksOn()) {
    await delay(200)
    return { ok: true, data: mockReport() }
  }
  const res = await request<RawReport>(`/bills/${encodeURIComponent(id)}`)
  return res.ok ? { ok: true, data: adaptReport(res.data) } : res
}

/** PUT /bills/{id}/items -- user corrections. */
export async function updateItems(
  id: string,
  items: ItemCorrection[],
): Promise<ApiResult<BillReport>> {
  if (mocksOn()) {
    await delay(400)
    const byIndex = new Map(items.map((c) => [c.index, c]))
    mockItems = mockItems.map((it) => {
      const c = byIndex.get(it.index)
      return c ? { ...it, name: c.name, quantity: c.quantity, rate: c.rate, amount: c.amount } : it
    })
    mockConfirmedAt = Date.now()
    return { ok: true, data: mockReport() }
  }
  // The engine takes a map keyed by index, with its own field names, and
  // returns a receipt rather than a report -- so re-read afterwards.
  const corrections: Record<string, Record<string, string>> = {}
  for (const c of items) {
    corrections[String(c.index)] = {
      name: c.name,
      quantity: c.quantity,
      unit_price: c.rate,
      line_total: c.amount,
    }
  }
  const put = await request<unknown>(
    `/bills/${encodeURIComponent(id)}/items`,
    jsonInit('PUT', { corrections }),
  )
  if (!put.ok) return put
  return getBill(id)
}

/** POST /bills/{id}/confirm -- user accepts the reading. */
export async function confirmBill(id: string): Promise<ApiResult<BillReport>> {
  if (mocksOn()) {
    await delay(400)
    mockConfirmedAt = Date.now()
    return { ok: true, data: mockReport() }
  }
  const res = await request<unknown>(`/bills/${encodeURIComponent(id)}/confirm`, {
    method: 'POST',
  })
  if (!res.ok) return res
  return getBill(id)
}

/** POST /bills/{id}/letter */
export async function generateLetter(id: string): Promise<ApiResult<LetterResponse>> {
  if (mocksOn()) {
    await delay(800)
    return { ok: true, data: { letter_text: sampleLetter } }
  }
  const res = await request<{ letter?: string }>(
    `/bills/${encodeURIComponent(id)}/letter`,
    { method: 'POST' },
  )
  return res.ok ? { ok: true, data: { letter_text: res.data.letter ?? '' } } : res
}

/** POST /feedback */
export async function sendFeedback(payload: FeedbackPayload): Promise<ApiResult<{ ok: true }>> {
  if (mocksOn()) {
    await delay(500)
    return { ok: true, data: { ok: true } }
  }
  return request<{ ok: true }>('/feedback', jsonInit('POST', payload))
}

/** GET /health */
export async function checkHealth(): Promise<ApiResult<HealthResponse>> {
  if (mocksOn()) return { ok: true, data: { status: 'ok' } }
  return request<HealthResponse>('/health')
}
