import type { LngLat } from '../lib/engine/types'
import { containsPoint } from '../lib/layers/parcelOutline'
import type { KnownParcel } from '../lib/picks'

/**
 * The last few parcels seen (hover or click), newest first. A point inside one
 * of them needs no new request.
 */
export class ParcelCache {
  private entries: KnownParcel[] = []
  constructor(private readonly limit = 20) {}

  find(at: LngLat): KnownParcel | null {
    const found = this.entries.find((entry) => containsPoint(entry.geometry, at)) ?? null
    if (found) this.add(found)
    return found
  }

  get(pnu: string): KnownParcel | null {
    return this.entries.find((entry) => entry.pnu === pnu) ?? null
  }

  add(parcel: KnownParcel) {
    this.entries = [parcel, ...this.entries.filter((entry) => entry.pnu !== parcel.pnu)].slice(0, this.limit)
  }
}
