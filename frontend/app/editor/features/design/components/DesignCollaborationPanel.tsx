import React, { useState } from 'react';

export function DesignCollaborationPanel({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
      <div
        data-testid="design-ai-collaboration-panel"
        data-collapsed={collapsed ? 'true' : 'false'}
        style={{
        width: collapsed ? 52 : 520,
        height: 'calc(100vh - 56px)',
        flexShrink: 0,
        borderLeft: '1px solid #1e293b',
        background: '#0f172a',
        overflowY: 'auto',
        padding: collapsed ? 8 : 12,
        boxSizing: 'border-box',
        transition: 'width 180ms ease',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: collapsed ? 'center' : 'space-between',
          alignItems: 'center',
          gap: 8,
          padding: '4px 2px 10px',
        }}>
          {!collapsed && (
            <div>
              <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 700 }}>
                AI 설계 협업
              </div>
              <div style={{ color: '#64748b', fontSize: 10, marginTop: 3, letterSpacing: '0.03em' }}>
                MAAS Agent Workspace
              </div>
            </div>
          )}
          <button
            type="button"
            data-testid="design-ai-collaboration-toggle"
            onClick={() => setCollapsed((collapsed) => !collapsed)}
            title={collapsed ? 'AI 협업 패널 펼치기' : 'AI 협업 패널 접기'}
            aria-label={collapsed ? 'AI 협업 패널 펼치기' : 'AI 협업 패널 접기'}
            style={{
              width: 30,
              height: 30,
              borderRadius: 7,
              border: '1px solid rgba(148,163,184,0.18)',
              background: 'rgba(2,6,23,0.72)',
              color: '#cbd5e1',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 800,
            }}
          >
            {collapsed ? '<' : '>'}
          </button>
        </div>
        {collapsed ? (
          <div style={{
            writingMode: 'vertical-rl',
            transform: 'rotate(180deg)',
            color: '#93c5fd',
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: '0.08em',
            margin: '12px auto 0',
            whiteSpace: 'nowrap',
          }}>
            AI 협업
          </div>
        ) : children}
      </div>
  );
}
