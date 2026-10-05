import React, { useState, useEffect, useCallback } from 'react';
import type { Constraint } from '../lib/types';

interface BuildingTypeOption {
  key: string;
  label: string;
  floorHeight: number;
}

interface AlgorithmOption {
  key: string;
  label: string;
}

interface Props {
  constraints: Constraint[];
  siteArea: number | null;
  zones?: string[];
  loading: boolean;
  onPnuSearch: (pnu: string) => void;
  onStart: (options: { maxGenerations: number; populationSize: number }) => void;
  onCancel: () => void;
  status: string;
  /** External PNU value (auto-filled from map click) */
  pnuValue?: string;
  /** Building use type options */
  buildingTypes?: BuildingTypeOption[];
  /** Currently selected building type key */
  buildingType?: string;
  /** Callback when building type changes */
  onBuildingTypeChange?: (key: string) => void;
  /** Mass generation algorithms */
  algorithms?: AlgorithmOption[];
  /** Currently selected algorithm key */
  algorithm?: string;
  /** Callback when algorithm changes */
  onAlgorithmChange?: (key: string) => void;
}

const ControlPanel: React.FC<Props> = React.memo(({
  constraints, siteArea, zones, loading, onPnuSearch, onStart, onCancel, status, pnuValue,
  buildingTypes, buildingType, onBuildingTypeChange,
  algorithms, algorithm, onAlgorithmChange,
}) => {
  const [pnu, setPnu] = useState('');

  useEffect(() => {
    if (pnuValue) setPnu(pnuValue);
  }, [pnuValue]);

  const [maxGens, setMaxGens] = useState(50);
  const [popSize, setPopSize] = useState(30);

  const isRunning = status === 'running' || status === 'connecting';
  const buildingTypeSelectRef = useCallback((node: HTMLSelectElement | null) => {
    if (!node) return;
    const notify = () => onBuildingTypeChange?.(node.value);
    node.oninput = notify;
    node.onchange = notify;
  }, [onBuildingTypeChange]);

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '8px 12px',
    background: '#0c1322',
    border: '1px solid #1e293b',
    borderRadius: 6,
    color: '#e2e8f0',
    fontSize: 13,
    outline: 'none',
    transition: 'border-color 0.2s',
  };

  const labelStyle: React.CSSProperties = {
    color: '#64748b',
    fontSize: 10,
    fontWeight: 600,
    marginBottom: 4,
    display: 'block',
    letterSpacing: '0.05em',
  };

  return (
    <div style={{
      background: '#111827',
      borderRadius: 10,
      padding: 14,
      marginBottom: 10,
      border: '1px solid #1e293b',
    }}>
      {/* PNU input */}
      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>PNU / ADDRESS</label>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            style={inputStyle}
            placeholder="PNU 코드 (19자리) 또는 주소"
            value={pnu}
            onChange={e => setPnu(e.target.value)}
            disabled={isRunning}
            onFocus={e => { e.target.style.borderColor = '#3b82f6'; }}
            onBlur={e => { e.target.style.borderColor = '#1e293b'; }}
          />
          <button
            onClick={() => onPnuSearch(pnu)}
            disabled={!pnu || loading || isRunning}
            style={{
              padding: '8px 14px',
              background: loading ? '#1e293b' : '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: loading ? 'wait' : 'pointer',
              fontSize: 12,
              fontWeight: 600,
              whiteSpace: 'nowrap' as const,
              opacity: !pnu || loading || isRunning ? 0.5 : 1,
              transition: 'all 0.2s',
            }}
          >
            {loading ? '...' : '조회'}
          </button>
        </div>
      </div>

      {/* Site info */}
      {siteArea && (
        <div style={{
          padding: '8px 12px',
          background: 'rgba(34,197,94,0.06)',
          borderRadius: 6,
          marginBottom: 10,
          fontSize: 12,
          color: '#94a3b8',
          border: '1px solid rgba(34,197,94,0.1)',
          display: 'flex',
          justifyContent: 'space-between',
        }}>
          <span>대지면적</span>
          <span style={{ color: '#4ade80', fontWeight: 700, fontFamily: 'monospace' }}>
            {siteArea.toLocaleString()} m{'\u00B2'}
          </span>
        </div>
      )}

      {/* Zone info */}
      {zones && zones.length > 0 && (
        <div style={{
          padding: '8px 12px',
          background: 'rgba(129,140,248,0.06)',
          borderRadius: 6,
          marginBottom: 10,
          fontSize: 12,
          color: '#94a3b8',
          border: '1px solid rgba(129,140,248,0.1)',
        }}>
          <div style={{ marginBottom: 4, color: '#64748b', fontSize: 10, fontWeight: 600, letterSpacing: '0.05em' }}>
            용도지역
          </div>
          {zones.map((z, i) => (
            <div key={i} style={{ color: '#818cf8', fontWeight: 600 }}>{z}</div>
          ))}
        </div>
      )}

      {/* Building type selector */}
      {buildingTypes && buildingTypes.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <label style={labelStyle}>BUILDING USE TYPE</label>
          <select
            ref={buildingTypeSelectRef}
            style={{
              ...inputStyle,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              appearance: 'none' as const,
              backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%2364748b\' d=\'M2 4l4 4 4-4\'/%3E%3C/svg%3E")',
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 10px center',
              paddingRight: 28,
            }}
            value={buildingType || '공동주택'}
            onInput={e => onBuildingTypeChange?.((e.target as HTMLSelectElement).value)}
            onChange={e => onBuildingTypeChange?.(e.target.value)}
            disabled={isRunning}
          >
            {buildingTypes.map(bt => (
              <option key={bt.key} value={bt.key}>
                {bt.label} ({bt.floorHeight}m/층)
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Algorithm selector */}
      {algorithms && algorithms.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <label style={labelStyle}>MASS SEARCH MODE</label>
          <select
            style={{
              ...inputStyle,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              appearance: 'none' as const,
              backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%2364748b\' d=\'M2 4l4 4 4-4\'/%3E%3C/svg%3E")',
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 10px center',
              paddingRight: 28,
            }}
            value={algorithm || 'additive'}
            onChange={e => onAlgorithmChange?.(e.target.value)}
            disabled={isRunning}
          >
            {algorithms.map(a => (
              <option key={a.key} value={a.key}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* GA options */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>GENERATIONS</label>
          <input
            type="number"
            style={inputStyle}
            value={maxGens}
            onChange={e => setMaxGens(Number(e.target.value))}
            min={5}
            max={200}
            disabled={isRunning}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>POPULATION</label>
          <input
            type="number"
            style={inputStyle}
            value={popSize}
            onChange={e => setPopSize(Number(e.target.value))}
            min={10}
            max={100}
            disabled={isRunning}
          />
        </div>
      </div>

      {/* Start/Cancel button */}
      {isRunning ? (
        <button
          onClick={onCancel}
          style={{
            width: '100%',
            padding: '10px',
            background: 'rgba(220,38,38,0.15)',
            color: '#f87171',
            border: '1px solid rgba(220,38,38,0.3)',
            borderRadius: 8,
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 700,
            transition: 'all 0.2s',
            letterSpacing: '0.03em',
          }}
        >
          CANCEL
        </button>
      ) : (
        <button
          onClick={() => onStart({ maxGenerations: maxGens, populationSize: popSize })}
          disabled={!siteArea || constraints.length === 0 || loading}
          style={{
            width: '100%',
            padding: '10px',
            background: !siteArea || constraints.length === 0
              ? '#1e293b'
              : 'linear-gradient(135deg, #059669, #22c55e)',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: !siteArea || constraints.length === 0 ? 'not-allowed' : 'pointer',
            fontSize: 13,
            fontWeight: 700,
            opacity: !siteArea || constraints.length === 0 ? 0.4 : 1,
            transition: 'all 0.2s',
            letterSpacing: '0.03em',
          }}
        >
          OPTIMIZE
        </button>
      )}
    </div>
  );
});

ControlPanel.displayName = 'ControlPanel';
export default ControlPanel;
