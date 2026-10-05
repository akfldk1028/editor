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
import { isPnu } from './constants';

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
  signal?: AbortSignal,
): Promise<PnuResolveResult> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input, input_type: inputType }),
    signal,
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

export async function locateParcel(input: string, signal?: AbortSignal): Promise<{
  geometry: object; coordinates?: { x: number; y: number };
}> {
  const value = input.trim();
  let pnu: string | undefined = isPnu(value) ? value : undefined;
  let coordinates: { x: number; y: number } | undefined;
  if (!pnu) {
    const location = await resolve(value, 'address', signal);
    if (!location.success) throw new Error(location.error || '주소 위치를 찾지 못했습니다.');
    coordinates = location.coordinates;
    pnu = location.pnu || undefined;
    if (!pnu && coordinates) {
      const parcel = await reverse(coordinates.x, coordinates.y, signal);
      if (!parcel.success || !parcel.geometry) throw new Error(parcel.error || '필지 경계를 찾지 못했습니다.');
      return { geometry: parcel.geometry, coordinates };
    }
  }
  if (!pnu) throw new Error('필지 번호를 찾지 못했습니다.');
  const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/parcel-geometry`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pnu }), signal,
  });
  if (!response.ok) throw new Error(`필지 경계 조회 실패: ${response.status}`);
  const parcel = await response.json();
  if (!parcel.success || !parcel.geometry || typeof parcel.geometry !== 'object') throw new Error(parcel.error || '필지 경계를 찾지 못했습니다.');
  return { geometry: parcel.geometry, coordinates };
}


export type { LandAnalysisResult, PnuResolveResult, ReverseGeocodeResult };
