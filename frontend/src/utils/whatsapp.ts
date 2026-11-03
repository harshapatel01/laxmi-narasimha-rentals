export interface BookingWhatsAppDetails {
  reference: string
  customerName: string | null
  phone: string
  vehicleName: string
  startAt: string
  endAt: string
  status: string
}

export function bookingWhatsAppUrl(booking: BookingWhatsAppDetails): string | null {
  const phone = booking.phone.replace(/[^\d+]/g, '')
  const digits = phone.startsWith('+') ? phone.slice(1) : phone
  const indianMobile = digits.startsWith('91') ? digits.slice(2) : digits
  if (!/^[6-9]\d{9}$/.test(indianMobile)) return null

  const statusText: Record<string, string> = {
    pending: 'Your booking request is pending confirmation.',
    awaiting_payment: 'Your booking request is awaiting payment and confirmation.',
    confirmed: 'Your booking is confirmed.',
    rejected: 'Your booking request was rejected.',
    cancelled: 'Your booking was cancelled.',
  }
  const statusMessage = statusText[booking.status]
  if (!statusMessage) return null

  const message = [
    `Laxmi Narasimha Rentals booking ${booking.reference}`,
    booking.customerName ? `Hello ${booking.customerName},` : 'Hello,',
    `Vehicle: ${booking.vehicleName}`,
    `Dates: ${new Date(booking.startAt).toLocaleString()} to ${new Date(booking.endAt).toLocaleString()}`,
    statusMessage,
  ].join('\n')
  return `https://wa.me/91${indianMobile}?text=${encodeURIComponent(message)}`
}
