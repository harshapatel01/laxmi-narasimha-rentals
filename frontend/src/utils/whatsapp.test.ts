import { describe, expect, it } from 'vitest'

import { bookingWhatsAppUrl } from './whatsapp'

describe('booking WhatsApp message links', () => {
  const booking = {
    reference: 'LNR-260101-ABC123',
    customerName: 'Anita Rao',
    phone: '+91 98765 43210',
    vehicleName: 'Honda City',
    startAt: '2027-01-02T10:00:00Z',
    endAt: '2027-01-03T10:00:00Z',
    status: 'confirmed',
  }

  it('normalizes an Indian mobile and URL-encodes a manual confirmation', () => {
    const url = bookingWhatsAppUrl(booking)
    expect(url).toContain('https://wa.me/919876543210?text=')
    expect(url).toContain(encodeURIComponent('Your booking is confirmed.'))
    expect(decodeURIComponent(url ?? '')).toContain(booking.reference)
  })

  it('rejects invalid numbers and unsupported states', () => {
    expect(bookingWhatsAppUrl({ ...booking, phone: '12345' })).toBeNull()
    expect(bookingWhatsAppUrl({ ...booking, status: 'completed' })).toBeNull()
  })
})
