import { describe, expect, it } from 'vitest'
import { suggestedSeatingCapacity } from './vehicleDefaults'

describe('suggestedSeatingCapacity', () => {
  it.each(['Bike', 'Motorcycle', 'Scooter'])('suggests two seats for %s', (category) => {
    expect(suggestedSeatingCapacity(category)).toBe(2)
  })

  it('does not override the existing car seating default', () => {
    expect(suggestedSeatingCapacity('Sedan')).toBeUndefined()
    expect(suggestedSeatingCapacity('SUV')).toBeUndefined()
  })
})
