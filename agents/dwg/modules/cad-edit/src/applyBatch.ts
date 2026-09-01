import {
  parseCadEditBatch,
  type CadChange,
  type CadCommandProposal,
  type CadEditBatch,
  type CadEditPrecondition,
  type CadResolvedCommand
} from "@dwg/contracts";
import { cloneDocumentSnapshot, type CadDocumentSnapshot } from "@dwg/cad-document";
import { applyCommand } from "./commandHandlers.js";
import { CadEditError } from "./errors.js";

export interface CadEditPreview {
  transactionId: string;
  baseRevision: number;
  nextRevision: number;
  changes: CadChange[];
  resolvedCommands: CadResolvedCommand[];
  warnings: string[];
  snapshot: CadDocumentSnapshot;
}

export function previewEditBatch(snapshot: CadDocumentSnapshot, input: CadEditBatch): CadEditPreview {
  const batch = parseCadEditBatch(input);
  validateBatch(snapshot, batch);
  const nextRevision = snapshot.revision + 1;
  if (!Number.isSafeInteger(nextRevision)) {
    throw new CadEditError("EDIT_REVISION_LIMIT", "Next document revision exceeds the safe integer range.");
  }

  const preview = cloneDocumentSnapshot(snapshot);
  const changes: CadChange[] = [];
  const resolvedCommands: CadResolvedCommand[] = [];
  for (const proposal of batch.commands) {
    const application = applyCommand(preview, proposal, batch.transactionId);
    changes.push(...application.changes);
    resolvedCommands.push(...application.resolved);
  }
  preview.revision = nextRevision;
  const warnings = [...new Set(
    resolvedCommands.flatMap((resolved) => resolved.warnings)
  )].sort();
  return {
    transactionId: batch.transactionId,
    baseRevision: snapshot.revision,
    nextRevision,
    changes,
    resolvedCommands,
    warnings,
    snapshot: preview
  };
}

function validateBatch(snapshot: CadDocumentSnapshot, batch: CadEditBatch): void {
  if (batch.documentId !== snapshot.documentId) {
    throw new CadEditError("EDIT_DOCUMENT_MISMATCH", "Edit batch document does not match the snapshot.");
  }
  if (batch.expectedRevision !== snapshot.revision) {
    throw new CadEditError("EDIT_REVISION_CONFLICT", "Edit batch revision does not match the snapshot.");
  }
  if (!Number.isSafeInteger(snapshot.revision) || snapshot.revision < 0) {
    throw new CadEditError("EDIT_REVISION_CONFLICT", "Snapshot revision is not a safe non-negative integer.");
  }

  validatePlannedCopyIds(snapshot, batch);
  const targets = new Set<string>();
  const commandIds = new Set<string>();
  for (const proposal of batch.commands) {
    if (proposal.expectedRevision !== batch.expectedRevision) {
      throw new CadEditError("EDIT_REVISION_CONFLICT", "Command revision does not match the edit batch.");
    }
    if (commandIds.has(proposal.commandId)) {
      throw new CadEditError("EDIT_DUPLICATE_TARGET", `Duplicate command ID: ${proposal.commandId}`);
    }
    commandIds.add(proposal.commandId);
    const proposalTargets = commandTargets(proposal);
    for (const target of proposalTargets) {
      if (targets.has(target)) {
        throw new CadEditError("EDIT_DUPLICATE_TARGET", `Duplicate edit target: ${target}`);
      }
      targets.add(target);
    }
    validatePreconditionScope(proposal, proposalTargets);
    for (const precondition of proposal.preconditions) validatePrecondition(snapshot, precondition);
  }
}

function validatePlannedCopyIds(snapshot: CadDocumentSnapshot, batch: CadEditBatch): void {
  const entityIds = new Set(snapshot.index.entities.map((entity) => entity.id));
  for (const proposal of batch.commands) {
    if (proposal.operation.kind !== "entity.copy") continue;
    for (const entityIndex of proposal.operation.handles.keys()) {
      const copyId = `copy:${batch.transactionId}:${proposal.commandId}:${entityIndex}`;
      if (entityIds.has(copyId)) {
        throw new CadEditError("EDIT_COPY_ID_COLLISION", `Copy entity ID collision: ${copyId}`);
      }
      entityIds.add(copyId);
    }
  }
}

function commandTargets(proposal: CadCommandProposal): string[] {
  switch (proposal.operation.kind) {
    case "layer.create":
    case "layer.update":
      return [proposal.operation.layerId];
    case "text.replace":
      return [proposal.operation.handle];
    case "entity.move":
    case "entity.copy":
    case "entity.delete":
      return proposal.operation.handles;
  }
}

function validatePreconditionScope(
  proposal: CadCommandProposal,
  proposalTargets: string[]
): void {
  const allowedTargets = new Set(proposalTargets);
  for (const precondition of proposal.preconditions) {
    if (!allowedTargets.has(precondition.target)) {
      throw new CadEditError(
        "EDIT_PRECONDITION_SCOPE",
        `Precondition target is outside the command scope: ${precondition.target}`
      );
    }
  }

  const coveredTargets = new Set(proposal.preconditions.map((precondition) => precondition.target));
  if (proposalTargets.some((target) => !coveredTargets.has(target))) {
    throw new CadEditError(
      "EDIT_PRECONDITION_COVERAGE",
      "Every command target requires at least one precondition."
    );
  }

  if (proposal.operation.kind === "layer.create") {
    const layerId = proposal.operation.layerId;
    const hasCreateGuard = proposal.preconditions.some((precondition) =>
      precondition.target === layerId &&
      precondition.field === "exists" &&
      precondition.equals === false
    );
    if (!hasCreateGuard) {
      throw new CadEditError(
        "EDIT_PRECONDITION_COVERAGE",
        "layer.create requires exists:false for its layer ID."
      );
    }
  }
}

function validatePrecondition(snapshot: CadDocumentSnapshot, precondition: CadEditPrecondition): void {
  const entity = snapshot.index.entities.find((candidate) => candidate.handle === precondition.target);
  const layer = snapshot.layers.find((candidate) => candidate.id === precondition.target);
  const exists = entity !== undefined || layer !== undefined;
  if (precondition.field === "exists") {
    if (exists !== precondition.equals) failPrecondition(precondition);
    return;
  }
  if (!entity) failPrecondition(precondition);
  if (precondition.field === "type" && entity.type !== precondition.equals) failPrecondition(precondition);
  if (precondition.field === "layer" && entity.layer !== precondition.equals) failPrecondition(precondition);
  if (precondition.field === "text" && entity.text !== precondition.equals) failPrecondition(precondition);
}

function failPrecondition(precondition: CadEditPrecondition): never {
  throw new CadEditError(
    "EDIT_PRECONDITION_FAILED",
    `Precondition failed for ${precondition.target}: ${precondition.field}`
  );
}
