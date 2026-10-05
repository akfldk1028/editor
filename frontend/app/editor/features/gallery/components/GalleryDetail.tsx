/**
 * GalleryDetail - Full detail view for a gallery with 6 category tabs.
 * Shows a banner header with metadata and a tabbed grid of components.
 */

import { Badge, Button, Card } from '@/elements/workspace'
import type { ComponentTestResult } from '@/features/team-templates/api'
import { validationAPI } from '@/features/team-templates/api'
import type { Component, ComponentConfig, ComponentTypes, Gallery } from '@/lib/contracts/workspace'
import {
  ArrowLeft,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  Copy,
  Cpu,
  Download,
  Loader2,
  Network,
  Play,
  Plug,
  Timer,
  Wrench,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ComponentCard } from './ComponentCard'

// --------------- Tab Definitions ---------------

interface TabDef {
  key: CategoryKey
  label: string
  icon: typeof Bot
  type: ComponentTypes
}

type CategoryKey = 'teams' | 'agents' | 'models' | 'tools' | 'workbenches' | 'terminations'

const TABS: TabDef[] = [
  { key: 'teams', label: 'Teams', icon: Network, type: 'team' },
  { key: 'agents', label: 'Agents', icon: Bot, type: 'agent' },
  { key: 'models', label: 'Models', icon: Cpu, type: 'model' },
  { key: 'tools', label: 'Tools', icon: Wrench, type: 'tool' },
  { key: 'workbenches', label: 'Workbenches', icon: Plug, type: 'workbench' },
  { key: 'terminations', label: 'Terminations', icon: Timer, type: 'termination' },
]

// --------------- Helpers ---------------

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function getComponentLabel(comp: Component<ComponentConfig>): string {
  // Try label, then config.name, then provider short name
  if (comp.label) return comp.label
  const cfg = comp.config as unknown as Record<string, unknown>
  if (typeof cfg?.name === 'string') return cfg.name
  return comp.provider?.split('.').pop() ?? 'Component'
}

// --------------- Props ---------------

interface GalleryDetailProps {
  gallery: Gallery
  onBack: () => void
}

// --------------- Component ---------------

export function GalleryDetail({ gallery, onBack }: GalleryDetailProps) {
  const [activeTab, setActiveTab] = useState<CategoryKey>('teams')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Component testing state
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<ComponentTestResult | null>(null)
  const [logsExpanded, setLogsExpanded] = useState(false)
  const resultRef = useRef<HTMLDivElement>(null)

  // Cleanup copy timer on unmount
  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current)
    }
  }, [])

  // Scroll test result into view
  useEffect(() => {
    if (testResult && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [testResult])

  const config = gallery.config
  const metadata = config?.metadata
  const components = config?.components

  const counts: Record<CategoryKey, number> = {
    teams: components?.teams?.length ?? 0,
    agents: components?.agents?.length ?? 0,
    models: components?.models?.length ?? 0,
    tools: components?.tools?.length ?? 0,
    workbenches: components?.workbenches?.length ?? 0,
    terminations: components?.terminations?.length ?? 0,
  }

  const totalCount = Object.values(counts).reduce((sum, n) => sum + n, 0)
  const activeItems = (components?.[activeTab] ?? []) as Component<ComponentConfig>[]
  const activeTabDef = TABS.find((t) => t.key === activeTab)!

  // -- Handlers --

  const handleTabChange = useCallback((key: CategoryKey) => {
    setActiveTab(key)
  }, [])

  const handleDownloadGallery = useCallback(() => {
    const name = config?.name?.replace(/\s+/g, '_').toLowerCase() ?? 'gallery'
    downloadJson(config, `${name}.json`)
  }, [config])

  const handleDownloadComponent = useCallback((comp: Component<ComponentConfig>, index: number) => {
    const label = getComponentLabel(comp).replace(/\s+/g, '_').toLowerCase()
    downloadJson(comp, `${label}_${index}.json`)
  }, [])

  const handleCopyComponent = useCallback((comp: Component<ComponentConfig>, id: string) => {
    const json = JSON.stringify(comp, null, 2)
    navigator.clipboard
      .writeText(json)
      .then(() => {
        setCopiedId(id)
        if (copyTimerRef.current) clearTimeout(copyTimerRef.current)
        copyTimerRef.current = setTimeout(() => setCopiedId(null), 2000)
      })
      .catch(() => {
        /* Clipboard API unavailable */
      })
  }, [])

  const handleTestComponent = useCallback(async (comp: Component<ComponentConfig>, id: string) => {
    setTestingId(id)
    setTestResult(null)
    setLogsExpanded(false)
    try {
      const result = await validationAPI.test(comp, 60)
      setTestResult({ ...result, logs: result.logs ?? [] })
    } catch (err) {
      setTestResult({ status: false, message: String(err), logs: [], data: undefined })
    } finally {
      setTestingId(null)
    }
  }, [])

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={onBack}
        aria-label="Back to gallery list"
        className="inline-flex items-center gap-1.5 text-sm text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) rounded-md px-1 py-0.5"
      >
        <ArrowLeft className="w-4 h-4" aria-hidden="true" />
        Back to Galleries
      </button>

      {/* Banner Header */}
      <Card className="bg-(--color-surface-card)">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h2 className="text-display-small truncate">{config?.name ?? 'Gallery'}</h2>
            {metadata?.description && (
              <p className="text-body-medium text-(--color-text-secondary) mt-1">
                {metadata.description}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3 mt-3">
              {metadata?.version && (
                <span className="inline-block">
                  <Badge variant="primary">v{metadata.version}</Badge>
                </span>
              )}
              {metadata?.author && (
                <span className="text-body-small text-(--color-text-tertiary)">
                  by {metadata.author}
                </span>
              )}
              <span className="text-body-small text-(--color-text-tertiary)">
                {totalCount} component{totalCount !== 1 ? 's' : ''}
              </span>
              {metadata?.tags?.map((tag) => (
                <span key={tag} className="inline-block">
                  <Badge variant="default">{tag}</Badge>
                </span>
              ))}
            </div>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleDownloadGallery}
            aria-label="Download entire gallery as JSON"
          >
            <Download className="w-4 h-4 mr-1.5" aria-hidden="true" />
            Download Gallery
          </Button>
        </div>
      </Card>

      {/* Tabs */}
      <div
        role="tablist"
        aria-label="Component categories"
        className="flex flex-wrap gap-1 border-b border-(--color-border-default) pb-px"
      >
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key
          const TabIcon = tab.icon
          return (
            <button
              key={tab.key}
              role="tab"
              id={`tab-${tab.key}`}
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.key}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => handleTabChange(tab.key)}
              onKeyDown={(e) => {
                const idx = TABS.findIndex((t) => t.key === tab.key)
                if (e.key === 'ArrowRight') {
                  e.preventDefault()
                  const next = TABS[(idx + 1) % TABS.length]
                  if (!next) return
                  handleTabChange(next.key)
                  document.getElementById(`tab-${next.key}`)?.focus()
                } else if (e.key === 'ArrowLeft') {
                  e.preventDefault()
                  const prev = TABS[(idx - 1 + TABS.length) % TABS.length]
                  if (!prev) return
                  handleTabChange(prev.key)
                  document.getElementById(`tab-${prev.key}`)?.focus()
                }
              }}
              className={`
                inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-t-md
                transition-colors focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)
                ${
                  isActive
                    ? 'text-(--color-accent-primary) border-b-2 border-(--color-accent-primary) -mb-px'
                    : 'text-(--color-text-secondary) hover:text-(--color-text-primary) hover:bg-(--color-background-secondary)'
                }
              `}
            >
              <TabIcon className="w-4 h-4" aria-hidden="true" />
              {tab.label}
              <span className="inline-block">
                <Badge variant={isActive ? 'primary' : 'default'}>{counts[tab.key]}</Badge>
              </span>
            </button>
          )
        })}
      </div>

      {/* Tab Panel */}
      <div
        role="tabpanel"
        id={`tabpanel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        className="min-h-[200px]"
      >
        {activeItems.length === 0 ? (
          <Card className="text-center py-12">
            <activeTabDef.icon
              className="w-10 h-10 mx-auto text-(--color-text-tertiary) mb-3"
              aria-hidden="true"
            />
            <p className="text-body-medium text-(--color-text-secondary)">
              No {activeTabDef.label.toLowerCase()} in this gallery.
            </p>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {activeItems.map((comp, index) => {
              const label = getComponentLabel(comp)
              const uniqueId = `${activeTab}-${index}`
              const isCopied = copiedId === uniqueId
              const isTesting = testingId === uniqueId
              return (
                <ComponentCard
                  key={uniqueId}
                  label={label}
                  provider={comp.provider ?? ''}
                  description={comp.description}
                  componentType={activeTabDef.type}
                  actions={
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleTestComponent(comp, uniqueId)}
                        disabled={testingId !== null}
                        aria-label={`Test ${label}`}
                      >
                        {isTesting ? (
                          <>
                            <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" aria-hidden="true" />
                            Testing...
                          </>
                        ) : (
                          <>
                            <Play className="w-3.5 h-3.5 mr-1" aria-hidden="true" />
                            Test
                          </>
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled
                        title="Coming soon"
                        aria-label={`Use ${label} in team`}
                      >
                        Use in Team
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDownloadComponent(comp, index)}
                        aria-label={`Download ${label} as JSON`}
                      >
                        <Download className="w-3.5 h-3.5 mr-1" aria-hidden="true" />
                        JSON
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleCopyComponent(comp, uniqueId)}
                        aria-label={isCopied ? `Copied ${label}` : `Copy ${label} JSON`}
                      >
                        {isCopied ? (
                          <>
                            <Check
                              className="w-3.5 h-3.5 mr-1 text-(--color-semantic-success)"
                              aria-hidden="true"
                            />
                            Copied!
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5 mr-1" aria-hidden="true" />
                            Copy
                          </>
                        )}
                      </Button>
                    </>
                  }
                />
              )
            })}
          </div>
        )}
      </div>

      {/* Test Results Panel */}
      {testResult && (
        <div ref={resultRef}>
          <Card>
            <div className="flex items-center gap-3 mb-3">
              {testResult.status ? (
                <CircleCheck className="w-5 h-5 text-(--color-semantic-success) flex-shrink-0" />
              ) : (
                <CircleX className="w-5 h-5 text-(--color-semantic-error) flex-shrink-0" />
              )}
              <h3 className="text-heading-small">Test {testResult.status ? 'Passed' : 'Failed'}</h3>
              <button
                onClick={() => setTestResult(null)}
                className="ml-auto text-xs text-(--color-text-tertiary) hover:text-(--color-text-primary) transition-colors"
                aria-label="Dismiss test results"
              >
                Dismiss
              </button>
            </div>

            <p className="text-body-small text-(--color-text-secondary) mb-3">
              {testResult.message}
            </p>

            {(testResult.logs?.length ?? 0) > 0 && (
              <div>
                <button
                  onClick={() => setLogsExpanded((p) => !p)}
                  className="inline-flex items-center gap-1 text-sm font-medium text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors mb-2"
                >
                  {logsExpanded ? (
                    <ChevronDown className="w-4 h-4" />
                  ) : (
                    <ChevronRight className="w-4 h-4" />
                  )}
                  Logs ({testResult.logs.length})
                </button>
                {logsExpanded && (
                  <pre className="w-full px-4 py-3 rounded-md border border-(--color-border-default) bg-(--color-background-secondary) text-(--color-text-primary) text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
                    {testResult.logs.join('\n')}
                  </pre>
                )}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
