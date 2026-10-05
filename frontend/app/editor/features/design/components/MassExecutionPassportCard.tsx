import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Maximize2, X } from 'lucide-react';

import type { MassExecutionPassport } from '../lib/language-system-types';
import { MassExecutionGraph } from './book-language-flow/MassExecutionGraph';
import './book-language-flow/book-language-flow.css';

interface Props {
  value?: MassExecutionPassport | Record<string, unknown> | null;
  title?: string;
}

function isPassport(value: Props['value']): value is MassExecutionPassport {
  if (!value || typeof value !== 'object') return false;
  return value.schema_version === 'arr.maas.mass_execution_passport.v1'
    && Array.isArray(value.stages)
    && typeof value.activation_graph === 'object';
}

export function MassExecutionPassportCard({ value, title = 'Selected MASS' }: Props) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [open]);
  if (!isPassport(value)) return null;
  const evaluated = value.stages.filter((stage) => stage.status !== 'not_evaluated').length;

  return (
    <section className="design-mass-passport" data-testid="design-mass-execution-passport">
      <header>
        <div><span>PER-MASS EXECUTION PASSPORT</span><strong>{evaluated}/{value.stages.length} stages evaluated</strong></div>
        <button type="button" onClick={() => setOpen(true)}><Maximize2 size={13} /> FULL FLOW</button>
      </header>
      <MassExecutionGraph passport={value} compact />
      {open && createPortal(
        <div className="mass-execution-modal" role="dialog" aria-modal="true" aria-label={`${title} 전체 실행 경로`}>
          <header>
            <div><span>ACTUAL GENERATED MASS / EXECUTION PASSPORT</span><h2>{title}</h2></div>
            <button type="button" onClick={() => setOpen(false)} aria-label="전체 실행 경로 닫기"><X size={18} /></button>
          </header>
          <MassExecutionGraph passport={value} />
          <div className="mass-execution-modal__stages">
            {value.stages.map((stage, index) => (
              <div key={stage.id} data-status={stage.status}>
                <b>{String(index + 1).padStart(2, '0')}</b><span>{stage.label}</span><strong>{stage.status.replaceAll('_', ' ').toUpperCase()}</strong>
              </div>
            ))}
          </div>
          <footer><code>{value.geometry_hash}</code><span>법규·주차·VLM 미평가는 PASS로 계산되지 않습니다.</span></footer>
        </div>,
        document.body,
      )}
    </section>
  );
}
