import type { FacadePalette } from './facade-palette';

export function createPatternCanvas(palette: FacadePalette): HTMLCanvasElement | null {
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
