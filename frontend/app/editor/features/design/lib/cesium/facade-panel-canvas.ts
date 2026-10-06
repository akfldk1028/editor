import type { FacadePalette } from './facade-palette';

/* eslint-disable @typescript-eslint/no-explicit-any */

export type AtlasView = 'front' | 'right' | 'back' | 'left';

const ATLAS_PANEL_BOXES: Record<AtlasView, [number, number, number, number]> = {
  front: [19, 19, 486, 739],
  right: [524, 19, 486, 739],
  back: [1029, 19, 486, 739],
  left: [19, 777, 486, 739],
};

const atlasCanvasCache = new Map<string, HTMLCanvasElement>();
const designedCanvasCache = new Map<string, HTMLCanvasElement>();

export function createAtlasPanelCanvas(
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

export function createDesignedFacadeCanvas(
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
