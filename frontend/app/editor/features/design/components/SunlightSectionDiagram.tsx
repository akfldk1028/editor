/**
 * SunlightSectionDiagram — 정북일조 사선제한 2D 단면도 (SVG).
 *
 * 법규 §86① (2023.9.12 개정):
 *   - 인접대지경계선에서 1.5m 이격
 *   - H ≤ 10m까지 수직 직각
 *   - H > 10m는 H/2 만큼 추가 이격 (slope 2:1)
 *
 * 이 컴포넌트는 법규 단면을 그대로 2D로 표현 (docs/img_5.png 스타일).
 * 지도 렌더와 독립적이므로 좌표/카메라 이슈 없음 — 법규 이해용 reference.
 */

import React from 'react';

export interface SunlightSectionDiagramProps {
  /** 건물 목표 높이 (m). 없으면 18m 표시. */
  targetHeightM?: number | null;
  /** zone 적용 여부 (정북일조 적용 필요 zone인가). false면 "미적용" 표시. */
  applies?: boolean;
  /** 작은 props 크기 조정용 (기본 width 520) */
  width?: number;
  height?: number;
}

const PX_PER_M = 10;  // 1m = 10px
const BASE_SETBACK = 1.5;
const BASE_HEIGHT = 10;
const SLOPE = 2;        // H = slope × x
const MARGIN = { top: 30, right: 40, bottom: 50, left: 60 };

export function SunlightSectionDiagram({
  targetHeightM,
  applies = true,
  width = 520,
  height = 340,
}: SunlightSectionDiagramProps) {
  const H = targetHeightM ?? 18;  // 기본 18m 예시

  // 좌표계: x=0은 인접경계, +x는 남쪽(대지 내부)
  // 화면 기준: 경계 x_screen = MARGIN.left + 20 (왼쪽 여백 확보)
  const innerW = width - MARGIN.left - MARGIN.right;
  const innerH = height - MARGIN.top - MARGIN.bottom;
  const xScale = (m: number) => MARGIN.left + (m + 2) * PX_PER_M;  // -2m ~ 40m range
  const yScale = (m: number) => height - MARGIN.bottom - m * PX_PER_M;

  // Envelope profile 4 points:
  // P1 (x=1.5, H=0)   — 수직벽 바닥
  // P2 (x=1.5, H=10)  — 수직벽 꼭대기
  // P3 (x=5,   H=10)  — 평탄 끝
  // P4 (x=H/2, H=H)   — slope 꼭대기 (H > 10)
  const x1 = BASE_SETBACK;
  const x2 = x1;
  const x3 = BASE_HEIGHT / SLOPE * 2 + BASE_SETBACK - 6.5; // adjusted to 5m by spec
  // spec 기준: H=10m 평탄 끝이 5m 지점이므로:
  const plateauEnd = 5;
  const x4 = H <= BASE_HEIGHT ? BASE_SETBACK : H / SLOPE + BASE_SETBACK - 3.5; // H/2 이격 + base_setback 보정
  // 간단히: H > 10이면 x4 = H / SLOPE (경계에서 H/2 이격)
  const xSlope = H > BASE_HEIGHT ? H / SLOPE : plateauEnd;

  // 건물 박스: 경계에서 1.5m 이격, 폭 25m (그림 공간에 맞게)
  const bldgLeft = Math.max(BASE_SETBACK, xSlope);
  const bldgRight = bldgLeft + 25;
  const bldgTop = H;

  // 경계선(노랑): x=0 세로선
  const borderX = xScale(0);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{
        background: '#0f172a',
        borderRadius: 12,
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      {/* 제목 */}
      <text x={width / 2} y={20} fill="#f1f5f9" fontSize={13} textAnchor="middle" fontWeight={600}>
        정북일조 사선제한 단면 (§86①, 2023.9.12 개정)
      </text>

      {/* Ground line */}
      <line
        x1={MARGIN.left}
        y1={yScale(0)}
        x2={width - MARGIN.right}
        y2={yScale(0)}
        stroke="#64748b"
        strokeWidth={2}
      />

      {/* 인접대지 경계선 (노랑 수직선, 점선) */}
      <line
        x1={borderX}
        y1={yScale(0)}
        x2={borderX}
        y2={yScale(H + 5)}
        stroke="#eab308"
        strokeWidth={2}
        strokeDasharray="4 4"
      />
      <text x={borderX - 5} y={MARGIN.top + 15} fill="#eab308" fontSize={10} textAnchor="end">
        인접대지 경계선
      </text>

      {/* 1.5m 이격 annotation (수평 양방향 화살) */}
      <line
        x1={borderX}
        y1={yScale(-0.5)}
        x2={xScale(BASE_SETBACK)}
        y2={yScale(-0.5)}
        stroke="#f87171"
        strokeWidth={1.5}
      />
      <text
        x={(borderX + xScale(BASE_SETBACK)) / 2}
        y={yScale(-1.2)}
        fill="#f87171"
        fontSize={10}
        textAnchor="middle"
      >
        1.5m 이격
      </text>

      {/* 법규 envelope profile (빨강 점선, 꺾이는 선) */}
      {applies && (
        <>
          <polyline
            points={[
              `${xScale(BASE_SETBACK)},${yScale(0)}`,
              `${xScale(BASE_SETBACK)},${yScale(BASE_HEIGHT)}`,
              `${xScale(xSlope)},${yScale(Math.min(H, H))}`,
              // 확장: 필지 끝까지 slope 계속
              `${xScale(xSlope + 5)},${yScale(H + 10)}`,
            ].join(' ')}
            fill="none"
            stroke="#dc2626"
            strokeWidth={2.5}
            strokeDasharray="6 4"
          />
          {/* 직각 annotation */}
          <text
            x={xScale(BASE_SETBACK) + 5}
            y={yScale(BASE_HEIGHT / 2)}
            fill="#f87171"
            fontSize={10}
          >
            H ≤ 10m: 직각
          </text>
          {/* Slope annotation */}
          {H > BASE_HEIGHT && (
            <text
              x={xScale(xSlope) + 5}
              y={yScale((BASE_HEIGHT + H) / 2)}
              fill="#f87171"
              fontSize={10}
            >
              H &gt; 10m: slope 2:1 (H = 2x)
            </text>
          )}
        </>
      )}

      {/* 건물 박스 (분홍 배경, 경사 없는 박스 단순 표시) */}
      <rect
        x={xScale(bldgLeft)}
        y={yScale(H)}
        width={(bldgRight - bldgLeft) * PX_PER_M}
        height={H * PX_PER_M}
        fill="#f472b6"
        fillOpacity={0.28}
        stroke="#ec4899"
        strokeWidth={1.5}
      />
      <text
        x={(xScale(bldgLeft) + xScale(bldgRight)) / 2}
        y={yScale(H / 2)}
        fill="#fecdd3"
        fontSize={11}
        textAnchor="middle"
      >
        건물 (H = {H}m)
      </text>

      {/* Y-axis 눈금 (0, 10, 20, 30) */}
      {[0, 10, 20, 30].filter((h) => h <= H + 10).map((h) => (
        <g key={h}>
          <line
            x1={MARGIN.left - 5}
            y1={yScale(h)}
            x2={MARGIN.left}
            y2={yScale(h)}
            stroke="#94a3b8"
            strokeWidth={1}
          />
          <text
            x={MARGIN.left - 8}
            y={yScale(h) + 4}
            fill="#94a3b8"
            fontSize={10}
            textAnchor="end"
          >
            {h}m
          </text>
        </g>
      ))}

      {/* X-axis 눈금 */}
      {[0, 1.5, 5, 10, 15, 20].filter((x) => xScale(x) <= width - MARGIN.right).map((x) => (
        <g key={x}>
          <line
            x1={xScale(x)}
            y1={yScale(0)}
            x2={xScale(x)}
            y2={yScale(0) + 5}
            stroke="#94a3b8"
            strokeWidth={1}
          />
          <text
            x={xScale(x)}
            y={yScale(0) + 18}
            fill="#94a3b8"
            fontSize={9}
            textAnchor="middle"
          >
            {x}m
          </text>
        </g>
      ))}

      {/* 범례 */}
      <g transform={`translate(${width - MARGIN.right - 140}, ${MARGIN.top + 10})`}>
        <rect width={140} height={55} fill="#1e293b" opacity={0.85} rx={4} />
        <line x1={8} y1={14} x2={28} y2={14} stroke="#dc2626" strokeWidth={2.5} strokeDasharray="6 4" />
        <text x={32} y={18} fill="#f1f5f9" fontSize={10}>법규 envelope</text>
        <line x1={8} y1={30} x2={28} y2={30} stroke="#eab308" strokeWidth={2} strokeDasharray="4 4" />
        <text x={32} y={34} fill="#f1f5f9" fontSize={10}>인접대지 경계</text>
        <rect x={8} y={43} width={20} height={8} fill="#f472b6" fillOpacity={0.5} stroke="#ec4899" />
        <text x={32} y={50} fill="#f1f5f9" fontSize={10}>건물 단면</text>
      </g>

      {/* 미적용 용도지역 — "미적용" badge */}
      {!applies && (
        <g transform={`translate(${width / 2 - 60}, ${height / 2 - 15})`}>
          <rect width={120} height={30} fill="#475569" rx={4} />
          <text x={60} y={20} fill="#e2e8f0" fontSize={13} textAnchor="middle">
            정북일조 미적용
          </text>
        </g>
      )}
    </svg>
  );
}
