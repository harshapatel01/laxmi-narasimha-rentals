import { describe, expect, it } from 'vitest'

import { vehicleArtworkFor } from './vehicleArtwork'

describe('vehicleArtworkFor', () => {
  it.each([
    ['Cars', 'car'],
    ['SUV', 'car'],
    ['Motorcycles', 'bike'],
    ['Scooter', 'bike'],
    ['Minibus', 'bus'],
    ['Tempo Traveller', 'bus'],
  ] as const)('selects suitable artwork for %s', (category, kind) => {
    expect(vehicleArtworkFor(category).kind).toBe(kind)
  })

  it('uses a mixed vehicle composition for unrecognized categories', () => {
    const artwork = vehicleArtworkFor('Adventure rentals')

    expect(artwork.kind).toBe('mixed')
    expect(artwork.secondaryImageUrl).toContain('images.unsplash.com')
  })
})
