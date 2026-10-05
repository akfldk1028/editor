import { memo, useState, useCallback } from 'react'
import { Card } from '@/elements/workspace'
import { ChevronDown, ChevronRight, Gavel } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { LawArticlesResponse } from '@/features/land/api'

interface LawArticleListProps {
  lawArticles: LawArticlesResponse
}

export const LawArticleList = memo(function LawArticleList({
  lawArticles,
}: LawArticleListProps) {
  const { t } = useTranslation()
  const [isOpen, setIsOpen] = useState(false)

  const handleToggle = useCallback(() => {
    setIsOpen(prev => !prev)
  }, [])

  return (
    <Card>
      <button
        type="button"
        onClick={handleToggle}
        className="flex items-center gap-2 w-full text-left"
      >
        {isOpen ? (
          <ChevronDown className="w-5 h-5 text-(--color-text-secondary)" />
        ) : (
          <ChevronRight className="w-5 h-5 text-(--color-text-secondary)" />
        )}
        <Gavel className="w-5 h-5 text-(--color-text-secondary)" />
        <h3 className="text-heading-small text-(--color-text-primary)">
          {t('land.lawArticles')}
        </h3>
        <span className="text-label-small text-(--color-text-tertiary) ml-auto">
          {lawArticles.total_count} {t('land.articles')}
        </span>
      </button>

      {isOpen && (
        <div className="mt-4 space-y-4">
          {[{ query: t('land.lawArticles'), results: lawArticles.articles }].map((group) => (
            <div key={group.query}>
              <h4 className="text-label-small text-(--color-accent-primary) mb-2">
                "{group.query}" ({group.results.length})
              </h4>
              <div className="space-y-2">
                {group.results.map((article, i) => (
                  <div
                    key={`${group.query}-${article.hang_id}-${i}`}
                    className="p-3 rounded-lg border border-(--color-border-default) bg-(--color-background-secondary)"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-body-small font-medium text-(--color-text-primary)">
                        {article.law_name}
                      </span>
                      <span className="text-label-small text-(--color-text-tertiary)">
                        {article.article}
                      </span>
                      {article.law_type && (
                        <span className="text-label-small px-1.5 py-0.5 rounded bg-(--color-background-secondary) text-(--color-text-tertiary)">
                          {article.law_type}
                        </span>
                      )}
                    </div>
                    <p className="text-body-small text-(--color-text-secondary) line-clamp-3">
                      {article.content}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {lawArticles.errors.length > 0 && (
            <div className="p-3 rounded-lg border border-(--color-semantic-error)/30 bg-(--color-semantic-error-light)">
              <span className="text-label-small text-(--color-semantic-error)">
                {t('land.searchErrors')}:
              </span>
              <ul className="mt-1 text-body-small text-(--color-text-secondary)">
                {lawArticles.errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  )
})
