import { describe, expect, it } from 'vitest'
import { formatINR } from './money'

describe('formatINR', () => {
  it.each([
    ['100', '₹100.00'],
    ['0.05', '₹0.05'],
    ['999.00', '₹999.00'],
    ['12947.61', '₹12,947.61'],
    ['1234567.50', '₹12,34,567.50'],
    ['10000000', '₹1,00,00,000.00'],
    ['0', '₹0.00'],
  ])('%s -> %s', (input, expected) => {
    expect(formatINR(input)).toBe(expected)
  })

  it('grouping boundaries: 3 digits, then 2s', () => {
    expect(formatINR('1000')).toBe('₹1,000.00')
    expect(formatINR('99999')).toBe('₹99,999.00')
    expect(formatINR('100000')).toBe('₹1,00,000.00')
    expect(formatINR('27690.18')).toBe('₹27,690.18')
  })

  it('pads or truncates the fraction to exactly 2 digits without rounding', () => {
    expect(formatINR('100.5')).toBe('₹100.50')
    expect(formatINR('1.999')).toBe('₹1.99')
  })

  it('handles negatives, leading zeros and values beyond float precision', () => {
    expect(formatINR('-2500')).toBe('-₹2,500.00')
    expect(formatINR('0042')).toBe('₹42.00')
    expect(formatINR('12345678901234567890.12')).toBe('₹1,23,45,67,89,01,23,45,67,890.12')
  })

  it('returns a dash for missing values and the raw string for junk', () => {
    expect(formatINR(undefined)).toBe('—')
    expect(formatINR('')).toBe('—')
    expect(formatINR('abc')).toBe('abc')
  })
})
