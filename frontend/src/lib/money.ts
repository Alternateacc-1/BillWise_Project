/**
 * Format an API decimal string as Indian rupees: "1234567.5" -> "₹12,34,567.50".
 * String manipulation only — the value is never converted to a Number.
 * Fractional part is kept verbatim and padded to 2 places ("100" -> "₹100.00").
 */
export function formatINR(value: string | undefined | null): string {
  if (value == null || value.trim() === '') return '—'
  let s = value.trim()
  const negative = s.startsWith('-')
  if (negative) s = s.slice(1)

  const [intRaw = '', fracRaw = ''] = s.split('.')
  const int = intRaw.replace(/^0+(?=\d)/, '') || '0'
  if (!/^\d+$/.test(int) || !/^\d*$/.test(fracRaw)) return value

  // Indian grouping: last 3 digits, then groups of 2.
  let grouped = int
  if (int.length > 3) {
    const head = int.slice(0, -3)
    const tail = int.slice(-3)
    grouped = head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + tail
  }

  const frac = (fracRaw + '00').slice(0, 2)
  return `${negative ? '-' : ''}₹${grouped}.${frac}`
}
