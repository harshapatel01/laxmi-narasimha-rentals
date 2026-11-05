import { useState } from 'react'
import { Bike, BusFront, CarFront } from 'lucide-react'

import { vehicleArtworkFor } from '../utils/vehicleArtwork'

interface VehicleArtworkProps {
  alt: string
  categoryName: string
  className?: string
  imageUrl?: string
  loading?: 'eager' | 'lazy'
}

export function VehicleArtwork({
  alt,
  categoryName,
  className = '',
  imageUrl,
  loading = 'lazy',
}: VehicleArtworkProps) {
  const artwork = vehicleArtworkFor(categoryName)
  const primaryImage = imageUrl ?? artwork.imageUrl
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)
  const [failedSecondaryUrl, setFailedSecondaryUrl] = useState<string | null>(null)
  const failed = failedImageUrl === primaryImage
  const secondaryFailed = artwork.secondaryImageUrl === failedSecondaryUrl

  const FallbackIcon = artwork.kind === 'bike'
    ? Bike
    : artwork.kind === 'bus'
      ? BusFront
      : CarFront

  return (
    <span className={`vehicle-artwork vehicle-artwork-${artwork.kind} ${className}`}>
      {failed ? (
        <span
          className="vehicle-artwork-fallback"
          role={alt ? 'img' : undefined}
          aria-label={alt || undefined}
          aria-hidden={alt ? undefined : true}
        >
          <FallbackIcon aria-hidden="true" />
        </span>
      ) : (
        <>
          <img
            className="vehicle-artwork-primary"
            src={primaryImage}
            alt={alt}
            loading={loading}
            fetchPriority={loading === 'eager' ? 'high' : undefined}
            onError={() => setFailedImageUrl(primaryImage)}
          />
          {!imageUrl && artwork.secondaryImageUrl && !secondaryFailed && (
          <img
            className="vehicle-artwork-secondary"
            src={artwork.secondaryImageUrl}
            alt=""
            aria-hidden="true"
            loading={loading}
            onError={() => setFailedSecondaryUrl(artwork.secondaryImageUrl ?? null)}
          />
          )}
        </>
      )}
    </span>
  )
}
