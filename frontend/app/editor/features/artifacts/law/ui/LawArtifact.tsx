'use client'

import { MotionConfig } from 'framer-motion'
import { Map as MapIcon, RotateCcw, Scale } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import LandAnalysisPanel from '../../../land-map/components/LandAnalysisPanel'
import { LawArticlesList } from '../../../land-map/components/LawArticlesList'
import type { LandAnalysisResult, LawArticleItem } from '../../../land-map/lib/types'
import { sendCommand } from '@/lib/orchestrator-runs/commands'
import { isValidDate } from '@/lib/orchestrator-runs/conditions'
import { ArtifactChrome } from '../../../shell/artifact-host/ArtifactChrome'

import type { ArtifactProps, ShellApi } from '../../../shell/artifact-types'
import type { LawAnalysis } from '../api/analyze'
import { type Conditions, defaultConditions, describeConditions } from '../lib/conditions'
import { summarize } from '../lib/summary'
import { lawArtifact } from '../manifest'
import { useLawAnalysis } from '../model/useLawAnalysis'
import { ConditionsMenu } from './ConditionsMenu'
import { OrchestratorTab } from './OrchestratorTab'
import { SetbacksTab } from './SetbacksTab'
import { ReviewTab } from './ReviewTab'
import './law.css'

/** 법규·한계: the selected site's regulations from `POST /land/analyze`, by tab. */
export default function LawArtifact({ tab = 'review', params, shell }: ArtifactProps) {
  const [editedConditions, setEditedConditions] = useState<{ params: typeof params; value: Conditions } | null>(null)
  const [initialConditions] = useState<Conditions>(defaultConditions)
  const conditions = useMemo(() => editedConditions?.params === params ? editedConditions.value : {
    ...initialConditions,
    ...(params.assessmentDate && isValidDate(params.assessmentDate) ? { assessmentDate: params.assessmentDate } : {}),
    ...(params.buildingType !== undefined ? { buildingType: params.buildingType } : {}),
  }, [editedConditions, params, initialConditions])
  const setConditions = (value: Conditions) => setEditedConditions({ params, value })
  const [appliedParams, setAppliedParams] = useState<typeof params | null>(null)
  const effectiveTab = appliedParams === params ? tab : params.tab ?? tab
  const orchestrator = effectiveTab === 'orchestrator'
  const { target, phase, rerun } = useLawAnalysis(params, conditions, !orchestrator)
  const analysis = phase.kind === 'ready' ? phase.analysis : null
  const title = target.kind === 'site' ? target.address || `PNU ${target.pnu}` : '법규·한계'
  const subtitle = target.kind === 'site' ? describeConditions(conditions) : null

  // `shell.openArtifact('law', {tab})` lands on that tab; each open (new params object) applies it once.
  useEffect(() => {
    setAppliedParams(params)
    const wanted = params.tab
    if (wanted && lawArtifact.tabs?.some((candidate) => candidate.id === wanted)) shell.setTab(wanted)
  }, [params, shell])

  return (
    <>
      <ArtifactChrome
        actions={
          !orchestrator && <button className="artifact-primary" disabled={target.kind !== 'site' || phase.kind === 'loading'} onClick={rerun} type="button">
            <RotateCcw aria-hidden="true" size={12} /><span>{phase.kind === 'loading' ? '새로고침 중' : '새로고침'}</span>
          </button>
        }
        menu={orchestrator ? undefined : <ConditionsMenu onChange={setConditions} value={conditions} />}
        title={<><strong title={title}>{title}</strong>{subtitle && <span>{subtitle}</span>}</>}
      />
      <div aria-busy={phase.kind === 'loading'} className="law-artifact" data-tab={tab}>
        {target.kind === 'resolving' && <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 선택한 대지를 확인하는 중</p>}
        {target.kind === 'error' && <p className="law-note" data-kind="error" role="alert">{target.text}</p>}
        {target.kind === 'none' && <Empty shell={shell} />}
        {target.kind === 'site' && (
          <>
            {target.notice && <p className="law-note" data-kind="notice" role="status">{target.notice}</p>}
            {phase.kind === 'loading' && !orchestrator && (
              <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 법규를 분석하는 중 — 조례·조문 조회에 수십 초가 걸릴 수 있어요</p>
            )}
            {phase.kind === 'error' && !orchestrator && <p className="law-note" data-kind="error" role="alert">{phase.text}</p>}
            {orchestrator ? (
              <OrchestratorTab address={target.address} editor={analysis ? summarize(analysis) : null} key={target.pnu} pnu={target.pnu} project={params.project} shell={shell} />
            ) : (
              analysis && <Body address={target.address} analysis={analysis} site={{ pnu: target.pnu, address: target.address, assessmentDate: conditions.assessmentDate }} tab={effectiveTab} />
            )}
          </>
        )}
      </div>
    </>
  )
}

function Body({ tab, analysis, site, address }: { tab: string; analysis: LawAnalysis; site: { pnu: string; address?: string; assessmentDate: string }; address: string }) {
  switch (tab) {
    case 'regulations':
      // The /land page's panel, unchanged (its own dark palette, see .law-legacy). `zone_info` caps may be
      // null here, which the panel's older type does not say; it never reads them.
      return (
        <section aria-label="규제" className="law-legacy">
          <MotionConfig reducedMotion="user">
            <LandAnalysisPanel address={address || undefined} analysis={analysis as LandAnalysisResult} />
          </MotionConfig>
        </section>
      )
    case 'articles':
      return analysis.law_articles?.articles?.length ? (
        <section aria-label="조문" className="law-legacy">
          <LawArticlesList fullText lawArticles={analysis.law_articles} onSelectArticle={(article) => askAboutArticle(article, site)} />
        </section>
      ) : (
        <p className="law-note" data-kind="notice">
          조문 검색 결과를 받지 못했어요 — 법규가 없다는 뜻이 아니에요
          {analysis.law_articles?.errors?.length ? ` (${analysis.law_articles.errors.join(' / ')})` : ' (검색이 결과를 돌려주지 않음)'}. 검토 조항 탭에서 조항별 근거를 확인하세요.
        </p>
      )
    case 'setbacks':
      return <SetbacksTab analysis={analysis} />
    default:
      return <ReviewTab analysis={analysis} site={site} />
  }
}

/** A searched article clicked in the 조문 tab: the conversation asks the Law Agent about exactly it (its graph id). */
function askAboutArticle(article: LawArticleItem, site: { pnu: string; address?: string; assessmentDate: string }) {
  const law = article.law_name || '법령'
  const kind = article.law_type === '시행령' ? 'decree' : article.law_type === '시행규칙' ? 'rule' : 'act'
  const instrument = kind === 'act' ? law : `${law} ${article.law_type}`
  const label = [instrument, article.article].filter(Boolean).join(' ')
  sendCommand({
    kind: 'ask', text: '이 대지에서 이 조문은 어떻게 적용되나요?', role: 'law', site,
    clause: { item_id: `article-${article.hang_id}`, title: label, refs: [{ instrument, kind, article: article.article ?? null, clause: null, ...(article.hang_id ? { hang_id: article.hang_id } : {}) }],
      reason: '조문 탭에서 고른 조문', status: 'needs_check', basis: '검색으로 찾은 조문 — 적용 여부는 Law Agent 답으로 확인' },
  })
}

function Empty({ shell }: { shell: ShellApi }) {
  return (
    <div className="law-empty">
      <Scale aria-hidden="true" size={24} />
      <p>먼저 대지를 선택하세요</p>
      <small>대지 지도에서 필지를 고르고 “이 대지로 선택”을 누르면 여기서 법규를 분석해요.</small>
      <button className="artifact-primary" onClick={() => shell.openArtifact('site-map')} type="button">
        <MapIcon aria-hidden="true" size={12} /><span>대지 지도 열기</span>
      </button>
    </div>
  )
}
