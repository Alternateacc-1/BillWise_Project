/** BillWise glyph, inlined from public/logo.svg so `currentColor` resolves. Set height only — width follows the 30:36 box. */
export function Logo({ height = 40, className = '', decorative = false }: { height?: number; className?: string; decorative?: boolean }) {
  return (
    <svg
      viewBox="0 0 30 36"
      height={height}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : 'BillWise'}
      aria-hidden={decorative ? 'true' : undefined}
      className={className}
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M0 5A5 5 0 0 1 5 0H25A5 5 0 0 1 30 5V31L25 36L20 31L15 36L10 31L5 36L0 31ZM6.4 17.8L13.2 24.6L24.6 13.2L21.4 10L13.2 18.2L9.6 14.6Z"
      />
    </svg>
  )
}

/** Glyph beside the wordmark: print header and the flow page header. */
export function Lockup({ height = 28 }: { height?: number }) {
  return (
    <span className="inline-flex items-center gap-3">
      <Logo height={height} />
      <span aria-hidden="true" className="text-2xl font-bold tracking-[-0.02em] text-ink">
        BillWise
      </span>
    </span>
  )
}
