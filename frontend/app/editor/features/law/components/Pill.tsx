/**
 * Pill — 상태 표시/토글용 둥근 배지 컴포넌트.
 *
 * 사용처: LawChat 헤더 (연결 상태, 실시간 토글, 중단, 초기화)
 * 스타일: inline hex (Tailwind CSS 변수 충돌 회피)
 */

import React from 'react';

interface PillProps {
  children: React.ReactNode;
  /** 활성 상태 여부 */
  active: boolean;
  /** 활성 시 텍스트/아이콘 색상 (hex) */
  activeColor: string;
  /** 활성 시 배경 색상 (rgba) */
  activeBg: string;
  /** 비활성 시 텍스트 색상 */
  inactiveColor?: string;
  /** 비활성 시 배경 색상 */
  inactiveBg?: string;
  /** 클릭 핸들러 */
  onClick?: () => void;
  /** 클릭 가능 여부 (cursor 변경) */
  clickable?: boolean;
}

export function Pill({
  children,
  active,
  activeColor,
  activeBg,
  inactiveColor,
  inactiveBg,
  onClick,
  clickable,
}: PillProps) {
  return (
    <div
      onClick={onClick}
      onKeyDown={clickable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick?.(); } } : undefined}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '4px 10px',
        borderRadius: 999,
        background: active ? activeBg : (inactiveBg || 'rgba(255,255,255,0.06)'),
        color: active ? activeColor : (inactiveColor || '#64748b'),
        fontSize: 10,
        fontWeight: 600,
        cursor: clickable ? 'pointer' : 'default',
        transition: 'all 0.15s',
        userSelect: 'none' as const,
      }}
    >
      {children}
    </div>
  );
}
