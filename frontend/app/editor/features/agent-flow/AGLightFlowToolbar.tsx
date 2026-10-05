import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Grid,
  Maximize2,
  MessageSquare,
  MessageSquareOff,
  Minimize2,
  MoreHorizontal,
  RotateCcw,
} from 'lucide-react';

export interface AGLightFlowSettings {
  direction: 'TB' | 'LR';
  showLabels: boolean;
  showGrid: boolean;
}

export const DEFAULT_AG_LIGHT_SETTINGS: AGLightFlowSettings = {
  direction: 'LR',
  showLabels: true,
  showGrid: true,
};

interface Props {
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  onResetView: () => void;
  settings: AGLightFlowSettings;
  onSettingsChange: (settings: AGLightFlowSettings) => void;
}

const iconButtonStyle: CSSProperties = {
  width: 26,
  height: 26,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  border: 0,
  borderRadius: 6,
  color: '#cbd5e1',
  background: 'transparent',
  cursor: 'pointer',
};

export default function AGLightFlowToolbar({
  isFullscreen,
  onToggleFullscreen,
  onResetView,
  settings,
  onSettingsChange,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (menuRef.current && event.target instanceof Node && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const update = (patch: Partial<AGLightFlowSettings>) => {
    onSettingsChange({ ...settings, ...patch });
  };

  return (
    <div
      style={{
        position: 'absolute',
        top: 8,
        right: 8,
        zIndex: 30,
        display: 'flex',
        alignItems: 'center',
        gap: 2,
        padding: 4,
        borderRadius: 8,
        border: '1px solid rgba(148,163,184,0.18)',
        background: 'rgba(15,23,42,0.88)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <button
        type="button"
        style={iconButtonStyle}
        onClick={onToggleFullscreen}
        title={isFullscreen ? '전체화면 해제' : '전체화면'}
        aria-label={isFullscreen ? '전체화면 해제' : '전체화면'}
      >
        {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
      </button>
      <button
        type="button"
        style={iconButtonStyle}
        onClick={() => update({ showLabels: !settings.showLabels })}
        title={settings.showLabels ? '라벨 숨김' : '라벨 표시'}
        aria-label={settings.showLabels ? '라벨 숨김' : '라벨 표시'}
      >
        {settings.showLabels ? <MessageSquare size={15} /> : <MessageSquareOff size={15} />}
      </button>
      <div ref={menuRef} style={{ position: 'relative' }}>
        <button
          type="button"
          style={iconButtonStyle}
          onClick={() => setMenuOpen((open) => !open)}
          title="옵션"
          aria-label="옵션"
          aria-expanded={menuOpen}
        >
          <MoreHorizontal size={15} />
        </button>
        {menuOpen && (
          <div
            role="menu"
            style={{
              position: 'absolute',
              top: 30,
              right: 0,
              width: 138,
              padding: 6,
              borderRadius: 8,
              border: '1px solid rgba(148,163,184,0.18)',
              background: 'rgba(2,6,23,0.98)',
              boxShadow: '0 18px 40px rgba(0,0,0,0.28)',
            }}
          >
            <MenuItem
              icon={<Grid size={14} />}
              label="Grid"
              active={settings.showGrid}
              onClick={() => update({ showGrid: !settings.showGrid })}
            />
            <MenuItem
              icon={<RotateCcw size={14} />}
              label="Reset"
              active={false}
              onClick={() => {
                onResetView();
                setMenuOpen(false);
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function MenuItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={active}
      onClick={onClick}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 8px',
        border: 0,
        borderRadius: 6,
        color: '#e2e8f0',
        background: 'transparent',
        cursor: 'pointer',
        fontSize: 12,
      }}
    >
      {icon}
      <span style={{ flex: 1, textAlign: 'left' }}>{label}</span>
      {active && <span style={{ width: 6, height: 6, borderRadius: 999, background: '#2dd4bf' }} />}
    </button>
  );
}
