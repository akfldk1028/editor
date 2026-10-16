'use client'

/** The world's layer panel: base map, layer toggles and what has been loaded. Shared by /world and /design. */

import type { ReactNode } from 'react'
import type { useWorld3D } from '../hooks/use-world-3d'

export function WorldControls({ world, title, children, className, compact }: {
  world: ReturnType<typeof useWorld3D>; title: string; children?: ReactNode; className?: string; compact?: boolean
}) {
  const { base, setBase, show, setShow, terrain, setTerrain, status, error, stats } = world
  return <div className={className ?? 'absolute left-3 top-3 z-10 flex w-80 flex-col gap-2 rounded-md bg-white/90 p-3 text-sm text-neutral-800 shadow'}>
    <div className="font-medium">{title}</div>
    {children}
    {!compact && <div className="flex gap-3">
      <label><input type="radio" checked={base === 'white'} onChange={() => setBase('white')} /> 흰 바탕</label>
      <label><input type="radio" checked={base === 'vworld2d'} onChange={() => setBase('vworld2d')} /> 브이월드 2D 지도</label>
    </div>}
    <div className="flex flex-wrap gap-x-3">
      <label><input type="checkbox" checked={show.buildings} onChange={(e) => setShow((v) => ({ ...v, buildings: e.target.checked }))} /> 건물</label>
      <label><input type="checkbox" checked={show.ground} onChange={(e) => setShow((v) => ({ ...v, ground: e.target.checked }))} /> 필지·도로</label>
      <label><input type="checkbox" checked={show.cover} onChange={(e) => setShow((v) => ({ ...v, cover: e.target.checked }))} /> 대지 안 피복</label>
      <label><input type="checkbox" checked={terrain} onChange={(e) => setTerrain(e.target.checked)} /> 지형</label>
    </div>
    {compact ? <div className="text-neutral-500">건물 {stats.buildings}동{stats.pending ? ` · ${stats.pending}건 불러오는 중` : ''}</div> : <>
    <div className="text-xs text-neutral-500">
      건물 {stats.buildings}동{stats.pending ? ` · ${stats.pending}건 불러오는 중` : ''} — 화면을 움직이면 보이는 곳이 채워집니다
    </div>
    <div className="text-xs text-neutral-500">
      높이: 실측 {stats.counts.measured} · 층수로 추정 {stats.counts.estimated} · 모름 {stats.counts.unknown}(옅게)
    </div></>}
    {(error || status) && <div className="text-xs text-neutral-500">{error || status}</div>}
  </div>
}
