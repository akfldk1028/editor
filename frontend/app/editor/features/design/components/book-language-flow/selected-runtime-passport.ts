import type {
  ExecutedMassManifest,
  ExecutedMassRecord,
  MassExecutionPassport,
} from '../../lib/language-system-types';

interface SelectedRuntimePassportBinding {
  passport: MassExecutionPassport | null;
  error: string;
}

export function publishablePortfolioRunId(
  archive: ExecutedMassManifest,
): string {
  const selectedRunId = archive.selected_run_id?.trim();
  const manifest = archive.publishable_20_manifest;
  return (
    selectedRunId
    && archive.run_id === selectedRunId
    && archive.mass_count === 20
    && archive.run_status === 'pass'
    && archive.numeric_status === 'pass'
    && archive.publishable_20 === true
    && archive.publishable_target_count === 20
    && manifest?.status === 'pass'
    && manifest.target_count === 20
    && Boolean(manifest.shared_legal_floor_field_hash?.trim())
    && manifest.shared_legal_floor_field_hash_count === 1
    && manifest.candidate_actual_gfa_stop_valid_count === 20
    && Array.isArray(manifest.typed_failure_deficits)
    && manifest.typed_failure_deficits.length === 0
  )
    ? selectedRunId
    : '';
}

export function bindSelectedRuntimePassport(
  passport: MassExecutionPassport | null,
  mass: ExecutedMassRecord | null,
  options: { requireCertifiedIdentity?: boolean } = {},
): SelectedRuntimePassportBinding {
  if (!passport || !mass) return { passport: null, error: '' };

  const passportCapacityPlanHash = passport.floor_capacity_plan_hash?.trim();
  const massCapacityPlanHash = mass.floor_capacity_plan_hash?.trim();
  const requireCertifiedIdentity = (
    options.requireCertifiedIdentity !== false
  );
  const passportVisualHash = passport.visual_hash?.trim();
  const massVisualHash = mass.visual_hash?.trim();
  const passportFinalHash = passport.final_legal_geometry_hash?.trim();
  const massFinalHash = (
    mass.final_geometry_hash ?? mass.final_legal_geometry_hash
  )?.trim();
  const passportLegalHash = passport.legal_floor_field_hash?.trim();
  const massLegalHash = mass.legal_floor_field_hash?.trim();
  const passportStopHash = passport.candidate_actual_gfa_stop_hash?.trim();
  const massStopHash = mass.candidate_actual_gfa_stop_hash?.trim();
  const visualMismatch = requireCertifiedIdentity
    ? (
      !passportVisualHash
      || !massVisualHash
      || passportVisualHash !== massVisualHash
    )
    : (
      Boolean(passportVisualHash && massVisualHash)
      && passportVisualHash !== massVisualHash
    );
  const capacityPlanMismatch = requireCertifiedIdentity
    ? (
      !passportCapacityPlanHash
      || !massCapacityPlanHash
      || passportCapacityPlanHash !== massCapacityPlanHash
    )
    : (
      Boolean(passportCapacityPlanHash && massCapacityPlanHash)
      && passportCapacityPlanHash !== massCapacityPlanHash
    );
  const finalGeometryMismatch = identityMismatch(
    passportFinalHash,
    massFinalHash,
    requireCertifiedIdentity,
  );
  const legalFieldMismatch = identityMismatch(
    passportLegalHash,
    massLegalHash,
    requireCertifiedIdentity,
  );
  const actualStopMismatch = identityMismatch(
    passportStopHash,
    massStopHash,
    requireCertifiedIdentity,
  );
  const certificateMismatch = requireCertifiedIdentity
    ? !certificatesMatch(passport, mass)
    : false;
  const mismatches = [
    passport.program_hash !== mass.program_hash ? 'PROGRAM HASH' : '',
    passport.geometry_hash !== mass.geometry_hash ? 'GEOMETRY HASH' : '',
    visualMismatch ? 'VISUAL HASH' : '',
    capacityPlanMismatch ? 'FLOOR CAPACITY PLAN HASH' : '',
    finalGeometryMismatch ? 'FINAL GEOMETRY HASH' : '',
    legalFieldMismatch ? 'LEGAL FLOOR FIELD HASH' : '',
    actualStopMismatch || certificateMismatch
      ? 'ACTUAL GFA STOP HASH'
      : '',
  ].filter(Boolean);

  if (mismatches.length > 0) {
    return {
      passport: null,
      error: `선택 MASS와 실행 passport의 ${mismatches.join(' / ')}가 일치하지 않아 실행 그래프와 elevation 증거를 결합하지 않았습니다.`,
    };
  }

  return { passport, error: '' };
}

function identityMismatch(
  left: string | undefined,
  right: string | undefined,
  required: boolean,
): boolean {
  return required
    ? !left || !right || left !== right
    : Boolean(left && right && left !== right);
}

function certificatesMatch(
  passport: MassExecutionPassport,
  mass: ExecutedMassRecord,
): boolean {
  const passportCertificate = passport.candidate_actual_gfa_stop_certificate;
  const massCertificate = mass.candidate_actual_gfa_stop_certificate;
  if (!passportCertificate || !massCertificate) return false;
  const finalHash = (
    mass.final_geometry_hash ?? mass.final_legal_geometry_hash ?? ''
  ).trim();
  const selectedFloorCount = mass.candidate_floor_count;
  return (
    passportCertificate.status === 'certified'
    && passportCertificate.hard_pass === true
    && massCertificate.status === 'certified'
    && massCertificate.hard_pass === true
    && passportCertificate.program_hash === passport.program_hash
    && passportCertificate.final_geometry_hash
      === passport.final_legal_geometry_hash
    && passportCertificate.visual_hash === passport.visual_hash
    && passportCertificate.legal_floor_field_hash
      === passport.legal_floor_field_hash
    && passportCertificate.candidate_actual_gfa_stop_hash
      === passport.candidate_actual_gfa_stop_hash
    && massCertificate.program_hash === mass.program_hash
    && massCertificate.final_geometry_hash === finalHash
    && massCertificate.visual_hash === mass.visual_hash
    && massCertificate.legal_floor_field_hash
      === mass.legal_floor_field_hash
    && massCertificate.candidate_actual_gfa_stop_hash
      === mass.candidate_actual_gfa_stop_hash
    && (
      typeof selectedFloorCount !== 'number'
      || massCertificate.selected_floor_count === selectedFloorCount
    )
  );
}
