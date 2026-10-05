/**
 * glassInputHandlers — 글래스모피즘 input focus/blur 스타일 핸들러.
 *
 * HeroSearch + BottomInput 공용. 포커스 시 밝아지고 그림자 추가,
 * 블러 시 원래 상태로 복원.
 */

import type React from 'react';

export const glassInputHandlers = {
  onFocus: (e: React.FocusEvent<HTMLInputElement>) => {
    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.15)';
    e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
    e.currentTarget.style.boxShadow = '0 0 0 1px rgba(255,255,255,0.08), 0 8px 40px rgba(0,0,0,0.2)';
  },
  onBlur: (e: React.FocusEvent<HTMLInputElement>) => {
    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
    e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
    e.currentTarget.style.boxShadow = 'none';
  },
};
