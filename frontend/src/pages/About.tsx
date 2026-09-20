import { useEffect, useRef, useState, type ReactNode } from 'react'
import { PREVIEW } from '../DropZone'
import { Chip } from '../Chip'
// Inlined (not <img>) so the SVG's font-family resolves against the page's loaded webfonts.
import billIllustration from '../../public/bill-illustration.svg?raw'

const ITEMS = [
  {
    title: 'Read it twice',
    body: 'Two independent readers parse the bill and their results are compared. Lines they disagree on are shown to you to confirm before anything is checked.',
  },
  {
    title: 'Check what has a ceiling',
    body: 'Medicines and devices with a published NPPA ceiling are compared against the ceiling in force. Room rent, nursing, consumables and lab tests have no published ceiling in India, so those are checked for duplication and arithmetic only.',
  },
  {
    title: 'Show the working',
    body: 'Every verdict opens to show the reference row, the order number and date it came from, and the rule that was applied. Nothing is asserted without its source.',
  },
]

const FACTS: [string, string][] = [
  ['Source', 'National Pharmaceutical Pricing Authority'],
  ['Items covered', '~915 medicines and devices'],
  ['Every verdict', 'Shows its reference row, order number and date'],
]

// Which left-hand item each right-hand panel belongs to.
const PANEL_ITEM = [0, 0, 1, 2]

export default function About() {
  const [active, setActive] = useState(0)
  const panelRefs = useRef<(HTMLDivElement | null)[]>([])

  // The panel crossing the middle band of the viewport drives the active item. If two overlap the lower
  // (newest while scrolling down) wins — the short last panel could otherwise never take over.
  useEffect(() => {
    const visible = new Set<number>()
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const i = panelRefs.current.indexOf(e.target as HTMLDivElement)
          if (e.isIntersecting) visible.add(i)
          else visible.delete(i)
        }
        const lowest = Math.max(-1, ...visible)
        if (lowest >= 0) setActive(PANEL_ITEM[lowest])
      },
      { rootMargin: '-40% 0px -40% 0px' },
    )
    panelRefs.current.forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [])

  return (
    // 1474px container — wider than the page's 1262px, matching the reference for this section.
    <section id="about" className="mt-24 w-full scroll-mt-24">
      {/* Plain flex row; see .about-* in index.css for the exact column rules. */}
      <div className="about-row">
        <div className="about-left">
          <h2 className="text-[52px] font-bold leading-[1.05] tracking-[-1px]">How BillSahi reads a bill.</h2>
          <ol className="mt-10">
            {ITEMS.map((item, i) => (
              <li key={item.title} className={`about-item ${i === active ? 'is-active' : ''}`}>
                <h3 className="text-[42px] font-bold leading-tight tracking-[-0.6px]">{item.title}</h3>
                <p className="about-body mt-3 text-[21px] leading-[1.55] text-[#585858]">{item.body}</p>
              </li>
            ))}
          </ol>
          <dl className="mt-9 space-y-5 border-t border-line pt-9">
            {FACTS.map(([label, value]) => (
              <div key={label}>
                <dt className="text-[13px] uppercase tracking-[0.5px] text-[#9b9b9b]">{label}</dt>
                <dd className="mt-0.5 text-[19px] font-semibold text-[#141414]">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-7 max-w-[460px] text-base leading-[1.6] text-[#8a8a8a]">
            Not compared is an expected result, not a failure. Most of an Indian hospital bill has no published
            ceiling — BillSahi says so plainly instead of guessing. BillSahi is not legal or medical advice.
          </p>
        </div>

        {/* Right: the four steps, illustrated. Swap a Panel's body for a screenshot when assets arrive. */}
        <div className="about-right relative isolate flex flex-col gap-8 overflow-hidden rounded-3xl bg-surface p-8">
          <div
            aria-hidden="true"
            className="bill-illustration pointer-events-none absolute right-8 top-10 z-0 hidden w-[420px] opacity-55 min-[900px]:block"
            dangerouslySetInnerHTML={{ __html: billIllustration }}
          />
          <Panel ref={(el) => (panelRefs.current[0] = el)} step="Step 1 · Upload">
            <UploadIllustration />
          </Panel>
          <Panel ref={(el) => (panelRefs.current[1] = el)} step="Step 2 · Check the reading" decorative>
            <CheckReadingIllustration />
          </Panel>
          <Panel ref={(el) => (panelRefs.current[2] = el)} step="Step 3 · Report" decorative>
            <ReportIllustration />
          </Panel>
          <Panel ref={(el) => (panelRefs.current[3] = el)} step="Step 4 · Clarification letter" decorative>
            <LetterIllustration />
          </Panel>
        </div>
      </div>
    </section>
  )
}

function Panel({
  ref,
  step,
  decorative,
  children,
}: {
  ref: (el: HTMLDivElement | null) => void
  step: string
  decorative?: boolean
  children: ReactNode
}) {
  return (
    <div ref={ref} className="relative rounded-2xl bg-card p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <span className="absolute right-4 top-4 rounded-md border border-line px-2 py-1 text-xs uppercase tracking-[0.5px] text-[#b0b0b0]">
        Example
      </span>
      <p className="pr-24 text-[17px] font-bold uppercase tracking-[0.8px] text-[#6b6b6b]">{step}</p>
      <div className="mt-4" aria-hidden={decorative ? 'true' : undefined}>
        {children}
      </div>
    </div>
  )
}

// ---- One worked example, carried through all four panels. Every figure is fabricated for illustration. ----
// Each illustration is its own component so it can be swapped for a real screenshot in one line.


/** Looks like the hero drop zone; its button returns the user to the real one instead of opening a picker. */
function UploadIllustration() {
  const goToUpload = () => {
    const zone = document.getElementById('upload')
    if (!zone) return
    zone.scrollIntoView({ behavior: 'smooth', block: 'center' })
    zone.focus({ preventScroll: true })
  }
  return (
    <div className="flex flex-col items-center rounded-[24px] border border-line bg-card px-6 py-8 text-center">
      <div aria-hidden="true" className="w-full max-w-[300px] opacity-55">
        <p className="text-[13px] uppercase tracking-[0.5px] text-[#9b9b9b]">Example</p>
        <ul className="mt-2 space-y-2">
          {PREVIEW.map((row) => (
            <li key={row.chip} className="flex items-center justify-between gap-3">
              <span className={`h-2 rounded-full bg-[#d9d9d9] ${row.w}`} />
              <Chip tone={row.tone} label={row.chip} size="xs" className="shrink-0" />
            </li>
          ))}
        </ul>
      </div>
      <button
        type="button"
        onClick={goToUpload}
        aria-label="Go to the upload area"
        className="mt-7 rounded-full bg-ink px-8 py-3.5 text-[17px] font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2"
      >
        Upload a bill
      </button>
      <span className="mt-3 text-base text-muted">Drop a photo or PDF, or click to choose</span>
    </div>
  )
}

function CheckReadingIllustration() {
  const fields: [string, string][] = [
    ['Item name', 'Coronary stent (DES)'],
    ['Quantity', '1'],
    ['Rate', '₹89,500.00'],
    ['Amount', '₹89,500.00'],
  ]
  return (
    <div>
      <p className="text-[15px] text-[#8a8a8a]">One line was hard to read. Confirm it before we check the price.</p>
      <div className="mt-4 flex gap-4">
        <div className="flex h-36 w-28 shrink-0 items-center justify-center rounded-xl bg-surface-hover text-[13px] text-muted">bill crop</div>
        <div className="min-w-0 flex-1 space-y-3">
          {fields.map(([label, value]) => (
            <div key={label}>
              <p className="text-[13px] font-medium text-muted">{label}</p>
              <p className="mt-1 rounded-lg border border-line bg-card px-3 py-1.5 text-base text-[#222]">{value}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ReportIllustration() {
  const rows: { name: string; affected: string; tone: 'red' | 'amber'; label: string }[] = [
    { name: 'Coronary stent (DES)', affected: '₹51,500.00', tone: 'red', label: 'Above the listed ceiling' },
    { name: 'Ceftriaxone 1g injection', affected: '₹147.00', tone: 'red', label: 'Above the listed ceiling' },
    { name: 'Nursing charges', affected: '₹1,200.00', tone: 'amber', label: 'May need clarification' },
    { name: 'Consumables', affected: '₹500.00', tone: 'amber', label: 'May need clarification' },
  ]
  return (
    <div>
      <p className="text-[17px] font-semibold text-[#141414]">We found 4 things worth asking about, worth ₹53,347.00.</p>
      <p className="mt-4 text-2xl font-bold">What we found</p>
      <ul className="mt-3 divide-y divide-line">
        {rows.map((r) => (
          <li key={r.name} className="flex items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="text-[15px] text-[#222]">{r.name}</p>
              <p className="text-sm text-[#6b6b6b]">Amount affected {r.affected}</p>
            </div>
            <Chip tone={r.tone} label={r.label} size="sm" className="shrink-0" />
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-4">
        <p className="text-base font-bold">Not compared (10)</p>
        <Chip tone="gray" label="No published ceiling" size="sm" className="shrink-0" />
      </div>
      <p className="mt-3 text-[13px] text-[#9b9b9b]">NPPA data retrieved 2026-09-18</p>
    </div>
  )
}

function LetterIllustration() {
  return (
    <div>
      <p className="whitespace-pre-line rounded-xl bg-surface p-4 text-[14.5px] leading-[1.7] text-[#444]">
        {`To the billing department, Sunrise Multispeciality, Pune.
I am writing about bill IP/2026/04812 dated 14-09-2026.
Four items on this bill appear to be above the price ceiling published by the NPPA, or may need clarification. I would be grateful if you could review the items listed below and let me know the basis for the amounts charged.`}
      </p>
      <p className="mt-3 text-[13px] text-[#9b9b9b]">You can edit this before sending.</p>
    </div>
  )
}
