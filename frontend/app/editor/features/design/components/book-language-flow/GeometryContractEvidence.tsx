import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Maximize2, X } from 'lucide-react';

import type { MaasLanguageSystemManifest, MassExecutionPassport } from '../../lib/language-system-types';
import { getGeometryShapePassport, getGeometryShapePreviewUrl } from '../../lib/api-client';
import type { NetworkNode } from './LanguageNetworkCanvas';
import { MassExecutionGraph } from './MassExecutionGraph';

interface GeometryContractEvidenceProps {
  node: NetworkNode | null;
  contract: MaasLanguageSystemManifest['geometry_language_contract'];
}

export function GeometryContractEvidence({ node, contract }: GeometryContractEvidenceProps) {
  const [passport, setPassport] = useState<MassExecutionPassport | null>(null);
  const [passportError, setPassportError] = useState('');
  const [flowOpen, setFlowOpen] = useState(false);
  const family = String(node?.attributes.family ?? '');
  const shape = contract.shapes.find((item) => item.family === family);

  useEffect(() => {
    setPassport(null);
    setPassportError('');
    if (!shape) return undefined;
    const controller = new AbortController();
    getGeometryShapePassport(shape.index, controller.signal)
      .then(setPassport)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setPassportError(reason instanceof Error ? reason.message : '실행 여권을 읽지 못했습니다.');
      });
    return () => controller.abort();
  }, [shape]);

  useEffect(() => {
    if (!flowOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFlowOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [flowOpen]);

  if (!node) return <aside className="book-evidence book-evidence--empty"><span>GEOMETRY PROGRAM</span><p>노드를 선택하면 실제 DSL과 컴파일 근거를 표시합니다.</p></aside>;
  return (
    <aside className="book-evidence">
      <div className="book-evidence__heading">
        <span>{node.stage.replaceAll('_', ' ').toUpperCase()}</span>
        <h4>{node.label}</h4>
        <code>{node.id}</code>
      </div>
      {shape ? (
        <>
          <div className="book-evidence__sources geometry-contract__preview">
            <figure>
              <img src={getGeometryShapePreviewUrl(shape.index)} alt={`${shape.name} compiled four-view MASS`} />
              <figcaption><strong>COMPILED MASS · FOUR VIEWS</strong><span>geometry hash 기반 deterministic render</span></figcaption>
            </figure>
          </div>
          <dl className="book-evidence__attributes">
            <div><dt>VISUAL RULE</dt><dd>{shape.feature}</dd></div>
            <div><dt>PRIMITIVE</dt><dd>{shape.primitive_operators.join(' · ')}</dd></div>
            <div><dt>OPERATORS</dt><dd>{shape.operators.join(' → ')}</dd></div>
            <div><dt>RECOMMENDED</dt><dd>{shape.recommended}</dd></div>
            <div><dt>GEOMETRY RISK</dt><dd>{shape.risk}</dd></div>
            <div><dt>GATE</dt><dd>{shape.gate_pass ? 'PASS' : 'FAIL'} · {shape.compile_status}</dd></div>
            <div><dt>GEOMETRY HASH</dt><dd>{shape.geometry_hash.slice(0, 18)}</dd></div>
          </dl>
          <div className="geometry-contract__passport">
            <div className="geometry-contract__passport-title">
              <span>MASS EXECUTION PASSPORT</span>
              <button type="button" onClick={() => setFlowOpen(true)} disabled={!passport}><Maximize2 size={13} /> FULL FLOW</button>
            </div>
            {passport ? <MassExecutionGraph passport={passport} compact resultImageUrl={getGeometryShapePreviewUrl(shape.index)} /> : <p>{passportError || '실제 실행 경로를 불러오는 중…'}</p>}
          </div>
          <div className="geometry-contract__program">
            <span>EXECUTABLE MASS DSL</span>
            <pre>{shape.minimum_program}</pre>
          </div>
          {flowOpen && passport && createPortal(
            <div className="mass-execution-modal" role="dialog" aria-modal="true" aria-label={`${shape.name} 전체 실행 경로`}>
              <header>
                <div><span>MASS {String(shape.index).padStart(2, '0')} / EXECUTION PASSPORT</span><h2>{shape.name}</h2></div>
                <button type="button" onClick={() => setFlowOpen(false)} aria-label="전체 실행 경로 닫기"><X size={18} /></button>
              </header>
              <MassExecutionGraph passport={passport} resultImageUrl={getGeometryShapePreviewUrl(shape.index)} />
              <div className="mass-execution-modal__stages">
                {passport.stages.map((stage, index) => (
                  <div key={stage.id} data-status={stage.status}>
                    <b>{String(index + 1).padStart(2, '0')}</b><span>{stage.label}</span><strong>{stage.status.replaceAll('_', ' ').toUpperCase()}</strong>
                  </div>
                ))}
              </div>
              <footer><code>{passport.geometry_hash}</code><span>NOT EVALUATED는 PASS로 계산되지 않습니다.</span></footer>
            </div>,
            document.body,
          )}
        </>
      ) : (
        <dl className="book-evidence__attributes">
          <div><dt>NODE KIND</dt><dd>{node.kind}</dd></div>
          <div><dt>INVARIANT</dt><dd>{contract.type_invariant}</dd></div>
          <div><dt>GRAMMAR</dt><dd>{contract.recursive_grammar.join(' · ')}</dd></div>
        </dl>
      )}
    </aside>
  );
}
