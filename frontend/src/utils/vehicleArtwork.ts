export type VehicleArtworkKind = 'car' | 'bike' | 'bus' | 'mixed'

export interface VehicleArtworkAsset {
  kind: VehicleArtworkKind
  imageUrl: string
  secondaryImageUrl?: string
}

const vehicleArt = {
  car: 'https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1400&q=85',
  bike: 'https://images.unsplash.com/photo-1558981806-ec527fa84c39?auto=format&fit=crop&w=1200&q=85',
  bus: 'https://images.unsplash.com/photo-1570125909232-eb263c188f7e?auto=format&fit=crop&w=1400&q=85',
}

export function vehicleArtworkFor(categoryName: string): VehicleArtworkAsset {
  const category = categoryName.toLowerCase()

  if (/\b(bikes?|motorbikes?|motorcycles?|scooters?|two[- ]wheelers?)\b/.test(category)) {
    return { kind: 'bike', imageUrl: vehicleArt.bike }
  }
  if (/\b(bus(?:es)?|mini[- ]?bus(?:es)?|vans?|coach(?:es)?|tempo travellers?|people carriers?)\b/.test(category)) {
    return { kind: 'bus', imageUrl: vehicleArt.bus }
  }
  if (/\b(cars?|sedans?|suvs?|hatchbacks?|four[- ]wheelers?)\b/.test(category)) {
    return { kind: 'car', imageUrl: vehicleArt.car }
  }

  return {
    kind: 'mixed',
    imageUrl: vehicleArt.car,
    secondaryImageUrl: vehicleArt.bike,
  }
}
