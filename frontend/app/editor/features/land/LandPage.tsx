'use client'

import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useLandAnalyze, useLandZones, useLandStats } from './useLand'
import { LandSearchForm } from './components/LandSearchForm'
import { LandInfoCard } from './components/LandInfoCard'
import { RegulationSummary } from './components/RegulationSummary'
import { ExtendedRegulations } from './components/ExtendedRegulations'
import { LawArticleList } from './components/LawArticleList'
import { RestrictionsList } from './components/RestrictionsList'
import { LandStatsPanel } from './components/LandStatsPanel'
import type { LandAnalyzeRequest } from '@/features/land/api'

export function LandPage() {
  const { t } = useTranslation()
  const analyzeMutation = useLandAnalyze()
  const { data: zonesData, error: zonesError } = useLandZones()
  const { data: statsData, error: statsError } = useLandStats()

  const handleSubmit = useCallback(
    (req: LandAnalyzeRequest) => {
      analyzeMutation.mutate(req)
    },
    [analyzeMutation],
  )

  const result = analyzeMutation.data

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-display-medium">{t('land.title')}</h1>
        <p className="text-body-medium text-(--color-text-secondary) mt-1">
          {t('land.desc')}
        </p>
      </div>

      {/* Search Form */}
      <LandSearchForm
        zones={zonesData?.zones}
        isLoading={analyzeMutation.isPending}
        onSubmit={handleSubmit}
      />
      {[zonesError, statsError].filter(Boolean).map((error, index) => (
        <p key={index} role="alert" className="text-body-medium text-(--color-semantic-error)">{error?.message}</p>
      ))}

      {/* Loading */}
      {analyzeMutation.isPending && (
        <div className="flex items-center justify-center py-12">
          <div className="w-8 h-8 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
          <span className="ml-3 text-body-medium text-(--color-text-secondary)">
            {t('land.analyzing')}
          </span>
        </div>
      )}

      {/* Error */}
      {analyzeMutation.isError && (
        <div className="p-4 rounded-lg border border-(--color-semantic-error)/30 bg-(--color-semantic-error-light)">
          <span className="text-body-medium text-(--color-semantic-error)">
            {analyzeMutation.error.message}
          </span>
        </div>
      )}

      {result?.errors?.map((error) => <p key={error} role="alert" className="text-body-medium text-(--color-semantic-error)">{error}</p>)}
      {/* Warning */}
      {result?.warning && (
        <div className="p-4 rounded-lg border border-(--color-semantic-warning)/30 bg-(--color-semantic-warning-light)">
          <span className="text-body-medium text-(--color-semantic-warning)">
            {result.warning}
          </span>
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {result.pnu && <LandInfoCard
            pnu={result.pnu}
            zoneInfo={result.zone_info}
            landInfo={result.land_info}
          />}

          {result.regulations && (
            <RegulationSummary regulations={result.regulations} />
          )}

          {result.regulations?.extended && (
            <ExtendedRegulations extended={result.regulations.extended} />
          )}

          {result.law_articles && (
            <LawArticleList lawArticles={result.law_articles} />
          )}

          <RestrictionsList restrictions={result.restrictions} />
        </>
      )}

      {/* Stats */}
      {statsData && <LandStatsPanel stats={statsData} />}
    </div>
  )
}
