import React from 'react';

type A2UIMessage = {
  version?: string;
  createSurface?: { surfaceId: string; catalogId: string };
  updateComponents?: { surfaceId: string; components: A2UIComponent[] };
  updateDataModel?: { surfaceId: string; path: string; value: Record<string, unknown> };
};

type A2UIComponent = {
  id: string;
  component: string;
  children?: string[];
  text?: unknown;
  tone?: string;
  metrics?: unknown;
  review?: unknown;
};

interface Props {
  messages?: Array<Record<string, unknown>>;
}

function resolveBinding(value: unknown, model: Record<string, unknown>): unknown {
  if (!value || typeof value !== 'object' || !('path' in value)) return value;
  const path = String((value as { path: unknown }).path || '/');
  if (path === '/') return model;
  return path
    .split('/')
    .filter(Boolean)
    .reduce<unknown>((acc, key) => {
      if (Array.isArray(acc)) return acc[Number(key)];
      if (acc && typeof acc === 'object') return (acc as Record<string, unknown>)[key];
      return undefined;
    }, model);
}

const formatMetric = (value: unknown): string => (
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '-'
);

const statusColor = (status: unknown): string => {
  if (status === 'pass') return '#5eead4';
  if (status === 'fail') return '#fca5a5';
  return '#93c5fd';
};

const A2UISurfaceRenderer: React.FC<Props> = ({ messages }) => {
  if (!messages?.length) return null;
  const typedMessages = messages as A2UIMessage[];
  const componentMap = new Map<string, A2UIComponent>();
  let model: Record<string, unknown> = {};
  for (const message of typedMessages) {
    for (const component of message.updateComponents?.components || []) {
      componentMap.set(component.id, component);
    }
    if (message.updateDataModel?.path === '/') {
      model = message.updateDataModel.value || {};
    }
  }

  const renderComponent = (id: string): React.ReactNode => {
    const component = componentMap.get(id);
    if (!component) return null;
    if (component.component === 'Column') {
      return (
        <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {(component.children || []).map(childId => renderComponent(childId))}
        </div>
      );
    }
    if (component.component === 'Text') {
      return (
        <div key={id} style={{ color: '#dbeafe', fontSize: 11, fontWeight: component.tone === 'strong' ? 800 : 500 }}>
          {String(resolveBinding(component.text, model) || '')}
        </div>
      );
    }
    if (component.component === 'MetricStrip') {
      const metrics = resolveBinding(component.metrics, model) as Record<string, unknown> | undefined;
      return (
        <div key={id} style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 5 }}>
          {['far', 'bcr', 'height', 'maas_score'].map(metric => (
            <div key={metric} style={{
              border: '1px solid rgba(148,163,184,0.12)',
              borderRadius: 6,
              padding: '5px 6px',
              background: 'rgba(2,6,23,0.38)',
            }}>
              <div style={{ color: '#64748b', fontSize: 9, textTransform: 'uppercase' }}>{metric}</div>
              <div style={{ color: '#e2e8f0', fontSize: 11, fontFamily: 'monospace', marginTop: 2 }}>
                {formatMetric(metrics?.[metric])}
              </div>
            </div>
          ))}
        </div>
      );
    }
    if (component.component === 'AgentReviewCard') {
      const review = resolveBinding(component.review, model) as Record<string, unknown> | undefined;
      return (
        <div key={id} style={{
          border: '1px solid rgba(96,165,250,0.16)',
          borderRadius: 7,
          padding: 7,
          background: 'rgba(15,23,42,0.58)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ color: '#bfdbfe', fontSize: 10, fontWeight: 800 }}>
              {String(review?.agent || 'agent')}
            </span>
            <span style={{ color: statusColor(review?.status), fontSize: 10, fontWeight: 800 }}>
              {String(review?.status || 'done').toUpperCase()}
            </span>
          </div>
          <div style={{ color: '#94a3b8', fontSize: 10, lineHeight: 1.4, marginTop: 4 }}>
            {String(review?.summary || '')}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{
      marginTop: 8,
      padding: 8,
      borderRadius: 8,
      border: '1px solid rgba(96,165,250,0.18)',
      background: 'rgba(15,23,42,0.52)',
    }}>
      {renderComponent('root')}
    </div>
  );
};

export default A2UISurfaceRenderer;
