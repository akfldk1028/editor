/**
 * 우측 분석 패널 — Premium AI dashboard style
 * BCR/FAR + core/extended 규제 + 토지 정보 + 법조항
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';
import { COLOR, STYLE, CORE_REGULATIONS, hexA } from '../lib/constants';
import type { LandAnalysisResult, RegulationItem, PnuInfo, OverlayRegulation, LawArticleItem } from '../lib/types';
import { RegulationCard } from './RegulationCard';
import { BigStat } from './BigStat';
import { LandInfoSummary } from './LandInfoSummary';
import { DatumInfoCard } from './DatumInfoCard';
import { LawArticlesList } from './LawArticlesList';

interface LandAnalysisPanelProps {
  analysis: LandAnalysisResult;
  address?: string | null;
  onSelectArticle?: (article: LawArticleItem) => void;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function extractValue(item: RegulationItem, keys: string[]): string | number | null {
  for (const k of keys) {
    const v = (item as Record<string, unknown>)[k];
    if (v != null) return v as string | number;
  }
  return null;
}

function extractDescription(item: RegulationItem, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = (item as Record<string, unknown>)[k];
    if (Array.isArray(v) && v.length) {
      // 배열 원소가 객체면 문자열로 변환 (일조사선 rules 등)
      return v.map(el =>
        typeof el === 'object' && el !== null
          ? (el as Record<string, unknown>).rule || (el as Record<string, unknown>).description || JSON.stringify(el)
          : String(el)
      ).join(' / ');
    }
    if (typeof v === 'string' && v) return v;
  }
  if (item.applies === false) return '미적용';
  if (item.applies === true) return '적용';
  return undefined;
}

function getPnuString(pnu: LandAnalysisResult['pnu']): string {
  if (!pnu) return '';
  if (typeof pnu === 'string') return pnu;
  return (pnu as PnuInfo).pnu || '';
}

function formatOverlayValue(ov: OverlayRegulation): string | null {
  const v = ov.values;
  if (v.min_height_m != null && v.max_height_m != null) return `${v.min_height_m}~${v.max_height_m}m`;
  if (v.max_height_m != null) return `최고 ${v.max_height_m}m`;
  if (v.min_height_m != null) return `최저 ${v.min_height_m}m`;
  return null;
}

// ---------------------------------------------------------------------------
// Animation
// ---------------------------------------------------------------------------

const EASE: [number, number, number, number] = [0.25, 0.46, 0.45, 0.94];

const fadeSlide = {
  hidden: { opacity: 0, y: 14 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.06, duration: 0.4, ease: EASE },
  }),
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Divider() {
  return (
    <div style={{
      height: 1, margin: '4px 0',
      background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.05) 30%, rgba(255,255,255,0.05) 70%, transparent)',
    }} />
  );
}

function SectionLabel({ label, count, color = COLOR.textMuted }: {
  label: string;
  count: number;
  color?: string;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <span style={{
        fontSize: 10, fontWeight: 700, color, letterSpacing: '0.1em',
        textTransform: 'uppercase' as const,
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 9, fontWeight: 700, color,
        padding: '2px 6px', borderRadius: 4,
        background: hexA(color, 0x12),
        border: `1px solid ${hexA(color, 0x20)}`,
      }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: hexA(color, 0x15) }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default React.memo(function LandAnalysisPanel({ analysis, address, onSelectArticle }: LandAnalysisPanelProps) {
  const [extendedOpen, setExtendedOpen] = useState(false);
  const [overlayOpen, setOverlayOpen] = useState(true);

  const reg = analysis.regulations;
  const zone = analysis.zone_info;
  const pnuStr = getPnuString(analysis.pnu);

  const coreCount = Object.keys(CORE_REGULATIONS).filter(k => reg?.[k]).length;
  const extCount = reg?.extended ? Object.keys(reg.extended).length : 0;
  const overlayCount = analysis.overlay_regulations?.length || 0;
  const lawCount = analysis.law_articles?.total_count || analysis.law_articles?.articles?.length || 0;
  const totalRegs = coreCount + extCount + overlayCount;

  let idx = 0;

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      style={{ display: 'flex', flexDirection: 'column', gap: 14 }}
    >
      {/* ── Status chip ── */}
      <motion.div custom={idx++} variants={fadeSlide}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '4px 12px', borderRadius: 20,
          background: 'rgba(52,211,153,0.06)',
          border: '1px solid rgba(52,211,153,0.15)',
        }}>
          <div style={{
            width: 6, height: 6, borderRadius: '50%',
            background: COLOR.emerald,
            boxShadow: '0 0 8px rgba(52,211,153,0.4)',
          }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: COLOR.emerald, letterSpacing: '0.02em' }}>
            {analysis.errors?.length ? '일부 결과 — 확인 필요' : '분석 결과'}
          </span>
          <span style={{
            fontSize: 10, color: COLOR.textMuted,
            borderLeft: '1px solid rgba(255,255,255,0.06)',
            paddingLeft: 8,
          }}>
            {totalRegs}개 규제 · {lawCount}개 법조항
          </span>
        </div>
      </motion.div>

      {analysis.errors?.map((error, index) => <p key={index} role="alert" style={{ color: COLOR.red, fontSize: 12 }}>{error}</p>)}
      {analysis.warning && <p role="status" style={{ color: COLOR.amber, fontSize: 12 }}>{analysis.warning}</p>}
      {/* ── Header: 주소 + PNU + 용도지역 뱃지 ── */}
      <motion.div custom={idx++} variants={fadeSlide}>
        {address && (
          <p style={{ margin: 0, fontSize: 17, fontWeight: 700, color: COLOR.text, marginBottom: 4, letterSpacing: '-0.01em' }}>
            {address}
          </p>
        )}
        {pnuStr && (
          <p style={{ margin: 0, fontSize: 11, color: COLOR.textDim, fontFamily: STYLE.monoFont }}>
            PNU {pnuStr}
          </p>
        )}
        {zone?.zones && zone.zones.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
            {zone.zones.map((z) => (
              <span key={z} style={{
                fontSize: 11, fontWeight: 600, color: COLOR.textSecondary,
                padding: '3px 10px', borderRadius: 6,
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.08)',
              }}>
                {z}
              </span>
            ))}
          </div>
        )}
      </motion.div>

      {/* ── BCR / FAR ── */}
      <motion.div custom={idx++} variants={fadeSlide} style={{ display: 'flex', gap: 10 }}>
        <BigStat label="건폐율" value={reg?.bcr?.limit_pct} unit="%" color={COLOR.cyan} />
        <BigStat label="용적률" value={reg?.far?.limit_pct} unit="%" color={COLOR.emerald} />
      </motion.div>

      <Divider />

      {/* ── Core regulations ── */}
      <motion.div custom={idx++} variants={fadeSlide} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        <SectionLabel label="핵심 규제" count={coreCount} />
        {Object.entries(CORE_REGULATIONS).map(([key, meta]) => {
          const item = reg?.[key] as RegulationItem | undefined;
          if (!item) return null;
          return (
            <RegulationCard
              key={key}
              name={meta.name}
              value={extractValue(item, meta.valueKeys)}
              unit={meta.unit}
              article={item.article || ''}
              description={extractDescription(item, meta.descKeys)}
              accent={meta.accent}
            />
          );
        })}
      </motion.div>

      {/* ── Extended regulations ── */}
      {extCount > 0 && (
        <>
          <Divider />
          <motion.div custom={idx++} variants={fadeSlide}>
            <button
              onClick={() => setExtendedOpen(prev => !prev)}
              aria-expanded={extendedOpen}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, width: '100%',
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '4px 0',
              }}
            >
              <ChevronDown style={{
                width: 12, height: 12, color: COLOR.textMuted,
                transition: 'transform 0.2s',
                transform: extendedOpen ? 'rotate(180deg)' : 'rotate(0)',
              }} />
              <span style={{ fontSize: 10, fontWeight: 700, color: COLOR.textMuted, letterSpacing: '0.1em', textTransform: 'uppercase' as const }}>
                확장 규제
              </span>
              <span style={{
                fontSize: 9, fontWeight: 700, color: COLOR.textMuted,
                padding: '2px 6px', borderRadius: 4,
                background: 'rgba(255,255,255,0.04)',
              }}>
                {extCount}
              </span>
            </button>
            <AnimatePresence>
              {extendedOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.25, ease: 'easeInOut' }}
                  style={{ overflow: 'hidden' }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5, paddingTop: 6 }}>
                    {Object.entries(reg?.extended ?? {}).map(([key, ext]) => (
                      <RegulationCard
                        key={key}
                        name={ext.name || key.replace(/_/g, ' ')}
                        value={ext.value ?? ext.limit ?? null}
                        unit={ext.unit}
                        article={ext.article || ''}
                        description={ext.description || ext.rule || (ext.applies === false ? '미적용' : ext.applies ? '적용' : undefined)}
                      />
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </>
      )}

      {/* ── Overlay regulations ── */}
      {overlayCount > 0 && (
        <>
          <Divider />
          <motion.div custom={idx++} variants={fadeSlide}>
            <button
              onClick={() => setOverlayOpen(prev => !prev)}
              aria-expanded={overlayOpen}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, width: '100%',
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '4px 0',
              }}
            >
              <ChevronDown style={{
                width: 12, height: 12, color: COLOR.amber,
                transition: 'transform 0.2s',
                transform: overlayOpen ? 'rotate(180deg)' : 'rotate(0)',
              }} />
              <span style={{ fontSize: 10, fontWeight: 700, color: COLOR.amber, letterSpacing: '0.1em', textTransform: 'uppercase' as const }}>
                지역·지구 규제
              </span>
              <span style={{
                fontSize: 9, fontWeight: 700, color: COLOR.amber,
                padding: '2px 6px', borderRadius: 4,
                background: 'rgba(245,158,11,0.08)',
              }}>
                {overlayCount}
              </span>
            </button>
            <AnimatePresence>
              {overlayOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.25, ease: 'easeInOut' }}
                  style={{ overflow: 'hidden' }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5, paddingTop: 6 }}>
                    {(analysis.overlay_regulations ?? []).map((ov) => (
                      <RegulationCard
                        key={ov.raw_zone}
                        name={ov.name}
                        value={formatOverlayValue(ov)}
                        article={ov.article}
                        description={ov.description}
                        accent={COLOR.amber}
                      />
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </>
      )}

      <Divider />

      {/* ── Land info ── */}
      <motion.div custom={idx++} variants={fadeSlide}>
        <LandInfoSummary landInfo={analysis.land_info} />
      </motion.div>

      {/* ── 지반 레벨 (§119 datum) ── */}
      <motion.div custom={idx++} variants={fadeSlide}>
        <DatumInfoCard
          envelope={analysis.setback_lines?.sunlight_envelope}
          datumResult={analysis.setback_lines?.datum_result}
        />
      </motion.div>

      {/* ── Law articles ── */}
      <motion.div custom={idx++} variants={fadeSlide}>
        <LawArticlesList lawArticles={analysis.law_articles} onSelectArticle={onSelectArticle} />
      </motion.div>

      {/* ── Restrictions summary ── */}
      {analysis.restrictions && analysis.restrictions.length > 0 && (
        <>
          <Divider />
          <motion.div custom={idx++} variants={fadeSlide} style={{
            borderRadius: 12,
            background: 'rgba(245,158,11,0.03)',
            border: '1px solid rgba(245,158,11,0.08)',
            padding: '14px 16px',
            position: 'relative',
            overflow: 'hidden',
          }}>
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 1,
              background: 'linear-gradient(90deg, transparent, rgba(245,158,11,0.3), transparent)',
            }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <div style={{
                width: 5, height: 5, borderRadius: '50%',
                background: COLOR.amber,
                boxShadow: '0 0 6px rgba(245,158,11,0.4)',
              }} />
              <span style={{
                fontSize: 10, fontWeight: 700, color: COLOR.amber,
                letterSpacing: '0.1em', textTransform: 'uppercase' as const,
              }}>
                요약
              </span>
            </div>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {analysis.restrictions.map((r, i) => (
                <li key={i} style={{ fontSize: 12, color: COLOR.textSecondary, lineHeight: 1.8 }}>{r}</li>
              ))}
            </ul>
          </motion.div>
        </>
      )}
    </motion.div>
  );
})
