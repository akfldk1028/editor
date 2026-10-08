'use client'

import { MotionConfig } from 'framer-motion'
import { Map as MapIcon, RotateCcw, Scale } from 'lucide-react'
import { useState } from 'react'

import LandAnalysisPanel from '../../../land-map/components/LandAnalysisPanel'
import { LawArticlesList } from '../../../land-map/components/LawArticlesList'
import type { LandAnalysisResult } from '../../../land-map/lib/types'
import { ArtifactChrome } from '../../../shell/artifact-host/ArtifactChrome'
import type { ArtifactProps, ShellApi } from '../../../shell/artifact-types'
import type { LawAnalysis } from '../api/analyze'
import { type Conditions, defaultConditions, describeConditions } from '../lib/conditions'
import { countArticles, countRegulations } from '../lib/summary'
import { useLawAnalysis } from '../model/useLawAnalysis'
import { ConditionsMenu } from './ConditionsMenu'
import { SetbacksTab } from './SetbacksTab'
import { SummaryTab } from './SummaryTab'
import './law.css'

/** 법규·한계: the selected site's regulations from `POST /land/analyze`, by tab. */
export default function LawArtifact({ tab = 'summary', params, shell }: ArtifactProps) {
  const [conditions, setConditions] = useState<Conditions>(defaultConditions)
  const { target, phase, rerun } = useLawAnalysis(params, conditions)
  const analysis = phase.kind === 'ready' ? phase.analysis : null
  const title = target.kind === 'site' ? target.address || `PNU ${target.pnu}` : '법규·한계'
  const subtitle = target.kind === 'site' ? describeConditions(conditions) : null

  return (
    <>
      <ArtifactChrome
        actions={
          <button className="artifact-primary" disabled={target.kind !== 'site' || phase.kind === 'loading'} onClick={rerun} type="button">
            <RotateCcw aria-hidden="true" size={12} /><span>다시 분석</span>
          </button>
        }
        counts={analysis ? { regulations: countRegulations(analysis), articles: countArticles(analysis) } : undefined}
        menu={<ConditionsMenu onChange={setConditions} value={conditions} />}
        title={<><strong title={title}>{title}</strong>{subtitle && <span>{subtitle}</span>}</>}
      />
      <div aria-busy={phase.kind === 'loading'} className="law-artifact" data-tab={tab}>
        {target.kind === 'resolving' && <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 선택한 대지를 확인하는 중</p>}
        {target.kind === 'error' && <p className="law-note" data-kind="error" role="alert">{target.text}</p>}
        {target.kind === 'none' && <Empty shell={shell} />}
        {target.kind === 'site' && (
          <>
            {target.notice && <p className="law-note" data-kind="notice" role="status">{target.notice}</p>}
            {phase.kind === 'loading' && (
              <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 법규를 분석하는 중 — 조례·조문 조회에 수십 초가 걸릴 수 있어요</p>
            )}
            {phase.kind === 'error' && <p className="law-note" data-kind="error" role="alert">{phase.text}</p>}
            {analysis && <Body address={target.address} analysis={analysis} tab={tab} />}
          </>
        )}
      </div>
    </>
  )
}

function Body({ tab, analysis, address }: { tab: string; analysis: LawAnalysis; address: string }) {
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
          <LawArticlesList lawArticles={analysis.law_articles} />
        </section>
      ) : (
        <p className="law-note">
          관련 조문이 없어요
          {analysis.law_articles?.errors?.length ? ` — ${analysis.law_articles.errors.join(' / ')}` : ' — 법 검색이 결과를 돌려주지 않았어요.'}
        </p>
      )
    case 'setbacks':
      return <SetbacksTab analysis={analysis} />
    default:
      return <SummaryTab analysis={analysis} />
  }
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
