/**
 * Land API client — Editor-owned land API
 *
 * 타입은 types.ts 에서 정의. 여기는 fetch 로직만.
 */

import type {
  LandAnalysisResult,
  PnuResolveResult,
  ReverseGeocodeResult,
} from './types';

/** POST /land/analyze/ — 토지 규제 분석 */
export async function analyze(
  input: string,
  inputType: 'pnu' | 'address' = 'address',
  zones?: string[],
  geometry?: object | null,
  signal?: AbortSignal,
): Promise<LandAnalysisResult> {
  const body: Record<string, unknown> = { input, input_type: inputType };
  if (zones) body.zones = zones;
  if (geometry) body.geometry = geometry;

  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(`분석 실패: ${res.status}`);
  return res.json();
}

/** POST /land/resolve/ — 주소 → PNU */
export async function resolve(
  input: string,
  inputType: 'address' | 'pnu' = 'address',
): Promise<PnuResolveResult> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input, input_type: inputType }),
  });
  if (!res.ok) throw new Error(`PNU 변환 실패: ${res.status}`);
  return res.json();
}

/** GET /land/zones/ — 21개 용도지역 목록 */
export async function getZones(): Promise<unknown[]> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/zones`);
  if (!res.ok) throw new Error(`용도지역 조회 실패: ${res.status}`);
  return res.json();
}

/** POST /land/reverse/ — 좌표 → PNU + 필지 geometry */
export async function reverse(x: number, y: number, signal?: AbortSignal): Promise<ReverseGeocodeResult> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/reverse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, y }),
    signal,
  });
  if (!res.ok) throw new Error(`요청 실패: ${res.status}`);
  return res.json();
}


export type { LandAnalysisResult, PnuResolveResult, ReverseGeocodeResult };
