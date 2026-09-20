import type { Severity } from './lib/api'

/** Default label per verdict. Colour never carries meaning alone: every chip renders its text. */
export const CHIP_LABEL: Record<Severity, string> = {
  red: 'Above listed ceiling',
  amber: 'May need clarification',
  green: 'Within ceiling',
  gray: 'Not compared',
}

const SIZE = {
  md: 'px-2.5 py-0.5 text-xs',
  sm: 'px-2 py-0.5 text-[10px] leading-4',
  xs: 'px-1.5 py-px text-[9px] leading-3',
}

/** The one severity chip: tinted fill, 1px border, dark text (colours in index.css under `.chip-*`). */
export function Chip({
  tone,
  label = CHIP_LABEL[tone],
  size = 'md',
  className = '',
}: {
  tone: Severity
  label?: string
  size?: keyof typeof SIZE
  className?: string
}) {
  return <span className={`chip chip-${tone} ${SIZE[size]} ${className}`}>{label}</span>
}
