import { useEffect, useId, useRef, useState } from 'react'
import { generateLetter, type ApiError } from '../lib/api'

const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-bg'
const btnPrimary = `rounded-full bg-ink px-6 py-3 text-base font-medium text-white transition-opacity disabled:opacity-40 ${focusRing}`
const btnSecondary = `rounded-full border border-ink/20 bg-card px-6 py-3 text-base font-medium transition-colors hover:border-ink ${focusRing}`

type State = { kind: 'idle' } | { kind: 'loading' } | { kind: 'error'; error: ApiError } | { kind: 'ready' }

export default function Letter({ billId, onDone, onText }: { billId: string; onDone: () => void; onText?: (text: string) => void }) {
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [text, setText] = useState('') // backend text, then whatever the user edits it into
  const [copied, setCopied] = useState<'no' | 'yes' | 'failed'>('no')
  const id = useId()
  const taRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => onText?.(text), [text, onText]) // the completed-step card shows a preview of it

  const generate = async () => {
    setState({ kind: 'loading' })
    const res = await generateLetter(billId)
    if (!res.ok) return setState({ kind: 'error', error: res.error })
    setText(res.data.letter_text)
    setState({ kind: 'ready' })
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied('yes')
    } catch {
      // Clipboard API blocked (embedded/older browsers): fall back to a selection copy.
      taRef.current?.select()
      setCopied(document.execCommand('copy') ? 'yes' : 'failed')
    }
  }

  const print = () => {
    // Switch the print stylesheet from the report to the letter for this one print.
    document.documentElement.classList.add('print-letter')
    window.print()
    document.documentElement.classList.remove('print-letter')
  }

  if (state.kind === 'idle') {
    return (
      <div>
        <p className="text-muted">
          A polite letter to the hospital asking them to explain the flagged lines. You can edit it before sending.
        </p>
        <div className="mt-5 flex flex-col gap-[10px]">
          <button type="button" onClick={generate} className={`${btnPrimary.replace('px-6 py-3', 'px-5 py-[14px]')} w-full whitespace-normal leading-snug`}>
            <span className="line-clamp-2">Write a clarification letter</span>
          </button>
          <button type="button" onClick={onDone} className={`${btnSecondary.replace('px-6 py-3', 'px-5 py-[14px]')} w-full whitespace-normal leading-snug`}>
            No thanks
          </button>
        </div>
      </div>
    )
  }

  if (state.kind === 'loading') {
    return (
      <div aria-live="polite" className="flex items-center gap-3 py-2">
        <span className="h-3 w-3 animate-pulse rounded-full bg-ink" aria-hidden="true" />
        <p className="animate-pulse font-medium">Writing your letter…</p>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div role="alert" className="rounded-2xl border border-ink/20 px-4 py-3 text-sm">
        <p>We couldn't write the letter ({state.error.message}). Your report is unaffected.</p>
        <div className="mt-3 flex flex-wrap gap-3">
          <button type="button" onClick={generate} className={`${btnPrimary} px-5 py-2 text-sm`}>
            Try again
          </button>
          <button type="button" onClick={onDone} className={`${btnSecondary} px-5 py-2 text-sm`}>
            No thanks, I'm done
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <p className="rounded-2xl bg-surface px-4 py-3 text-sm print:hidden">
        <strong>Read this before sending.</strong> Check the names, amounts and dates against your bill, and add your
        own details where marked. You are responsible for what you send.
      </p>

      <label htmlFor={id} className="sr-only">
        Clarification letter
      </label>
      <textarea
        id={id}
        ref={taRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setCopied('no')
        }}
        rows={22}
        spellCheck
        className={`mt-4 w-full rounded-2xl border border-ink/20 px-4 py-3 font-sans text-base leading-relaxed print:hidden ${focusRing}`}
      />
      {/* Textareas clip when printed; paper gets the same text as a plain block. */}
      <div className="hidden whitespace-pre-wrap text-base leading-relaxed print:block">{text}</div>

      <div className="mt-4 flex flex-wrap items-center gap-3 print:hidden">
        <button type="button" onClick={copy} className={btnPrimary}>
          Copy
        </button>
        <button type="button" onClick={print} className={btnSecondary}>
          Print / Save as PDF
        </button>
        <span role="status" aria-live="polite" className="text-sm text-muted">
          {copied === 'yes' && 'Copied to clipboard.'}
          {copied === 'failed' && 'Copy is blocked in this browser — select the text and copy it yourself.'}
        </span>
      </div>

      <button type="button" onClick={onDone} className={`mt-6 rounded-full px-2 py-1 text-sm font-medium text-muted underline-offset-4 hover:text-ink hover:underline print:hidden ${focusRing}`}>
        Done — back to the start
      </button>
    </div>
  )
}
