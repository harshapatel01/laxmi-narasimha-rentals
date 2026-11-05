export function suggestedSeatingCapacity(categoryName: string): number | undefined {
  return /bike|motorcycle|scooter/i.test(categoryName) ? 2 : undefined
}
