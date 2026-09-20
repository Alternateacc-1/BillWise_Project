import { useEffect, useId, useRef, useState, type AnimationEvent, type FormEvent } from 'react'
import { DropZone } from '../DropZone'
import { useRevealOnce } from '../useRevealOnce'
import About from './About'
import { Logo } from '../Logo'
import { sendFeedback } from '../lib/api'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-bg'

const NAV = ['About', 'FAQ', 'Contact', 'Feedback'] as const

// Placeholders — replace before shipping.
const CONTACT_EMAIL = 'contact@example.com'
// No git remote is configured on this repo, so there is no URL to put here.
// The previous value was INVENTED from the local git username and pointed at
// a repository that may not exist -- a fabricated link on a public page is
// worse than no link. Set this when the repo is pushed; the footer hides the
// link while it is empty.
const REPO_URL = ''
// Brand marks from Simple Icons (CC0, simpleicons.org) — path data copied verbatim, not redrawn.
const SOCIAL = [
  { name: 'X', handle: '@HANDLE_X', href: 'https://x.com/HANDLE_X', brand: '#000000', path: 'M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z' },
  { name: 'Instagram', handle: '@HANDLE_IG', href: 'https://instagram.com/HANDLE_IG', brand: '#E4405F', path: 'M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077' },
  { name: 'WhatsApp', handle: '+91 HANDLE_WA', href: 'https://wa.me/HANDLE_WA', brand: '#25D366', path: 'M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z' },
]


const FAQ: { q: string; a: string }[] = [
  {
    q: 'What does BillWise check?',
    a: 'It reads each line of your bill, matches medicines and devices to the price ceilings published by India\'s National Pharmaceutical Pricing Authority (NPPA), and marks each line as above the listed ceiling, may need clarification, within the ceiling, or not compared. Every verdict comes with the reference row, the government order number and date, and the rule that produced it.',
  },
  {
    q: 'Does a red line mean the hospital did something wrong?',
    a: 'No. It means the billed price is above the ceiling listed for that item on the date we retrieved the data. There can be valid reasons — a different pack size, a newer order, a line we matched imperfectly. That is why the report ends with a polite letter asking the hospital to explain, not a claim.',
  },
  {
    q: 'Why are most of my lines "not compared"?',
    a: 'Because most of a hospital bill is not medicines. Room rent, nursing, consultant visits, operation theatre, consumables and lab tests have no published ceiling price in India, so there is nothing to compare them against. We still check those lines for duplication and arithmetic. This is expected, not an error.',
  },
  {
    q: 'What if BillWise read a line wrongly?',
    a: 'Two independent readers check each line. Lines they disagree on are shown to you before the report, next to the bill image, so you can correct the name, quantity, rate or amount. Lines you skip simply go unchecked.',
  },
  {
    q: 'Is this legal or medical advice?',
    a: 'No. BillWise is an information tool. The report and the letter are starting points for a conversation with your hospital. For a dispute, contact your state\'s health department or a lawyer.',
  },
  {
    q: 'Where do the price ceilings come from?',
    a: 'From the National Pharmaceutical Pricing Authority, the government body that publishes maximum prices for scheduled medicines and devices in India. The date the data was retrieved is shown with every verdict, so you can see how current it is.',
  },
]

export default function Landing({ onStart }: { onStart: (file: File | null) => void }) {
  return (
    <div id="top" className="min-h-screen">
      {/* .page-content slides over the sticky footer beneath it (see index.css). */}
      <div className="page-content pb-24">
      <Nav />

      <main>
        {/* Hero */}
        <section className="mx-auto max-w-[860px] px-4 pt-10 text-center">
          <Badge />
          {/* Plus Jakarta Sans's full stop carries wide side-bearings; at this size that reads as a gap, so each one is pulled in. */}
          <h1 className="mt-3 text-[clamp(34px,4.6vw,64px)] font-bold leading-[1.05] tracking-[-1.6px] [word-spacing:normal]">
            Every line of your hospital bill, checked against the price list<span className="-ml-[0.08em]">.</span>
          </h1>
          <p className="mx-auto mt-[14px] max-w-[660px] text-[19px] leading-[1.5] text-muted">
            Upload a photo or PDF. BillWise compares what has a published ceiling and shows you where every figure came from.
          </p>
        </section>

        {/* Upload */}
        <section className="mx-auto mt-[22px] max-w-[720px] px-4 text-center">
          <DropZone id="upload" onStart={onStart} />
          <p className="mt-4 text-[15px] font-semibold text-muted">Checks against NPPA's published ceilings for ~915 medicines and devices.</p>
        </section>

        {/* Media placeholders */}
        {/* Full-width section, 20px side padding; the 1262px inner container matches the reference. */}
        <section className="mt-16 w-full px-5">
          <div className="mx-auto w-full max-w-[1262px]">
            <Placeholder label="Product video" className="aspect-video rounded-[32px]" />
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Placeholder label="Screenshot 1 — upload" className="aspect-[4/3]" />
              <Placeholder label="Screenshot 2 — report" className="aspect-[4/3]" />
              <Placeholder label="Screenshot 3 — letter" className="aspect-[4/3]" />
            </div>
          </div>
        </section>

        <About />

        {/* FAQ */}
        <section id="faq" className="mx-auto w-full max-w-[1320px] scroll-mt-24 px-10 pt-11">
          <h2 className="faq-heading text-center font-bold leading-[1.05] text-[#141414]">Frequently asked questions</h2>
          {/* The accordion keeps a narrower measure inside the shared 1320px container so answers stay readable. */}
          <div className="mx-auto mt-10 flex w-full max-w-[1080px] flex-col gap-[14px]">
            {FAQ.map((f) => (
              <FaqRow key={f.q} {...f} />
            ))}
          </div>
        </section>

        {/* Contact */}
        <section id="contact" className="mx-auto w-full max-w-[1320px] scroll-mt-24 px-10 pt-24">
          <div className="rounded-[24px] border border-line bg-card p-6 shadow-[0_2px_10px_rgba(20,20,20,0.04)] sm:p-10 lg:p-11">
            <div className="grid grid-cols-1 gap-10 min-[900px]:grid-cols-[55fr_45fr]">
              {/* Left */}
              <div>
                <h2 className="text-[44px] font-bold leading-[1.05] tracking-[-1px]">Contact</h2>
                <p className="mt-5 max-w-[400px] text-[17px] leading-[1.55] text-muted">
                  Questions, corrections to a price reference, or a hospital that wants to talk to us.
                </p>
                <EmailButton />
                <p className="mt-3 text-[13px] text-muted">{CONTACT_EMAIL}</p>
                <p className="mt-2.5 max-w-[380px] text-[14px] leading-[1.55] text-muted">
                  We read every message. If you are writing about a specific bill, include the line number and the hospital's name — it
                  helps us check the reference faster.
                </p>
              </div>

              {/* Right */}
              <div className="flex flex-col gap-[14px]">
                <div className="rounded-[18px] bg-surface p-6">
                  <h3 className="text-[18px] font-bold">Found a wrong reference?</h3>
                  <p className="mt-2 text-[15px] leading-[1.6] text-muted">
                    Tell us which line and which bill, and we will check it against the published order. BillWise is
                    only as good as the data it cites.
                  </p>
                </div>
                <div className="rounded-[18px] bg-surface p-6">
                  <h3 className="text-[18px] font-bold">The project</h3>
                  {REPO_URL && (
                  <a
                    href={REPO_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`mt-3 inline-flex items-center gap-2 rounded-full border border-line px-4 py-2.5 text-[15px] font-semibold text-[#141414] transition-colors hover:border-[#141414] ${focusRing}`}
                  >
                    View the source
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M7 17L17 7M9 7h8v8" />
                    </svg>
                  </a>
                  )}
                  <p className="mt-3 text-[14px] text-muted">Built for Bharat Builds, 2026.</p>
                </div>
              </div>
            </div>

            {/* Social: icons left, label right; stacked and centred below 640px */}
            <div className="mt-32 flex flex-col items-center gap-6 border-t border-line pt-10 sm:flex-row sm:justify-between">
            <ul className="flex flex-wrap items-start justify-center gap-x-7 gap-y-6 sm:flex-nowrap sm:gap-7">
              {SOCIAL.map((item) => (
                <li key={item.name}>
                  <a
                    href={item.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={item.name}
                    className={`social-link flex flex-col items-center rounded-2xl ${focusRing}`}
                    style={{ '--brand': item.brand } as React.CSSProperties}
                  >
                    <span className="social-circle flex h-11 w-11 items-center justify-center rounded-full border border-line bg-card">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d={item.path} />
                      </svg>
                    </span>
                    <span className="social-handle mt-2.5 whitespace-nowrap text-[13px] font-semibold text-ink">{item.handle}</span>
                  </a>
                </li>
              ))}
            </ul>
            {/* Plain label for now; not a link until a URL is supplied. */}
            <p className="flex items-center text-[15px] font-semibold text-ink sm:h-11 sm:self-start">@VersionOne</p>
            </div>
          </div>
        </section>

      </main>
      </div>
      {/* Scroll-spy sentinel at the bottom edge of .page-content: exactly where the sticky footer is revealed (see Nav). */}
      <div id="feedback-sentinel" aria-hidden="true" className="h-0" />

      {/* Footer + feedback. id="feedback" is the nav anchor. Hidden in print. */}
      <footer id="feedback" className="site-footer scroll-mt-24 print:hidden">
        <div className="mx-auto w-full max-w-[1320px]">
          <div className="grid grid-cols-1 gap-14 min-[900px]:grid-cols-[38fr_62fr]">
            {/* Left */}
            <div>
              <p className="text-[36px] font-bold leading-none tracking-[-1px] text-[color:var(--footer-text)]">BillWise</p>
              <p className="mt-5 max-w-[340px] text-[18px] leading-[1.5] text-[color:var(--footer-muted)]">
                Check your hospital bill against India's published price ceilings.
              </p>
              <div className="mt-11 grid grid-cols-2 gap-14">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[1px] text-[color:var(--footer-muted)]">Sections</p>
                  <ul className="mt-4 space-y-3.5">
                    {['About', 'FAQ', 'Contact'].map((l) => (
                      <li key={l}>
                        <a href={`#${l.toLowerCase()}`} className={`footer-link ${focusRing}`}>
                          {l}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase tracking-[1px] text-[color:var(--footer-muted)]">Project</p>
                  <ul className="mt-4 space-y-3.5">
                    {REPO_URL && (
                    <li>
                      <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className={`footer-link ${focusRing}`}>
                        GitHub
                      </a>
                    </li>
                    )}
                    <li>
                      <a href={`mailto:${CONTACT_EMAIL}`} className={`footer-link ${focusRing}`}>
                        Email
                      </a>
                    </li>
                    <li>
                      <a href="https://www.nppaindia.nic.in" target="_blank" rel="noopener noreferrer" className={`footer-link ${focusRing}`}>
                        NPPA
                      </a>
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            {/* Right */}
            <FeedbackBlock />
          </div>

          <div className="mt-11 flex flex-col gap-4 border-t pt-6 text-[14px] text-[color:var(--footer-muted)] sm:flex-row sm:justify-between" style={{ borderColor: 'var(--footer-line)' }}>
            <p>© BillWise 2026 · Built for Bharat Builds</p>
            <p className="sm:max-w-[420px] sm:text-right">
              Not legal or medical advice. Verdicts cite published NPPA data; always confirm with the hospital.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}

// The entrance reveal (nav pill + hero badge, one shared timeline in index.css) plays once per page load — not again
// when Landing remounts after page 2. Module-level flag; both components read it in their state initialisers, so on the
// first mount they start together, and `.is-arriving` is dropped for both once the CSS timeline (--reveal-total) is over.
let arrived = false
function useArriving(): boolean {
  const [arriving, setArriving] = useState(() => !arrived)
  useEffect(() => {
    if (!arriving) return
    arrived = true
    const total = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--reveal-total')) || 2100
    const t = setTimeout(() => setArriving(false), total + 100)
    return () => clearTimeout(t)
  }, [arriving])
  return arriving
}

/** Entrance corner dots. Each removes itself from the DOM when its fade-out animation ends. */
const Dots = () => {
  const [dots, setDots] = useState(['one', 'two', 'three', 'four'])
  const gone = (name: string) => (e: AnimationEvent) => {
    if (e.animationName === 'reveal-dot-out') setDots((d) => d.filter((x) => x !== name))
  }
  return (
    <>
      {dots.map((name) => (
        <i key={name} className={`reveal-dot ${name}`} onAnimationEnd={gone(name)} />
      ))}
    </>
  )
}

/** The "BillWise" badge. Final state = a plain bordered pill; the shared reveal only changes how it arrives. */
function Badge() {
  const arriving = useArriving()
  return (
    <span className={`badge-anim ${arriving ? 'is-arriving' : ''}`}>
      <span className="badge-frame reveal-frame" aria-hidden="true">
        {arriving && <Dots />}
      </span>
      <span className="badge-content reveal-item">BillWise</span>
    </span>
  )
}

function Nav() {
  const navRef = useRef<HTMLElement>(null)
  const [active, setActive] = useState<string | null>(null)

  // Entrance: shared with the hero badge (useArriving). The nav box is full size and interactive throughout —
  // only ::before (the skin), the dots and the items' opacity/transform/blur animate.
  const arriving = useArriving()

  // Active section: a section counts once it reaches just below the floating nav.
  // Several may intersect at once (the zone is nav-bottom to 45% of the viewport); the topmost wins.
  // The footer is sticky under the page, so its own box sits in the viewport from load and cannot be observed.
  // Instead a zero-height sentinel at the end of .page-content marks where the footer is genuinely revealed:
  // Feedback counts once that sentinel has risen to the 45% line, and only when no section above it is active.
  useEffect(() => {
    const ids = NAV.filter((l) => l !== 'Feedback').map((l) => l.toLowerCase())
    const sections = ids.map((id) => document.getElementById(id)).filter((el): el is HTMLElement => !!el)
    const navBottom = navRef.current?.getBoundingClientRect().bottom ?? 90
    const visible = new Set<string>()
    let feedback = false
    const update = () => setActive(ids.find((id) => visible.has(id)) ?? (feedback ? 'feedback' : null))
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target.id)
          else visible.delete(e.target.id)
        }
        update()
      },
      { rootMargin: `-${Math.round(navBottom + 8)}px 0px -55% 0px` },
    )
    sections.forEach((el) => io.observe(el))
    const sentinel = document.getElementById('feedback-sentinel')
    const sio = new IntersectionObserver(
      (entries) => {
        // fires on every crossing of the 45% line (and of the top edge); recompute from the rect, not isIntersecting
        for (const e of entries) feedback = e.boundingClientRect.top <= e.rootBounds!.bottom
        update()
      },
      { rootMargin: '0px 0px -55% 0px' },
    )
    if (sentinel) sio.observe(sentinel)
    return () => {
      io.disconnect()
      sio.disconnect()
    }
  }, [])

  return (
    // The header keeps 76px (16 + 60) in the document flow; the pill itself is fixed.
    <header className="h-[76px]">
      <div className="fixed left-1/2 top-0 z-[100] w-full -translate-x-1/2 px-4 pt-4">
        <nav ref={navRef} aria-label="Main" className={`nav-pill mx-auto ${arriving ? 'is-arriving' : ''}`}>
          {arriving && (
            <span aria-hidden="true">
              <Dots />
            </span>
          )}
          <a
            href="#top"
            aria-label="BillWise"
            onClick={(e) => {
              e.preventDefault() // scroll to top without writing #top into the URL
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
            className={`nav-brand reveal-item flex shrink-0 items-center gap-2.5 rounded-full ${focusRing}`}
          >
            <Logo height={26} decorative />
            <span className="nav-wordmark">BillWise</span>
          </a>
          {/* Negative margin cancels the link's own side padding so the last label ends exactly at the pill's 24px padding edge. */}
          <ul className="nav-links flex shrink-0 items-center">
            {NAV.map((label) => {
              const id = label.toLowerCase()
              return (
                <li key={label} className="reveal-item">
                  <a href={`#${id}`} aria-current={active === id ? 'true' : undefined} className={`nav-link ${focusRing}`}>
                    {label}
                  </a>
                </li>
              )
            })}
          </ul>
        </nav>
      </div>
    </header>
  )
}

function Placeholder({ label, className = '' }: { label: string; className?: string }) {
  return (
    <div
      role="img"
      aria-label={`${label} (placeholder)`}
      className={`flex items-center justify-center rounded-3xl bg-surface text-sm font-medium text-muted ${className}`}
    >
      {label}
    </div>
  )
}

function FaqRow({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div className={`faq-row ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={`faq-trigger flex w-full items-start justify-between gap-4 text-left font-bold leading-[1.3] text-[#141414] ${focusRing}`}
      >
        <span className="pr-6">{q}</span>
        {/* .faq-chevron margin-top = (line-height − 22) / 2 keeps it on the first line of a wrapped question. */}
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={`faq-chevron shrink-0 ${open ? 'rotate-180' : ''}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {/* Stays mounted; collapsed via grid-rows so print can expand it. */}
      <div id={id} className={`faq-panel grid transition-[grid-template-rows] print:grid-rows-[1fr] ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
        <p className="faq-answer max-w-[780px] overflow-hidden leading-[1.65] text-[#585858]">
          <span className="block pt-5">{a}</span>
        </p>
      </div>
    </div>
  )
}

/** Mailto pill with a one-shot entrance the first time 40% of it is on screen. */
function EmailButton() {
  const ref = useRef<HTMLAnchorElement>(null)
  useRevealOnce(ref, 0.4)
  return (
    <a
      ref={ref}
      href={`mailto:${CONTACT_EMAIL}`}
      className={`email-cta mt-8 inline-flex items-center gap-2.5 rounded-full bg-[#111111] px-7 py-3.5 text-[16px] font-semibold text-white hover:bg-black ${focusRing}`}
    >
      Email the team
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M5 12h14M13 6l6 6-6 6" />
      </svg>
    </a>
  )
}

const MAX = 2000

function FeedbackBlock() {
  const ref = useRef<HTMLDivElement>(null)
  useRevealOnce(ref, 0.3)
  return (
    <div ref={ref} className="feedback-block">
      <h2 className="text-[44px] font-bold leading-[1.05] tracking-[-1px] text-[color:var(--footer-text)]">Feedback</h2>
      <p className="mt-4 max-w-[520px] text-[17px] text-[color:var(--footer-muted)]">
        Tell us what worked and what didn't. We read everything.
      </p>
      <FeedbackForm />
    </div>
  )
}

const WARN_AT = 1800

function FeedbackForm() {
  const [message, setMessage] = useState('')
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorText, setErrorText] = useState('')
  const msgId = useId()
  const emailId = useId()
  const noteId = useId()

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    // Honeypot: bots fill every field; humans never see this one.
    if ((form.elements.namedItem('website') as HTMLInputElement).value) {
      setState('sent')
      return
    }
    setState('sending')
    const res = await sendFeedback({ message: message.trim(), email: email.trim() || undefined })
    if (res.ok) {
      setState('sent')
    } else {
      setState('error')
      setErrorText(res.error.message)
    }
  }

  if (state === 'sent') {
    return (
      <div className="footer-field mt-8 rounded-[18px] p-6" role="status">
        <p className="text-lg font-medium text-[color:var(--footer-text)]">Thank you — your feedback has been received.</p>
        <button
          type="button"
          onClick={() => {
            setMessage('')
            setEmail('')
            setState('idle')
          }}
          className={`footer-link mt-4 text-sm underline underline-offset-4 ${focusRing}`}
        >
          Send another
        </button>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="mt-8" noValidate>
      <label htmlFor={msgId} className="sr-only">
        Your feedback
      </label>
      <div className="relative">
        <textarea
          id={msgId}
          required
          maxLength={MAX}
          value={message}
          onChange={(e) => setMessage(e.target.value.slice(0, MAX))}
          aria-describedby={noteId}
          placeholder="What worked, what didn't, what you expected to see…"
          className="footer-field min-h-[150px] w-full resize-y rounded-[18px] p-[18px] pb-10 text-[16px] leading-[1.6]"
        />
        <p
          className={`pointer-events-none absolute bottom-4 right-[18px] text-[13px] ${message.length > WARN_AT ? 'text-[#E0A03A]' : 'text-[color:var(--footer-muted)]'}`}
          aria-live="polite"
        >
          {message.length} / {MAX}
        </p>
      </div>

      <label htmlFor={emailId} className="sr-only">
        Email (optional)
      </label>
      <input
        id={emailId}
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email (optional, if you'd like a reply)"
        className="footer-field mt-4 w-full rounded-[18px] px-[18px] py-[14px] text-[16px]"
      />

      <div className="absolute -left-[9999px] top-auto h-px w-px overflow-hidden" aria-hidden="true">
        <label>
          Website
          <input type="text" name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>

      <p id={noteId} className="mt-3 text-[14px] text-[color:var(--footer-muted)]">
        Feedback is not private. Please don't include personal or medical details.
      </p>

      {state === 'error' && (
        <p className="footer-field mt-4 rounded-[18px] px-4 py-3 text-sm text-[color:var(--footer-text)]" role="alert">
          We couldn't send that ({errorText}). Your text is still here — try again in a moment.
        </p>
      )}

      <button
        type="submit"
        disabled={state === 'sending' || !message.trim()}
        className={`footer-submit mt-6 rounded-full px-[30px] py-[14px] text-[16px] font-semibold disabled:opacity-40 ${focusRing}`}
      >
        {state === 'sending' ? 'Sending…' : state === 'error' ? 'Try again' : 'Send feedback'}
      </button>
    </form>
  )
}
