import { afterEach, describe, expect, it, vi } from 'vitest'

import { businessDateTimeToUtc, defaultBusinessDateTime } from './businessDateTime'

describe('business date and time conversion', () => {
  afterEach(() => vi.useRealTimers())

  it('converts India-local rental times to the same UTC instant on any browser timezone', () => {
    expect(businessDateTimeToUtc('2026-11-02T14:00')).toBe('2026-11-02T08:30:00.000Z')
  })

  it('rejects invalid date-time values instead of sending an inaccurate availability period', () => {
    expect(() => businessDateTimeToUtc('2026-02-30T10:00')).toThrow()
    expect(() => businessDateTimeToUtc('2026-11-02T25:00')).toThrow()
  })

  it('builds default date-time values in the business timezone', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-01T22:00:00.000Z'))
    expect(defaultBusinessDateTime(1, 10)).toBe('2026-11-03T10:00')
  })
})
