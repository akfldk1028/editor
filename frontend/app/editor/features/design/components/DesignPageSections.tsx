import type React from 'react';

export function DesignPageHeader() {
  return (
    <div style={{
      padding: '4px 8px 14px',
    }}>
      <h2 style={{
        color: '#e2e8f0',
        fontSize: 17,
        fontWeight: 700,
        margin: 0,
        letterSpacing: '-0.01em',
      }}>
        건물 매스 최적화
      </h2>
      <p style={{ color: '#475569', fontSize: 11, margin: '4px 0 0', letterSpacing: '0.02em' }}>
        MAAS Legal Morphology Search
      </p>
    </div>
  );
}

export function ParetoEmptyState() {
  return (
    <div style={{
      background: 'rgba(30,41,59,0.5)',
      borderRadius: 10,
      padding: 32,
      textAlign: 'center' as const,
      color: '#334155',
      border: '1px dashed #1e293b',
    }}>
      <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>&#x25B3;</div>
      <div style={{ fontSize: 13, lineHeight: 1.6 }}>
        왼쪽 지도에서 대지를 선택하고<br />
        최적화를 시작하면<br />
        파레토 프론트가 표시됩니다
      </div>
    </div>
  );
}

interface DesignViewTabBarProps {
  viewTab: 'mass' | 'floor';
  setViewTab: React.Dispatch<React.SetStateAction<'mass' | 'floor'>>;
  floorAlgorithm: string;
  setFloorAlgorithm: React.Dispatch<React.SetStateAction<string>>;
  autoFloorPlan: boolean;
  setAutoFloorPlan: React.Dispatch<React.SetStateAction<boolean>>;
}

/** Tab bar: 매스 | 평면 + 자동 토글 */
export function DesignViewTabBar({
  viewTab,
  setViewTab,
  floorAlgorithm,
  setFloorAlgorithm,
  autoFloorPlan,
  setAutoFloorPlan,
}: DesignViewTabBarProps) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', padding: '6px 12px 0',
      borderBottom: '1px solid rgba(255,255,255,0.04)',
      flexShrink: 0,
    }}>
      {(['mass', 'floor'] as const).map(tab => (
        <button
          key={tab}
          onClick={() => setViewTab(tab)}
          style={{
            flex: 1, padding: '7px 0', border: 'none', cursor: 'pointer',
            fontSize: 11, fontWeight: 600, letterSpacing: '0.05em',
            background: 'transparent',
            color: viewTab === tab ? '#e2e8f0' : '#475569',
            borderBottom: viewTab === tab ? '2px solid #60c8ff' : '2px solid transparent',
            transition: 'all 0.15s',
          }}
        >
          {tab === 'mass' ? '매스' : '평면'}
        </button>
      ))}
      <select
        value={floorAlgorithm}
        onChange={e => setFloorAlgorithm(e.target.value)}
        style={{
          marginLeft: 6, padding: '2px 4px', borderRadius: 4,
          border: '1px solid #334155', background: '#0f172a',
          color: '#94a3b8', fontSize: 9, cursor: 'pointer',
          flexShrink: 0,
        }}
      >
        <option value="ga">GA</option>
        <option value="subdivision">분할</option>
        <option value="mcts">MCTS</option>
        <option value="packing">패킹</option>
        <option value="graph2plan">Graph2Plan</option>
      </select>
      <button
        onClick={() => setAutoFloorPlan(prev => !prev)}
        title={autoFloorPlan ? '자동 평면 생성 켜짐' : '자동 평면 생성 꺼짐'}
        style={{
          marginLeft: 4, padding: '3px 8px', borderRadius: 6,
          border: 'none', cursor: 'pointer', fontSize: 9, fontWeight: 600,
          background: autoFloorPlan ? 'rgba(96,200,255,0.12)' : 'rgba(255,255,255,0.03)',
          color: autoFloorPlan ? '#60c8ff' : '#475569',
          transition: 'all 0.15s', whiteSpace: 'nowrap',
          flexShrink: 0,
        }}
      >
        자동 {autoFloorPlan ? 'ON' : 'OFF'}
      </button>
    </div>
  );
}

interface ParetoVisibilityToggleProps {
  showAllPareto: boolean;
  setShowAllPareto: React.Dispatch<React.SetStateAction<boolean>>;
  paretoFrontCount: number;
  visibleParetoCount: number;
}

export function ParetoVisibilityToggle({
  showAllPareto,
  setShowAllPareto,
  paretoFrontCount,
  visibleParetoCount,
}: ParetoVisibilityToggleProps) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '7px 12px 0',
      color: '#64748b',
      fontSize: 10,
      flexShrink: 0,
    }}>
      <span>
        {showAllPareto ? `전체 ${paretoFrontCount}개 표시` : `최적 후보 ${visibleParetoCount}개 우선 표시`}
      </span>
      <button
        onClick={() => setShowAllPareto(prev => !prev)}
        style={{
          border: '1px solid rgba(96,200,255,0.22)',
          background: showAllPareto ? 'rgba(96,200,255,0.08)' : 'rgba(16,185,129,0.12)',
          color: showAllPareto ? '#60c8ff' : '#34d399',
          borderRadius: 6,
          padding: '3px 7px',
          fontSize: 10,
          cursor: 'pointer',
        }}
      >
        {showAllPareto ? '최적만' : '전체보기'}
      </button>
    </div>
  );
}
