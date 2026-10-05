import { requiredValue } from '../required-value';
/* eslint-disable @typescript-eslint/no-explicit-any */

export type FacadePalette = {
  base: string;
  edge: string;
  floor: string;
  alpha: number;
  label: string;
};

export type RenderFacadeWallParams = {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  ring: number[][];
  groundH: number;
  bottom: number;
  top: number;
  designId: number;
  segmentKey: string;
  style?: string | null;
  textureUrl?: string | null;
  texturePanelUrls?: Record<string, string> | null;
  floorH: number;
  textureTotalHeight?: number;
};

type AtlasView = 'front' | 'right' | 'back' | 'left';

const ATLAS_PANEL_BOXES: Record<AtlasView, [number, number, number, number]> = {
  front: [19, 19, 486, 739],
  right: [524, 19, 486, 739],
  back: [1029, 19, 486, 739],
  left: [19, 777, 486, 739],
};

const atlasCanvasCache = new Map<string, HTMLCanvasElement>();
const designedCanvasCache = new Map<string, HTMLCanvasElement>();

function normalizedOpenRing(ring: number[][]): number[][] {
  if (ring.length < 2) return ring;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first && last && Math.abs(requiredValue(first[0]) - requiredValue(last[0])) < 1e-10 && Math.abs(requiredValue(first[1]) - requiredValue(last[1])) < 1e-10) {
    return ring.slice(0, -1);
  }
  return ring;
}

function facadeViewForEdge(a: number[], b: number[], ring: number[][]): AtlasView {
  const xs = ring.map(p => requiredValue(p[0]));
  const ys = ring.map(p => requiredValue(p[1]));
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const mx = (requiredValue(a[0]) + requiredValue(b[0])) / 2;
  const my = (requiredValue(a[1]) + requiredValue(b[1])) / 2;
  const dx = mx - cx;
  const dy = my - cy;
  if (Math.abs(dx) > Math.abs(dy)) return dx >= 0 ? 'right' : 'left';
  return dy >= 0 ? 'back' : 'front';
}

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

function createPatternCanvas(palette: FacadePalette): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.fillStyle = palette.base;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (palette.label === 'brick') {
    const facadeGradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    facadeGradient.addColorStop(0, '#a85a3e');
    facadeGradient.addColorStop(0.55, '#8f4834');
    facadeGradient.addColorStop(1, '#6e3529');
    ctx.fillStyle = facadeGradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const brickH = 22;
    const brickW = 58;
    for (let y = 0; y <= canvas.height; y += brickH) {
      const offset = (Math.floor(y / brickH) % 2) * (brickW / 2);
      for (let x = -offset; x <= canvas.width; x += brickW) {
        const shade = ((Math.floor((x + 512) / brickW) * 19 + Math.floor(y / brickH) * 13) % 44) - 22;
        const r = Math.max(74, Math.min(176, 142 + shade));
        const g = Math.max(38, Math.min(100, 72 + Math.round(shade * 0.45)));
        const b = Math.max(28, Math.min(82, 50 + Math.round(shade * 0.25)));
        ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
        ctx.fillRect(x + 2, y + 2, brickW - 4, brickH - 4);
        ctx.fillStyle = 'rgba(255,255,255,0.075)';
        ctx.fillRect(x + 5, y + 4, brickW - 10, 2);
        ctx.fillStyle = 'rgba(0,0,0,0.08)';
        ctx.fillRect(x + 3, y + brickH - 5, brickW - 6, 2);
      }
    }
    ctx.strokeStyle = 'rgba(232, 211, 190, 0.62)';
    ctx.lineWidth = 2;
    for (let y = 0; y <= canvas.height; y += brickH) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
      const offset = (Math.floor(y / brickH) % 2) * (brickW / 2);
      for (let x = -offset; x <= canvas.width; x += brickW) {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + brickH);
        ctx.stroke();
      }
    }

    const drawWindow = (x: number, y: number, w: number, h: number, balcony: boolean) => {
      ctx.fillStyle = 'rgba(28, 18, 14, 0.46)';
      ctx.fillRect(x - 7, y - 6, w + 14, h + 13);
      ctx.fillStyle = 'rgba(112, 54, 37, 0.82)';
      ctx.fillRect(x - 4, y - 4, w + 8, h + 8);
      const glass = ctx.createLinearGradient(x, y, x + w, y + h);
      glass.addColorStop(0, 'rgba(225, 238, 240, 0.94)');
      glass.addColorStop(0.45, 'rgba(125, 151, 157, 0.82)');
      glass.addColorStop(1, 'rgba(38, 52, 59, 0.92)');
      ctx.fillStyle = glass;
      ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = 'rgba(23, 25, 27, 0.86)';
      ctx.lineWidth = 3;
      ctx.strokeRect(x, y, w, h);
      ctx.beginPath();
      ctx.moveTo(x + w / 2, y);
      ctx.lineTo(x + w / 2, y + h);
      ctx.stroke();
      ctx.strokeStyle = 'rgba(255,255,255,0.28)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x + 5, y + 5);
      ctx.lineTo(x + w - 8, y + 5);
      ctx.stroke();
      if (balcony) {
        const by = y + h + 8;
        ctx.fillStyle = 'rgba(56, 34, 26, 0.72)';
        ctx.fillRect(x - 9, by, w + 18, 8);
        ctx.strokeStyle = 'rgba(225, 222, 212, 0.78)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x - 8, by - 11);
        ctx.lineTo(x + w + 8, by - 11);
        ctx.stroke();
        for (let rx = x - 4; rx <= x + w + 4; rx += 9) {
          ctx.beginPath();
          ctx.moveTo(rx, by - 10);
          ctx.lineTo(rx, by + 4);
          ctx.stroke();
        }
      }
    };

    for (let y = 34; y < canvas.height; y += 116) {
      drawWindow(52, y, 46, 50, true);
      drawWindow(148, y + 6, 42, 44, false);
      drawWindow(242, y, 48, 50, true);
      drawWindow(344, y + 4, 42, 46, false);
      drawWindow(438, y, 46, 50, true);
    }

    ctx.fillStyle = 'rgba(54, 32, 24, 0.58)';
    for (let y = 102; y < canvas.height; y += 116) {
      ctx.fillRect(0, y, canvas.width, 7);
    }
    ctx.fillStyle = 'rgba(255,255,255,0.07)';
    for (let x = 0; x < canvas.width; x += 4) {
      const alpha = (x % 19 === 0) ? 0.08 : 0.025;
      ctx.fillStyle = `rgba(255,255,255,${alpha})`;
      ctx.fillRect(x, 0, 1, canvas.height);
    }
    const shade = ctx.createLinearGradient(0, 0, canvas.width, 0);
    shade.addColorStop(0, 'rgba(0,0,0,0.24)');
    shade.addColorStop(0.18, 'rgba(0,0,0,0)');
    shade.addColorStop(0.82, 'rgba(0,0,0,0)');
    shade.addColorStop(1, 'rgba(0,0,0,0.28)');
    ctx.fillStyle = shade;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  } else if (palette.label === 'glass') {
    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, 'rgba(219, 234, 254, 0.95)');
    gradient.addColorStop(0.45, 'rgba(96, 165, 250, 0.72)');
    gradient.addColorStop(1, 'rgba(15, 23, 42, 0.58)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = 'rgba(248, 250, 252, 0.80)';
    ctx.lineWidth = 3;
    for (let x = 0; x <= canvas.width; x += 64) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
    }
  } else {
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.34)';
    ctx.lineWidth = 2;
    for (let y = 0; y <= canvas.height; y += 42) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(15, 23, 42, 0.20)';
    for (let x = 0; x <= canvas.width; x += 56) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
    }
  }
  return canvas;
}

function createAtlasPanelCanvas(
  textureUrl: string,
  view: AtlasView,
  viewer: any,
  verticalRange?: { bottom: number; top: number; total: number },
): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  const rangeKey = verticalRange
    ? `${verticalRange.bottom.toFixed(3)}-${verticalRange.top.toFixed(3)}-${verticalRange.total.toFixed(3)}`
    : 'full';
  const key = `${textureUrl}#${view}#${rangeKey}`;
  const cached = atlasCanvasCache.get(key);
  if (cached) return cached;

  const canvas = document.createElement('canvas');
  canvas.width = 768;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.fillStyle = '#8f4834';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  atlasCanvasCache.set(key, canvas);

  const image = new Image();
  image.crossOrigin = 'anonymous';
  image.onload = () => {
    const [sx, sy, sw, sh] = ATLAS_PANEL_BOXES[view];
    const scaleX = image.naturalWidth / 1536;
    const scaleY = image.naturalHeight / 1536;
    let cropY = sy * scaleY;
    let cropH = sh * scaleY;
    if (verticalRange && verticalRange.total > 0) {
      const bottomRatio = Math.max(0, Math.min(1, verticalRange.bottom / verticalRange.total));
      const topRatio = Math.max(bottomRatio, Math.min(1, verticalRange.top / verticalRange.total));
      cropY = (sy + (1 - topRatio) * sh) * scaleY;
      cropH = Math.max(1, (topRatio - bottomRatio) * sh * scaleY);
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(
      image,
      sx * scaleX,
      cropY,
      sw * scaleX,
      cropH,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    try {
      viewer.scene?.requestRender?.();
    } catch { /* ignore */ }
  };
  image.onerror = () => {
    atlasCanvasCache.delete(key);
  };
  image.src = textureUrl;
  return canvas;
}

function createDesignedFacadeCanvas(
  palette: FacadePalette,
  floorCount: number,
  view: AtlasView,
  sourceUrl?: string | null,
  viewer?: any,
): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  const key = `${palette.label}#${floorCount}#${view}#${sourceUrl || 'procedural'}`;
  const cached = designedCanvasCache.get(key);
  if (cached) return cached;

  const canvas = document.createElement('canvas');
  canvas.width = 768;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  designedCanvasCache.set(key, canvas);

  const bg = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  if (palette.label === 'glass') {
    bg.addColorStop(0, '#d8e7ed');
    bg.addColorStop(0.48, '#8fa8b1');
    bg.addColorStop(1, '#2f3f47');
  } else if (palette.label === 'stone' || palette.label === 'plaster') {
    bg.addColorStop(0, '#f2eee6');
    bg.addColorStop(0.55, '#d8d1c3');
    bg.addColorStop(1, '#b8afa1');
  } else {
    bg.addColorStop(0, '#b96d51');
    bg.addColorStop(0.52, '#9b5b43');
    bg.addColorStop(1, '#744231');
  }
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Fine material grain without making the facade read as a repeated photo.
  if (palette.label === 'brick') {
    ctx.strokeStyle = 'rgba(244, 224, 204, 0.16)';
    ctx.lineWidth = 1;
    for (let y = 0; y < canvas.height; y += 18) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(61, 34, 26, 0.10)';
    for (let x = 0; x < canvas.width; x += 72) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
    }
  } else {
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
    for (let y = 0; y < canvas.height; y += 92) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
    }
  }

  const floors = Math.max(2, Math.min(10, floorCount));
  const marginX = view === 'front' || view === 'back' ? 76 : 122;
  const baseH = Math.round(canvas.height * 0.22);
  const parapetH = 58;
  const bodyTop = parapetH;
  const bodyBottom = canvas.height - baseH;
  const floorH = (bodyBottom - bodyTop) / floors;
  const cols = view === 'front' || view === 'back' ? 3 : 2;
  const bayGap = view === 'front' || view === 'back' ? 42 : 34;
  const bayW = (canvas.width - marginX * 2 - bayGap * (cols - 1)) / cols;

  ctx.fillStyle = 'rgba(229, 219, 201, 0.98)';
  ctx.fillRect(0, canvas.height - baseH, canvas.width, baseH);
  const baseGrad = ctx.createLinearGradient(0, bodyBottom, canvas.width, canvas.height);
  baseGrad.addColorStop(0, '#f0e8d7');
  baseGrad.addColorStop(0.55, '#d8c9aa');
  baseGrad.addColorStop(1, '#bba886');
  ctx.fillStyle = baseGrad;
  ctx.fillRect(0, bodyBottom, canvas.width, baseH);
  ctx.fillStyle = 'rgba(34, 28, 24, 0.42)';
  ctx.fillRect(0, bodyBottom - 12, canvas.width, 12);
  ctx.fillStyle = 'rgba(238, 232, 220, 0.88)';
  ctx.fillRect(0, 0, canvas.width, parapetH);
  ctx.fillStyle = 'rgba(46, 31, 25, 0.42)';
  ctx.fillRect(0, parapetH - 9, canvas.width, 9);

  const drawWindow = (x: number, y: number, w: number, h: number, balcony: boolean, accent = false) => {
    ctx.fillStyle = 'rgba(24, 18, 16, 0.42)';
    ctx.fillRect(x - 15, y - 12, w + 30, h + 25);
    ctx.fillStyle = accent
      ? 'rgba(80, 58, 46, 0.82)'
      : palette.label === 'brick' ? 'rgba(226, 215, 198, 0.90)' : 'rgba(142, 133, 121, 0.68)';
    ctx.fillRect(x - 8, y - 6, w + 16, h + 12);
    const glass = ctx.createLinearGradient(x, y, x + w, y + h);
    glass.addColorStop(0, '#eef7f8');
    glass.addColorStop(0.36, '#9cb3bb');
    glass.addColorStop(0.72, '#536870');
    glass.addColorStop(1, '#1f2a2f');
    ctx.fillStyle = glass;
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = 'rgba(28, 28, 27, 0.90)';
    ctx.lineWidth = 4;
    ctx.strokeRect(x, y, w, h);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x + w * 0.5, y);
    ctx.lineTo(x + w * 0.5, y + h);
    ctx.stroke();
    if (balcony) {
      const by = y + h + 12;
      ctx.fillStyle = 'rgba(43, 35, 30, 0.78)';
      ctx.fillRect(x - 20, by, w + 40, 9);
      ctx.fillStyle = 'rgba(70, 62, 56, 0.18)';
      ctx.fillRect(x - 20, by - 22, w + 40, 24);
      ctx.strokeStyle = 'rgba(244, 241, 232, 0.70)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x - 12, by - 15);
      ctx.lineTo(x + w + 12, by - 15);
      ctx.stroke();
      for (let rx = x - 8; rx <= x + w + 8; rx += 13) {
        ctx.beginPath();
        ctx.moveTo(rx, by - 14);
        ctx.lineTo(rx, by + 5);
        ctx.stroke();
      }
    }
  };

  const drawVerticalFin = (x: number, w: number, alpha = 0.36) => {
    const fin = ctx.createLinearGradient(x, bodyTop, x + w, bodyBottom);
    fin.addColorStop(0, `rgba(244, 232, 212, ${alpha})`);
    fin.addColorStop(0.55, `rgba(94, 55, 40, ${alpha * 0.7})`);
    fin.addColorStop(1, `rgba(41, 27, 22, ${alpha})`);
    ctx.fillStyle = fin;
    ctx.fillRect(x, bodyTop, w, bodyBottom - bodyTop);
  };
  for (let col = 0; col <= cols; col++) {
    const x = marginX - 23 + col * (bayW + bayGap);
    drawVerticalFin(x, 20, col === 0 || col === cols ? 0.42 : 0.28);
  }
  if (view === 'front' || view === 'back') {
    drawVerticalFin(canvas.width - marginX + 14, 28, 0.34);
  }

  for (let floor = 0; floor < floors; floor++) {
    const y = bodyBottom - (floor + 1) * floorH + 16;
    const h = Math.max(78, floorH - 38);
    ctx.fillStyle = 'rgba(255,255,255,0.055)';
    ctx.fillRect(0, Math.round(bodyBottom - floor * floorH), canvas.width, 2);
    for (let col = 0; col < cols; col++) {
      const x = marginX + col * (bayW + bayGap);
      const stagger = (floor + col) % 4 === 0 ? 8 : 0;
      const balcony = palette.label !== 'glass' && view !== 'back' && floor > 0 && ((floor + col) % 2 === 0);
      const isWide = (view === 'front' || view === 'back') && col === 1;
      const windowW = bayW * (isWide ? 0.86 : 0.68);
      const offsetX = isWide ? bayW * 0.06 : bayW * 0.16;
      drawWindow(x + offsetX, y + stagger, windowW, h - stagger, balcony, col === 1);
    }
  }

  ctx.fillStyle = 'rgba(35, 30, 27, 0.90)';
  ctx.fillRect(marginX - 10, canvas.height - baseH + 42, bayW * 1.25, baseH - 70);
  ctx.fillStyle = 'rgba(210, 188, 156, 0.96)';
  ctx.fillRect(marginX - 28, canvas.height - baseH + 28, bayW * 1.25 + 56, 15);
  const lobbyGlass = ctx.createLinearGradient(canvas.width - marginX - bayW * 1.42, bodyBottom + 44, canvas.width - marginX, canvas.height - 38);
  lobbyGlass.addColorStop(0, 'rgba(239, 248, 247, 0.86)');
  lobbyGlass.addColorStop(1, 'rgba(56, 67, 70, 0.74)');
  ctx.fillStyle = lobbyGlass;
  ctx.fillRect(canvas.width - marginX - bayW * 1.42, canvas.height - baseH + 44, bayW * 1.42, baseH - 78);
  ctx.strokeStyle = 'rgba(68, 56, 46, 0.36)';
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.moveTo(0, canvas.height - 16);
  ctx.lineTo(canvas.width, canvas.height - 16);
  ctx.stroke();

  const sideShade = ctx.createLinearGradient(0, 0, canvas.width, 0);
  sideShade.addColorStop(0, 'rgba(0,0,0,0.22)');
  sideShade.addColorStop(0.14, 'rgba(0,0,0,0)');
  sideShade.addColorStop(0.86, 'rgba(0,0,0,0)');
  sideShade.addColorStop(1, 'rgba(0,0,0,0.24)');
  ctx.fillStyle = sideShade;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (sourceUrl) {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => {
      ctx.save();
      ctx.globalAlpha = 0.22;
      ctx.globalCompositeOperation = 'multiply';
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      ctx.restore();
      try {
        viewer?.scene?.requestRender?.();
      } catch { /* ignore */ }
    };
    image.onerror = () => {
      designedCanvasCache.delete(key);
    };
    image.src = sourceUrl;
  }
  return canvas;
}

function createFacadeMaterial(
  Cesium: any,
  palette: FacadePalette,
  floorCount: number,
  textureUrl: string | null | undefined,
  texturePanelUrl: string | null | undefined,
  atlasView: AtlasView,
  viewer: any,
  verticalRange?: { bottom: number; top: number; total: number },
): any {
  if ((textureUrl || texturePanelUrl) && Cesium.ImageMaterialProperty) {
    const panelCanvas = createDesignedFacadeCanvas(palette, floorCount, atlasView, texturePanelUrl || textureUrl, viewer)
      || (textureUrl ? createAtlasPanelCanvas(textureUrl, atlasView, viewer, verticalRange) : null);
    return new Cesium.ImageMaterialProperty({
      image: panelCanvas || texturePanelUrl || textureUrl,
      repeat: new Cesium.Cartesian2(1, 1),
      color: Cesium.Color.WHITE.withAlpha(1),
      transparent: false,
    });
  }
  const pattern = createPatternCanvas(palette);
  if (!pattern || !Cesium.ImageMaterialProperty) {
    return Cesium.Color.fromCssColorString(palette.base).withAlpha(palette.alpha);
  }
  return new Cesium.ImageMaterialProperty({
    image: pattern,
    repeat: new Cesium.Cartesian2(1.4, Math.max(1, floorCount * 0.5)),
    color: Cesium.Color.WHITE.withAlpha(0.98),
    transparent: true,
  });
}

export function renderFacadeWallEntities({
  viewer,
  Cesium,
  entityPrefix,
  ring,
  groundH,
  bottom,
  top,
  designId,
  segmentKey,
  style,
  textureUrl,
  texturePanelUrls,
  floorH,
  textureTotalHeight,
}: RenderFacadeWallParams) {
  const palette = facadePaletteFromStyle(style);
  if (!palette || top <= bottom) return;
  const open = normalizedOpenRing(ring);
  if (open.length < 3) return;

  const edgeColor = Cesium.Color.fromCssColorString(palette.edge).withAlpha(0.92);
  const floorColor = Cesium.Color.fromCssColorString(palette.floor).withAlpha(textureUrl ? 0.10 : 0.22);
  const minH = groundH + bottom + 0.04;
  const maxH = groundH + top + 0.04;
  const floorCount = Math.max(1, Math.round((top - bottom) / Math.max(1, floorH)));
  const verticalRange = textureUrl && textureTotalHeight
    ? { bottom, top, total: textureTotalHeight }
    : undefined;
  const baseMaterial = createFacadeMaterial(Cesium, palette, floorCount, textureUrl, texturePanelUrls?.front, 'front', viewer, verticalRange);

  for (let edgeIndex = 0; edgeIndex < open.length; edgeIndex++) {
    const a = requiredValue(open[edgeIndex]);
    const b = requiredValue(open[(edgeIndex + 1) % open.length]);
    const atlasView = textureUrl ? facadeViewForEdge(a, b, open) : 'front';
    const texturePanelUrl = texturePanelUrls?.[atlasView] || null;
    const facadeMaterial = textureUrl
      ? createFacadeMaterial(Cesium, palette, floorCount, textureUrl, texturePanelUrl, atlasView, viewer, verticalRange)
      : baseMaterial;
    viewer.entities.add({
      id: `${entityPrefix}facade-${designId}-${segmentKey}-${edgeIndex}`,
      properties: {
        interactionKind: 'facade_material',
        designId,
        facadeMaterial: palette.label,
        facadeAtlasView: atlasView,
        facadePanelUrl: texturePanelUrl,
        target: { kind: 'facade', segment: segmentKey, edge_index: edgeIndex },
      },
      wall: {
        positions: Cesium.Cartesian3.fromDegreesArray([requiredValue(a[0]), requiredValue(a[1]), requiredValue(b[0]), requiredValue(b[1])]),
        minimumHeights: [minH, minH],
        maximumHeights: [maxH, maxH],
        material: facadeMaterial,
        outline: !textureUrl,
        outlineColor: textureUrl ? edgeColor.withAlpha(0.32) : edgeColor.withAlpha(0.54),
      },
    });

    if (textureUrl) continue;
    for (let floor = 1; floor < floorCount; floor++) {
      const h = groundH + bottom + floor * ((top - bottom) / floorCount) + 0.07;
      viewer.entities.add({
        id: `${entityPrefix}facade-floor-${designId}-${segmentKey}-${edgeIndex}-${floor}`,
        polyline: {
          positions: [
            Cesium.Cartesian3.fromDegrees(requiredValue(a[0]), requiredValue(a[1]), h),
            Cesium.Cartesian3.fromDegrees(requiredValue(b[0]), requiredValue(b[1]), h),
          ],
          width: 1.4,
          material: floorColor,
          clampToGround: false,
        },
      });
    }
  }
}
