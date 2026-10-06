export type FacadePalette = {
  base: string;
  edge: string;
  floor: string;
  alpha: number;
  label: string;
};

export function facadePaletteFromStyle(style?: string | null): FacadePalette | null {
  const text = (style || '').toLowerCase();
  if (!text.trim()) return null;
  if (/(glass|curtain|유리|커튼월)/i.test(text)) {
    return { base: '#6fb6d6', edge: '#dbeafe', floor: '#1e3a8a', alpha: 0.58, label: 'glass' };
  }
  if (/(concrete|cement|콘크리트|노출|시멘트)/i.test(text)) {
    return { base: '#b8b5ad', edge: '#f3f4f6', floor: '#525252', alpha: 0.72, label: 'concrete' };
  }
  if (/(brick|terracotta|벽돌|전돌|테라코타)/i.test(text)) {
    return { base: '#b45f43', edge: '#fed7aa', floor: '#5f241a', alpha: 0.74, label: 'brick' };
  }
  if (/(stone|limestone|granite|석재|라임스톤|화강석)/i.test(text)) {
    return { base: '#9ca3af', edge: '#f8fafc', floor: '#374151', alpha: 0.72, label: 'stone' };
  }
  if (/(wood|timber|목재|우드)/i.test(text)) {
    return { base: '#9a6a3a', edge: '#fde68a', floor: '#451a03', alpha: 0.72, label: 'wood' };
  }
  if (/(white|stucco|plaster|백색|흰색|스터코|미장)/i.test(text)) {
    return { base: '#e7e5df', edge: '#ffffff', floor: '#78716c', alpha: 0.74, label: 'plaster' };
  }
  return { base: '#b45f43', edge: '#fed7aa', floor: '#5f241a', alpha: 0.74, label: 'brick' };
}
