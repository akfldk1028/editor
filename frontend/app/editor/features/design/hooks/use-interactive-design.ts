import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  Constraint,
  DesignData,
  GeoJSONFeature,
  InteractivePreviewCandidate,
  InteractivePreviewResult,
  InteractivePatchResult,
  MaasAestheticResult,
  SetbackGeometriesMap,
} from '../lib/types';
import {
  applyInteractiveOperation,
  createInteractivePatch,
  createInteractivePreview,
  createMaasAesthetic,
  createMaasLegalVariants,
} from '../lib/api-client';
import { useInteractiveAgentReview } from './use-interactive-agent-review';

export interface InteractiveDesignProps {
  jobId?: string | null;
  design: DesignData;
  massGeojson: GeoJSONFeature | null;
  constraints: Constraint[];
  sitePolygon: object | null;
  siteArea: number | null;
  pnu?: string | null;
  buildingType: string;
  algorithm: string;
  sunlightEnvelope?: object | null;
  setbackGeometries?: SetbackGeometriesMap | null;
  onPreviewCandidate: (feature: GeoJSONFeature | null) => void;
  onAestheticGenerated?: (result: MaasAestheticResult | null, style?: string) => void;
}

export const formatMetric = (value: number | undefined): string => (
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '-'
);

export function useInteractiveDesign({
  jobId,
  design,
  massGeojson,
  constraints,
  sitePolygon,
  siteArea,
  pnu,
  buildingType,
  algorithm,
  sunlightEnvelope,
  setbackGeometries,
  onPreviewCandidate,
  onAestheticGenerated,
}: InteractiveDesignProps) {
  const agentReview = useInteractiveAgentReview({ jobId, design, massGeojson, setbackGeometries, buildingType, algorithm, onAestheticGenerated, onPreviewCandidate });
  const [message, setMessage] = useState('');
  const [result, setResult] = useState<InteractivePatchResult | null>(null);
  const [preview, setPreview] = useState<InteractivePreviewResult | null>(null);
  const [activePreviewId, setActivePreviewId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [operationLoading, setOperationLoading] = useState(false);
  const [aestheticLoading, setAestheticLoading] = useState(false);
  const [aestheticProvider, setAestheticProvider] = useState<'placeholder' | 'gpt-image' | 'nano-banana'>('placeholder');
  const [aestheticStyle, setAestheticStyle] = useState(
    'premium contemporary Korean residential facade, warm brick and limestone base, deep shadow window reveals, disciplined vertical window rhythm, refined metal balconies, elegant ground floor entrance, realistic architectural competition quality'
  );
  const [aesthetic, setAesthetic] = useState<MaasAestheticResult | null>(null);
  const [error, setError] = useState('');

  const contextKey = JSON.stringify([jobId, design.id, design.uid, design.algorithm, pnu, buildingType, algorithm]);
  const contextRef = useRef(contextKey);
  contextRef.current = contextKey;
  const callbacksRef = useRef({ onPreviewCandidate, onAestheticGenerated });
  callbacksRef.current = { onPreviewCandidate, onAestheticGenerated };
  const requestRef = useRef<AbortController | null>(null);
  const cancelPending = useCallback(() => {
    requestRef.current?.abort();
    requestRef.current = null;
  }, []);
  const clearLoading = useCallback(() => {
    setLoading(false);
    setPreviewLoading(false);
    setOperationLoading(false);
    setAestheticLoading(false);
  }, []);
  const startRequest = () => {
    cancelPending();
    clearLoading();
    const controller = new AbortController();
    requestRef.current = controller;
    const isCurrent = () => requestRef.current === controller && !controller.signal.aborted && contextRef.current === contextKey;
    return { signal: controller.signal, isCurrent, finish: () => {
      if (!isCurrent()) return;
      requestRef.current = null;
      clearLoading();
    } };
  };

  useEffect(() => {
    clearLoading();
    setResult(null);
    setPreview(null);
    setActivePreviewId(null);
    setAesthetic(null);
    callbacksRef.current.onAestheticGenerated?.(null);
    setError('');
    callbacksRef.current.onPreviewCandidate(null);
    return cancelPending;
  }, [contextKey, cancelPending, clearLoading]);

  const submit = async () => {
    const trimmed = message.trim();
    if (!trimmed) return;
    const request = startRequest();
    setLoading(true);
    setError('');
    try {
      const patch = await createInteractivePatch({
        message: trimmed,
        selected_design: design,
        mass_geojson: massGeojson,
        constraints,
      }, request.signal);
      if (!request.isCurrent()) return;
      setResult(patch);
      setPreview(null);
      setActivePreviewId(null);
      onPreviewCandidate(null);
    } catch (e) {
      if (!request.isCurrent()) return;
      setError(e instanceof Error ? e.message : '수정 후보 생성 실패');
    } finally {
      request.finish();
    }
  };

  const buildPreview = async () => {
    if (!result || !sitePolygon || !siteArea) {
      setError('부지 정보가 있어야 수정안 미리보기를 계산할 수 있습니다.');
      return;
    }
    const request = startRequest();
    setPreviewLoading(true);
    setError('');
    try {
      const computed = await createInteractivePreview({
        patch_plan: result,
        selected_design: design,
        site_polygon: sitePolygon,
        site_area_m2: siteArea,
        constraints,
        building_type: buildingType,
        algorithm: design.algorithm || (algorithm === 'all' ? undefined : algorithm),
      }, request.signal);
      if (!request.isCurrent()) return;
      setPreview(computed);
      const first = computed.candidates.find(c => c.mass_geojson)?.mass_geojson || null;
      const firstId = computed.candidates.find(c => c.mass_geojson)?.id || null;
      setActivePreviewId(firstId);
      onPreviewCandidate(first);
    } catch (e) {
      if (!request.isCurrent()) return;
      setError(e instanceof Error ? e.message : '미리보기 계산 실패');
    } finally {
      request.finish();
    }
  };

  const buildMaasVariants = async () => {
    if (!massGeojson || !sitePolygon) {
      setError('선택된 매스와 부지 정보가 있어야 MAAS 후보를 계산할 수 있습니다.');
      return;
    }
    const request = startRequest();
    setPreviewLoading(true);
    setError('');
    try {
      const computed = await createMaasLegalVariants({
        mass_geojson: massGeojson,
        site_polygon: sitePolygon,
        constraints,
        building_type: buildingType,
        max_variants: 6,
        sunlight_envelope: sunlightEnvelope,
        setback_geometries: setbackGeometries,
      }, request.signal);
      if (!request.isCurrent()) return;
      const candidates = computed.feature_collection.features.map((feature, index) => {
        const props = feature.properties;
        const variantId = typeof props.variant_id === 'string' ? props.variant_id : `maas_${index + 1}`;
        const notes = Array.isArray(props.notes) ? props.notes.map(String) : [];
        return {
    ...agentReview,
          id: variantId,
          title: `${variantId} · ${props.mass_shape || 'MAAS variant'}`,
          intent: 'maas_morphology',
          feasible: true,
          penalty: 0,
          inputs: design.inputs,
          outputs: [],
          metrics: {
            far: props.far,
            bcr: props.bcr,
            height: props.height,
            maas_score: typeof props.maas_score === 'number' ? props.maas_score : 0,
          },
          mass_geojson: feature,
          notes,
        };
      });
      const nextPreview = {
        mode: 'preview' as const,
        selected_design_id: design.id,
        algorithm: computed.algorithm,
        building_type: buildingType,
        candidates,
        notes: computed.notes,
      };
      setResult(null);
      setPreview(nextPreview);
      const first = candidates.find(c => c.mass_geojson)?.mass_geojson || null;
      const firstId = candidates.find(c => c.mass_geojson)?.id || null;
      setActivePreviewId(firstId);
      onPreviewCandidate(first);
    } catch (e) {
      if (!request.isCurrent()) return;
      setError(e instanceof Error ? e.message : 'MAAS 후보 계산 실패');
    } finally {
      request.finish();
    }
  };

  const selectPreview = (candidate: InteractivePreviewCandidate) => {
    cancelPending();
    clearLoading();
    setActivePreviewId(candidate.id);
    onPreviewCandidate(candidate.mass_geojson);
  };

  const applyOperation = async (operation: object) => {
    if (!massGeojson || !sitePolygon) {
      setError('조작할 매스와 부지 정보가 필요합니다.');
      return;
    }
    const request = startRequest();
    setOperationLoading(true);
    setError('');
    try {
      const result = await applyInteractiveOperation({
        mass_geojson: massGeojson,
        site_polygon: sitePolygon,
        operation,
        constraints,
        building_type: buildingType,
        sunlight_envelope: sunlightEnvelope,
        setback_geometries: setbackGeometries,
      }, request.signal);
      if (!request.isCurrent()) return;
      const props = result.feature.properties;
	      const agentNotes = (result.agent_reviews || []).map(review => `${review.agent}: ${review.status} · ${review.summary}`);
	      const candidate = {
        id: `op_${Date.now()}`,
        title: `Push/Pull · FAR ${formatMetric(props.far)} / BCR ${formatMetric(props.bcr)}`,
        intent: 'push_pull_operation',
        feasible: true,
        penalty: 0,
        inputs: design.inputs,
        outputs: [],
        metrics: {
          far: props.far,
          bcr: props.bcr,
          height: props.height,
        },
        mass_geojson: result.feature,
	        notes: [...agentNotes, ...result.notes],
	      };
	      setPreview({
	        mode: 'preview',
	        selected_design_id: design.id,
	        algorithm: 'maas_legal_envelope',
	        building_type: buildingType,
	        candidates: [candidate],
	        notes: [...agentNotes, ...result.notes],
	        a2ui_messages: result.a2ui_messages,
	      });
      setActivePreviewId(candidate.id);
      onPreviewCandidate(result.feature);
    } catch (e) {
      if (!request.isCurrent()) return;
      setError(e instanceof Error ? e.message : '매스 조작 실패');
    } finally {
      request.finish();
    }
  };

  const generateAesthetic = async () => {
    if (!jobId) {
      setError('저장된 최적화 job이 있어야 외관 이미지를 생성할 수 있습니다.');
      return;
    }
    if (massGeojson?.properties?.design_id == null) {
      setError('현재 선택 후보의 MAAS 매스 geometry를 찾을 수 없습니다. 다른 후보를 선택한 뒤 다시 시도하세요.');
      return;
    }
    const massDesignId = massGeojson?.properties?.design_id;
    const aestheticDesignId = typeof massDesignId === 'number' ? massDesignId : design.id;
    const request = startRequest();
    setAestheticLoading(true);
    setError('');
    onAestheticGenerated?.(null, aestheticStyle);
    try {
      const result = await createMaasAesthetic({
        job_id: jobId,
        design_id: aestheticDesignId,
        provider: aestheticProvider,
        style: aestheticStyle,
        attach_to_evidence: true,
      }, request.signal);
      if (!request.isCurrent()) return;
      setAesthetic(result);
      onAestheticGenerated?.(result, aestheticStyle);
    } catch (e) {
      if (!request.isCurrent()) return;
      setError(e instanceof Error ? e.message : '외관 이미지 생성 실패');
    } finally {
      request.finish();
    }
  };

  return {
    ...agentReview,
    message, setMessage, result, preview, activePreviewId, loading, previewLoading, operationLoading, aestheticLoading, aestheticProvider, setAestheticProvider, aestheticStyle, setAestheticStyle, aesthetic, error, submit, buildPreview, buildMaasVariants, selectPreview, applyOperation, generateAesthetic
  };
}
