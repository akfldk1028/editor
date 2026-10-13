import { AlertTriangle, Check, Plus, X } from 'lucide-react'

import type { ShellApi } from '../../../shell/artifact-types'
import { lotLabel } from '../lib/layers/parcelOutline'
import type { SavedSite, SiteBundle } from '../lib/picks'
import { SiteRunPanel } from './SiteRunPanel'

export type CardState =
  | { kind: 'loading'; count: number }
  | { kind: 'error'; text: string }
  | { kind: 'ready'; site: SiteBundle; save: 'idle' | 'saving' | 'failed' }
  /** Saved: the record (with its selection id) the Orchestrator run is made from. */
  | { kind: 'ready'; site: SavedSite; save: 'saved' }

const area = (value: number | null) =>
  value === null ? '—' : `${value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} ㎡`

interface Props {
  state: CardState
  /** Whether a tap adds to the bundle (touch has no Shift). */
  adding: boolean
  onAddingChange(adding: boolean): void
  onRemove(pnu: string): void
  onSelect(): void
  onClose(): void
  /** The shell's `?project=`; the saved site's 검토 시작 submits under this binding when it is one. */
  project?: string
  /** The run panel opens the system artifact through it when the Orchestrator is down. */
  shell: ShellApi
}

/** The picked site: its parcels, total area, warnings, and the button that makes it the project's site. */
export function SiteCard({ state, adding, onAddingChange, onRemove, onSelect, onClose, project, shell }: Props) {
  return (
    <section aria-label="선택한 대지" className="site-card">
      <button aria-label="닫기 (Esc)" className="site-card-icon site-card-close" onClick={onClose} title="닫기 (Esc)" type="button"><X size={14} /></button>
      {state.kind === 'loading' && <p className="site-card-note">{state.count > 1 ? `필지 ${state.count}개 정보를 불러오는 중` : '필지 정보를 불러오는 중'}</p>}
      {state.kind === 'error' && <p className="site-card-note" data-kind="error">{state.text}</p>}
      {state.kind === 'ready' && <Ready {...{ state, adding, onAddingChange, onRemove, onSelect, project, shell }} />}
    </section>
  )
}

function Ready({ state, adding, onAddingChange, onRemove, onSelect, project, shell }: Omit<Props, 'onClose' | 'state'> & { state: Extract<CardState, { kind: 'ready' }> }) {
  const { site, save } = state
  const count = site.parcels.length
  const editable = save !== 'saved' && save !== 'saving'
  return (
    <>
      <header>
        <h3>{site.label}</h3>
        <small>필지 {count}개 · 합계 {area(site.total_area_m2)}</small>
      </header>
      <ul className="site-card-parcels">
        {site.parcels.map((parcel) => (
          <li key={parcel.pnu}>
            <div>
              <b>{lotLabel(parcel.address, parcel.pnu)}</b>
              <span>{[parcel.summary.land_category, area(parcel.summary.area_m2)].filter(Boolean).join(' · ')}</span>
              <small>{parcel.summary.zones.length ? parcel.summary.zones.join(' · ') : '용도지역 —'}</small>
            </div>
            {editable && count > 1 && (
              <button aria-label={`${lotLabel(parcel.address, parcel.pnu)} 빼기`} className="site-card-icon" onClick={() => onRemove(parcel.pnu)} title="빼기" type="button"><X size={12} /></button>
            )}
          </li>
        ))}
      </ul>
      {(site.zones.length > 1 || site.contiguous === false || site.zone_notes?.length) && (
        <ul className="site-card-warnings">
          {site.zones.length > 1 && <li><AlertTriangle aria-hidden="true" size={12} />용도지역 {site.zones.length}개 걸침 ({site.zones.join(' · ')})</li>}
          {site.zone_notes?.map((note) => <li key={note}><AlertTriangle aria-hidden="true" size={12} />{note}</li>)}
          {site.contiguous === false && <li><AlertTriangle aria-hidden="true" size={12} />서로 붙어 있지 않아 합필 불가</li>}
        </ul>
      )}
      {editable && (
        <button aria-pressed={adding} className="site-card-toggle" onClick={() => onAddingChange(!adding)} type="button">
          <Plus aria-hidden="true" size={12} />필지 추가 {adding ? '켜짐' : ''}<kbd>Shift+클릭</kbd>
        </button>
      )}
      {state.save === 'saved' ? (
        <>
          <p className="site-card-saved"><Check aria-hidden="true" size={14} />선택됨</p>
          <SiteRunPanel key={state.site.selection_id} project={project} shell={shell} site={state.site} />
        </>
      ) : (
        <button className="artifact-primary site-card-select" disabled={save === 'saving'} onClick={onSelect} type="button">
          {save === 'saving' ? '저장 중' : `이 대지로 선택 (필지 ${count}개)`}
        </button>
      )}
      {save === 'failed' && <p className="site-card-note" data-kind="error">저장하지 못했습니다. 다시 시도해 주세요.</p>}
    </>
  )
}
