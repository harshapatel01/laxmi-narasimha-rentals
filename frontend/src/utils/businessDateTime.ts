const BUSINESS_TIME_ZONE = 'Asia/Kolkata'
const BUSINESS_UTC_OFFSET_MINUTES = 5 * 60 + 30

function businessDateParts(value: Date): Record<string, string> {
  return Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: BUSINESS_TIME_ZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
      .formatToParts(value)
      .filter((part) => part.type !== 'literal')
      .map(({ type, value: partValue }) => [type, partValue]),
  )
}

export function defaultBusinessDateTime(daysFromNow: number, hour: number): string {
  const date = businessDateParts(new Date(Date.now() + daysFromNow * 24 * 60 * 60 * 1000))
  return `${date.year}-${date.month}-${date.day}T${String(hour).padStart(2, '0')}:00`
}

export function businessDateTimeToUtc(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value)
  if (!match) {
    throw new Error('Select a valid pickup and return date/time.')
  }
  const [, year, month, day, hour, minute] = match
  const utcMilliseconds =
    Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute))
    - BUSINESS_UTC_OFFSET_MINUTES * 60_000
  const normalized = new Date(utcMilliseconds)
  if (
    normalized.getUTCFullYear() !== Number(year)
    || normalized.getUTCMonth() !== Number(month) - 1
    || normalized.getUTCDate() !== Number(day)
    || Number(hour) > 23
    || Number(minute) > 59
  ) {
    throw new Error('Select a valid pickup and return date/time.')
  }
  return normalized.toISOString()
}
