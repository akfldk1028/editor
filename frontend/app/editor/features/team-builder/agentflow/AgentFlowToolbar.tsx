/**
 * AgentFlowToolbar - Controls for the React Flow graph
 * Ported from AutoGen Studio toolbar.tsx (converted from antd to Tailwind)
 */

import {
  ArrowDown,
  ArrowRight,
  Grid,
  Hash,
  Map as MapIcon,
  Maximize2,
  MessageSquare,
  MessageSquareOff,
  Minimize2,
  MoreHorizontal,
  RotateCcw,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export interface FlowSettings {
  direction: 'TB' | 'LR'
  showLabels: boolean
  showGrid: boolean
  showMiniMap: boolean
  showTokens: boolean
}

export const DEFAULT_SETTINGS: FlowSettings = {
  direction: 'TB',
  showLabels: true,
  showGrid: false,
  showMiniMap: false,
  showTokens: false,
}

interface Props {
  isFullscreen: boolean
  onToggleFullscreen: () => void
  onResetView?: () => void
  settings: FlowSettings
  onSettingsChange: (settings: FlowSettings) => void
}

export function AgentFlowToolbar({
  isFullscreen,
  onToggleFullscreen,
  onResetView,
  settings,
  onSettingsChange,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && e.target instanceof Node && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const toggle = (key: keyof FlowSettings) => {
    onSettingsChange({ ...settings, [key]: !settings[key] })
  }

  const iconBtn =
    'p-1.5 rounded hover:bg-(--color-background-secondary) text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors'

  return (
    <div className="absolute top-2 right-2 bg-(--color-background-primary)/80 backdrop-blur-sm rounded-lg border border-(--color-border-default) z-50">
      <div className="p-1 flex items-center gap-0.5">
        <button
          className={iconBtn}
          onClick={onToggleFullscreen}
          title={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'}
          aria-label={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'}
        >
          {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>

        <button
          className={iconBtn}
          onClick={() =>
            onSettingsChange({ ...settings, direction: settings.direction === 'TB' ? 'LR' : 'TB' })
          }
          title={`Switch to ${settings.direction === 'TB' ? 'Horizontal' : 'Vertical'} Layout`}
          aria-label={`Switch to ${settings.direction === 'TB' ? 'Horizontal' : 'Vertical'} Layout`}
        >
          {settings.direction === 'TB' ? <ArrowDown size={16} /> : <ArrowRight size={16} />}
        </button>

        <button
          className={iconBtn}
          onClick={() => toggle('showLabels')}
          title={settings.showLabels ? 'Hide Labels' : 'Show Labels'}
          aria-label={settings.showLabels ? 'Hide Labels' : 'Show Labels'}
        >
          {settings.showLabels ? <MessageSquare size={16} /> : <MessageSquareOff size={16} />}
        </button>

        <div className="relative" ref={menuRef}>
          <button
            className={iconBtn}
            onClick={() => setMenuOpen(!menuOpen)}
            title="More Options"
            aria-label="More Options"
            aria-expanded={menuOpen}
          >
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full mt-1 w-40 bg-(--color-background-primary) border border-(--color-border-default) rounded-lg shadow-lg py-1"
            >
              <MenuItem
                icon={<Grid size={14} />}
                label="Show Grid"
                active={settings.showGrid}
                onClick={() => toggle('showGrid')}
              />
              <MenuItem
                icon={<Hash size={14} />}
                label="Show Tokens"
                active={settings.showTokens}
                onClick={() => toggle('showTokens')}
              />
              <MenuItem
                icon={<MapIcon size={14} />}
                label="Mini Map"
                active={settings.showMiniMap}
                onClick={() => toggle('showMiniMap')}
              />
              <div className="border-t border-(--color-border-default) my-1" />
              <button
                className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-(--color-background-secondary) text-(--color-text-primary)"
                onClick={() => {
                  onResetView?.()
                  setMenuOpen(false)
                }}
              >
                <RotateCcw size={14} />
                Reset View
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MenuItem({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      role="menuitemcheckbox"
      aria-checked={active}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-(--color-background-secondary) text-(--color-text-primary)"
      onClick={onClick}
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {active && <span className="w-1.5 h-1.5 rounded-full bg-(--color-accent-primary)" />}
    </button>
  )
}
