import type { ExecutedMassRecord } from '../../lib/language-system-types';

export function executedMassNodeId(mass: ExecutedMassRecord): string {
  return `executed:mass:${mass.run_id}:${mass.index}:${mass.geometry_hash.slice(0, 12)}`;
}

export function evidenceImageUrl(evidence: Record<string, unknown>): string {
  const keys = ['preview_url', 'image_url', 'asset_url', 'local_url'];
  for (const key of keys) {
    const value = evidence[key];
    if (typeof value === 'string' && /^(https?:|data:|\/)/.test(value)) return value;
  }
  return '';
}

export function massLabel(label: string): string {
  return label.replace(/^MASS \d+\s*[·•-]\s*/, '');
}
