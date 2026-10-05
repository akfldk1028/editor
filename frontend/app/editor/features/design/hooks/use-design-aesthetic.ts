import { useState, useCallback } from 'react';
import type { MaasAestheticResult } from '../lib/types';

export function useDesignAesthetic() {
  const [aestheticOverlay, setAestheticOverlay] = useState<{
    url: string;
    status: string;
    provider: string;
    style: string;
    textureUrl: string | null;
    texturePanelUrls: Record<string, string>;
    texturedGltfUrl: string | null;
  } | null>(null);
  const [aestheticFacadeStyle, setAestheticFacadeStyle] = useState<string | null>(null);
  const textureProbe = (process.env.NODE_ENV === 'development') && new URLSearchParams(window.location.search).get('textureProbe') === 'reference';

  const handleAestheticGenerated = useCallback((result: MaasAestheticResult | null, style = '') => {
    const requestedStyle = style.trim();
    if (!result) {
      setAestheticOverlay(null);
      setAestheticFacadeStyle(null);
      return;
    }
    const assets = result.provider_result?.assets || [];
    const generated = assets.find(asset => asset.role === 'generated_facade_image' && asset.url)?.url
      || assets.find(asset => asset.url)?.url;
    const bakeStatus = (result.provider_result?.metadata?.texture_bake as { status?: string } | undefined)?.status;
    const projectionSkipped = bakeStatus === 'skipped'
      || result.provider_result?.issues?.some(issue => issue.code === 'projection_panels_not_texture_ready');
    setAestheticFacadeStyle(projectionSkipped ? null : (requestedStyle || null));
    const texturedGltfUrl = projectionSkipped
      ? null
      : assets.find(asset => asset.role === 'textured_gltf' && asset.url)?.url || null;
    const texturePanelUrls = projectionSkipped ? {} : assets
      .filter(asset => asset.role === 'facade_panel_image' && asset.url && asset.metadata?.view)
      .reduce<Record<string, string>>((acc, asset) => {
        const view = String(asset.metadata?.view || '');
        if (view) acc[view] = asset.url!;
        return acc;
      }, {});
    const reference = result.reference?.url;
    const url = generated || reference;
    const textureUrl = projectionSkipped ? null : generated || (textureProbe ? reference : null);
    if (!url) {
      setAestheticOverlay(null);
      return;
    }
    setAestheticOverlay({
      url,
      provider: result.provider_result?.provider || result.job.provider,
      status: `${result.provider_result?.provider || result.job.provider} · ${result.status}${projectionSkipped ? ' / mesh skipped' : ''}`,
      style: projectionSkipped ? '' : style,
      textureUrl: textureUrl || null,
      texturePanelUrls,
      texturedGltfUrl,
    });
  }, [textureProbe]);

  return { aestheticOverlay, setAestheticOverlay, aestheticFacadeStyle, setAestheticFacadeStyle, handleAestheticGenerated };
}
