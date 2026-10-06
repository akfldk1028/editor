import DesignInspector from './components/DesignInspector';
import DesignList from './components/DesignList';
import { MassExecutionPassportCard } from './components/MassExecutionPassportCard';
import type { DesignData, GeoJSONFeature } from './lib/types';

interface DesignMassTabProps {
  designs: DesignData[];
  selectedDesign: DesignData | null;
  onSelect: (d: DesignData) => void;
  objectives: { name: string }[];
  featureForDesign: (design: DesignData) => GeoJSONFeature | null;
  selectedMassGeojson: GeoJSONFeature | null;
  showFloorPlanButton: boolean;
  floorPlanLoading: boolean;
  onGenerateFloorPlan: () => void;
}

/** 매스 tab: candidate list + selected design inspector / passport / 평면 생성 */
export function DesignMassTab({
  designs,
  selectedDesign,
  onSelect,
  objectives,
  featureForDesign,
  selectedMassGeojson,
  showFloorPlanButton,
  floorPlanLoading,
  onGenerateFloorPlan,
}: DesignMassTabProps) {
  return (
    <div style={{ padding: '8px 12px', minHeight: 0 }}>
      <DesignList
        designs={designs}
        selectedId={selectedDesign?.id ?? null}
        selectedUid={selectedDesign?.uid ?? null}
        selectedAlgorithm={selectedDesign?.algorithm ?? null}
        onSelect={onSelect}
        objectiveNames={objectives.map(o => o.name)}
        featureForDesign={featureForDesign}
      />

      {selectedDesign && (
        <div style={{ marginTop: 8 }}>
          <DesignInspector
            design={selectedDesign}
            objectiveNames={objectives.map(o => o.name)}
            feature={selectedMassGeojson}
          />
          <MassExecutionPassportCard
            value={selectedMassGeojson?.properties?.mass_execution_passport}
            title={String(
              selectedMassGeojson?.properties?.variant_id
              || selectedMassGeojson?.properties?.mass_shape
              || `MASS ${selectedDesign.id}`
            )}
          />
          {/* 평면 생성 버튼 */}
          {showFloorPlanButton && (
            <button
              onClick={onGenerateFloorPlan}
              disabled={floorPlanLoading}
              style={{
                width: '100%', marginTop: 10, padding: '10px 0',
                borderRadius: 8, border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 700, letterSpacing: '0.03em',
                background: floorPlanLoading
                  ? 'rgba(96,200,255,0.08)'
                  : 'linear-gradient(135deg, rgba(96,200,255,0.15), rgba(96,200,255,0.08))',
                color: '#60c8ff',
                transition: 'all 0.15s',
              }}
            >
              {floorPlanLoading ? '생성 중...' : '⊞ 평면 생성'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
