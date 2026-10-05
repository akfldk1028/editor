import { memo } from 'react'
import { Card } from '@/elements/workspace'
import { MapPin } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { PnuInfo, ZoneInfo, LandInfoResponse } from '@/features/land/api'

interface LandInfoCardProps {
  pnu: PnuInfo
  zoneInfo: ZoneInfo | null
  landInfo: LandInfoResponse | null
}

function formatPnu(pnu: string): string {
  if (pnu.length !== 19) return pnu
  return `${pnu.slice(0, 5)}-${pnu.slice(5, 8)}-${pnu.slice(8, 10)}-${pnu.slice(10, 11)}-${pnu.slice(11, 15)}-${pnu.slice(15)}`
}

function formatPrice(price: number | null | undefined): string {
  if (!price) return '-'
  if (price >= 10000) {
    const man = Math.floor(price / 10000)
    const rest = price % 10000
    return rest > 0 ? `${man.toLocaleString()}만 ${rest.toLocaleString()}원/m²` : `${man.toLocaleString()}만원/m²`
  }
  return `${price.toLocaleString()}원/m²`
}

export const LandInfoCard = memo(function LandInfoCard({
  pnu,
  zoneInfo,
  landInfo,
}: LandInfoCardProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-(--color-accent-primary-light) flex items-center justify-center shrink-0">
          <MapPin className="w-5 h-5 text-(--color-accent-primary)" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-heading-small text-(--color-text-primary)">
            {t('land.landInfo')}
          </h3>
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            <InfoItem label="PNU" value={formatPnu(pnu.pnu)} />
            {pnu.address && (
              <InfoItem label={t('land.address')} value={pnu.address} />
            )}
            {zoneInfo && zoneInfo.zones.length > 0 && (
              <InfoItem
                label={t('land.zoning')}
                value={zoneInfo.zones.join(', ')}
              />
            )}
            {landInfo?.land_area_m2 && (
              <InfoItem
                label={t('land.area')}
                value={`${landInfo.land_area_m2.toLocaleString()}m²`}
              />
            )}
            {landInfo?.official_land_price && (
              <InfoItem
                label={t('land.landPrice')}
                value={formatPrice(landInfo.official_land_price)}
              />
            )}
            {landInfo?.land_use_situation && (
              <InfoItem
                label={t('land.landUse')}
                value={landInfo.land_use_situation}
              />
            )}
          </div>
        </div>
      </div>
    </Card>
  )
})

const InfoItem = memo(function InfoItem({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div>
      <span className="text-label-small text-(--color-text-tertiary) block">
        {label}
      </span>
      <span className="text-body-medium text-(--color-text-primary) break-all">
        {value}
      </span>
    </div>
  )
})
