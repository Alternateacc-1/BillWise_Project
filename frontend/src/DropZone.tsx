import { useRef, useState, type DragEvent } from 'react'
import { validateFile } from './pages/Flow'
import { Chip } from './Chip'
import type { Severity } from './lib/api'
import { useRevealOnce } from './useRevealOnce'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-bg'

// Decorative preview rows: neutral placeholders only — no amounts, names or percentages.
export const PREVIEW: { w: string; chip: string; tone: Severity }[] = [
  { w: 'w-[42%]', chip: 'Above ceiling', tone: 'red' },
  { w: 'w-[58%]', chip: 'Needs clarification', tone: 'amber' },
  { w: 'w-[36%]', chip: 'Within ceiling', tone: 'green' },
  { w: 'w-[50%]', chip: 'Not compared', tone: 'gray' },
]

/**
 * Hero upload control. Click / Enter / Space navigate to page 2 (the real picker lives in flow step 1).
 * A dropped file is validated here and handed to page 2 so the upload starts without re-picking.
 */
export function DropZone({ onStart, id }: { onStart: (file: File | null) => void; id?: string }) {
  const [over, setOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  useRevealOnce(ref, 0.3)

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const file = e.dataTransfer.files[0]
    if (!file) return
    const err = validateFile(file)
    if (err) return setError(err) // stay on page 1
    setError(null)
    onStart(file)
  }

  return (
    <div ref={ref} className="hero-zone-wrap">
      <button
        id={id}
        type="button"
        onClick={() => onStart(null)}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        aria-label="Upload a bill: drop a photo or PDF here, or click to get started"
        aria-describedby={error ? `${id}-error` : undefined}
        className={`hero-zone flex min-h-[280px] w-full cursor-pointer flex-col items-center justify-center rounded-[24px] px-6 py-6 text-center ${
          over ? 'is-over' : ''
        } ${focusRing}`}
      >
        <div aria-hidden="true" className="hero-zone-preview w-full max-w-[300px]">
          <p className="text-[11px] uppercase tracking-[0.5px] text-[#9b9b9b]">Example</p>
          <ul className="mt-2 space-y-2">
            {PREVIEW.map((row) => (
              <li key={row.chip} className="flex items-center justify-between gap-3">
                <span className={`h-2 rounded-full bg-[#d9d9d9] ${row.w}`} />
                <Chip tone={row.tone} label={row.chip} size="xs" className="shrink-0" />
              </li>
            ))}
          </ul>
        </div>

        <span className="hero-zone-cta mt-5 rounded-full bg-ink px-8 py-3.5 text-[17px] font-semibold text-white">Upload a bill</span>
        <span className="mt-2 text-sm text-muted">Drop a photo or PDF here, or click to get started</span>
        <span className="mt-3 flex flex-wrap justify-center gap-1.5">
          {['JPG', 'PNG', 'PDF', 'up to 10MB'].map((t) => (
            <span key={t} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-[#9b9b9b]">
              {t}
            </span>
          ))}
        </span>
      </button>

      {error && (
        <p id={`${id}-error`} role="alert" className="mt-3 rounded-2xl border border-ink/20 px-4 py-3 text-left text-sm">
          {error}
        </p>
      )}
    </div>
  )
}
