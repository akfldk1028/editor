import type {
  CadChange,
  CadCommandProposal,
  CadEditPoint3,
  CadResolvedCommand,
  CadPoint3
} from "@dwg/contracts";
import type { CadDocumentSnapshot } from "@dwg/cad-document";
import { entityChange, entityChangeState, layerChange, layerChangeState } from "./diff.js";
import { CadEditError } from "./errors.js";

type CadDocumentEntity = CadDocumentSnapshot["index"]["entities"][number];

interface CommandApplication {
  changes: CadChange[];
  resolved: CadResolvedCommand[];
}

const editableEntityTypes = new Set(["LINE", "CIRCLE", "ARC", "LWPOLYLINE"]);

export function applyCommand(
  snapshot: CadDocumentSnapshot,
  proposal: CadCommandProposal,
  transactionId: string
): CommandApplication {
  switch (proposal.operation.kind) {
    case "layer.create":
      return createLayer(snapshot, proposal);
    case "layer.update":
      return updateLayer(snapshot, proposal);
    case "text.replace":
      return replaceText(snapshot, proposal);
    case "entity.move":
      return moveEntities(snapshot, proposal);
    case "entity.copy":
      return copyEntities(snapshot, proposal, transactionId);
    case "entity.delete":
      return deleteEntities(snapshot, proposal);
  }
}

function createLayer(snapshot: CadDocumentSnapshot, proposal: CadCommandProposal): CommandApplication {
  const operation = proposal.operation;
  if (operation.kind !== "layer.create") throw new Error("Unexpected CAD edit command.");
  if (snapshot.layers.some((layer) => layer.id === operation.layerId || layer.name === operation.name)) {
    throw new CadEditError("EDIT_LAYER_EXISTS", `Layer already exists: ${operation.layerId}`);
  }

  const after = {
    id: operation.layerId,
    name: operation.name,
    color: operation.color,
    visible: true,
    frozen: false,
    locked: null
  };
  snapshot.layers.push(after);
  snapshot.index.layers.push({
    name: operation.name,
    entityCount: 0,
    visible: true,
    frozen: false,
    color: operation.color,
    locked: null
  });
  snapshot.index.summary.layerCount += 1;
  const change = layerChange(proposal.commandId, "layer.create", operation.layerId, null, after);
  return resolved(proposal, change, null, layerChangeState(after));
}

function updateLayer(snapshot: CadDocumentSnapshot, proposal: CadCommandProposal): CommandApplication {
  const operation = proposal.operation;
  if (operation.kind !== "layer.update") throw new Error("Unexpected CAD edit command.");
  const layer = snapshot.layers.find((candidate) => candidate.id === operation.layerId);
  if (!layer) throw new CadEditError("EDIT_TARGET_NOT_FOUND", `Layer not found: ${operation.layerId}`);
  const before = structuredClone(layer);
  const previousName = layer.name;
  if (operation.name !== undefined && operation.name !== previousName && snapshot.layers.some((candidate) => candidate.name === operation.name)) {
    throw new CadEditError("EDIT_LAYER_EXISTS", `Layer already exists: ${operation.name}`);
  }
  if (operation.name !== undefined) layer.name = operation.name;
  if (operation.color !== undefined) layer.color = operation.color;
  if (operation.visible !== undefined) layer.visible = operation.visible;
  if (operation.locked !== undefined) layer.locked = operation.locked;

  const indexLayer = snapshot.index.layers.find((candidate) => candidate.name === previousName);
  if (!indexLayer) throw new CadEditError("EDIT_TARGET_NOT_FOUND", `Indexed layer not found: ${previousName}`);
  if (operation.name !== undefined) {
    indexLayer.name = operation.name;
    for (const entity of snapshot.index.entities) {
      if (entity.layer === previousName) entity.layer = operation.name;
    }
  }
  if (operation.color !== undefined) indexLayer.color = operation.color;
  if (operation.visible !== undefined) indexLayer.visible = operation.visible;
  if (operation.locked !== undefined) indexLayer.locked = operation.locked;

  const change = layerChange(proposal.commandId, "layer.update", operation.layerId, before, layer);
  return resolved(proposal, change, layerChangeState(before), layerChangeState(layer));
}

function replaceText(snapshot: CadDocumentSnapshot, proposal: CadCommandProposal): CommandApplication {
  const operation = proposal.operation;
  if (operation.kind !== "text.replace") throw new Error("Unexpected CAD edit command.");
  const entity = entityForHandle(snapshot, operation.handle);
  if (entity.type !== "TEXT" && entity.type !== "MTEXT") {
    throw unsupported(entity);
  }
  if (entity.geometry.kind !== "text") throw unsupported(entity);
  const before = structuredClone(entity);
  entity.text = operation.text;
  const change = entityChange(proposal.commandId, "text.replace", entity.id, before, entity);
  return resolved(
    proposal,
    change,
    entityChangeState(before),
    entityChangeState(entity),
    before.warnings
  );
}

function moveEntities(snapshot: CadDocumentSnapshot, proposal: CadCommandProposal): CommandApplication {
  const operation = proposal.operation;
  if (operation.kind !== "entity.move") throw new Error("Unexpected CAD edit command.");
  const changes: CadChange[] = [];
  const resolvedCommands: CadResolvedCommand[] = [];
  for (const handle of operation.handles) {
    const entity = entityForHandle(snapshot, handle);
    assertEditableEntity(entity);
    const before = structuredClone(entity);
    translateEntity(entity, operation.delta);
    changes.push(entityChange(proposal.commandId, "entity.move", entity.id, before, entity));
    resolvedCommands.push(resolvedCommand(
      proposal,
      entityChangeState(before),
      entityChangeState(entity),
      before.warnings
    ));
  }
  return { changes, resolved: resolvedCommands };
}

function copyEntities(snapshot: CadDocumentSnapshot, proposal: CadCommandProposal, transactionId: string): CommandApplication {
  const operation = proposal.operation;
  if (operation.kind !== "entity.copy") throw new Error("Unexpected CAD edit command.");
  const changes: CadChange[] = [];
  const resolvedCommands: CadResolvedCommand[] = [];
  for (const [entityIndex, handle] of operation.handles.entries()) {
    const source = entityForHandle(snapshot, handle);
    assertEditableEntity(source);
    const copy = structuredClone(source);
    copy.id = `copy:${transactionId}:${proposal.commandId}:${entityIndex}`;
    copy.handle = null;
    translateEntity(copy, operation.delta);
    snapshot.index.entities.push(copy);
    incrementEntityCounts(snapshot, copy, 1);
    changes.push(entityChange(proposal.commandId, "entity.copy", copy.id, null, copy));
    resolvedCommands.push(resolvedCommand(
      proposal,
      entityChangeState(source),
      entityChangeState(copy),
      source.warnings
    ));
  }
  return { changes, resolved: resolvedCommands };
}

function deleteEntities(snapshot: CadDocumentSnapshot, proposal: CadCommandProposal): CommandApplication {
  const operation = proposal.operation;
  if (operation.kind !== "entity.delete") throw new Error("Unexpected CAD edit command.");
  const changes: CadChange[] = [];
  const resolvedCommands: CadResolvedCommand[] = [];
  for (const handle of operation.handles) {
    const entity = entityForHandle(snapshot, handle);
    assertEditableEntity(entity);
    const before = structuredClone(entity);
    const index = snapshot.index.entities.indexOf(entity);
    snapshot.index.entities.splice(index, 1);
    incrementEntityCounts(snapshot, entity, -1);
    changes.push(entityChange(proposal.commandId, "entity.delete", entity.id, before, null));
    resolvedCommands.push(resolvedCommand(
      proposal,
      entityChangeState(before),
      null,
      before.warnings
    ));
  }
  return { changes, resolved: resolvedCommands };
}

function resolved(
  proposal: CadCommandProposal,
  changes: CadChange | CadChange[],
  before: CadResolvedCommand["before"],
  result: CadResolvedCommand["result"],
  warnings: string[] = []
): CommandApplication {
  return {
    changes: Array.isArray(changes) ? changes : [changes],
    resolved: [resolvedCommand(proposal, before, result, warnings)]
  };
}

function resolvedCommand(
  proposal: CadCommandProposal,
  before: CadResolvedCommand["before"],
  result: CadResolvedCommand["result"],
  warnings: string[] = []
): CadResolvedCommand {
  return {
    proposal,
    before,
    result,
    warnings: [...new Set(warnings)].sort()
  };
}

function entityForHandle(snapshot: CadDocumentSnapshot, handle: string): CadDocumentEntity {
  const entity = snapshot.index.entities.find((candidate) => candidate.handle === handle);
  if (!entity) throw new CadEditError("EDIT_TARGET_NOT_FOUND", `Entity not found: ${handle}`);
  return entity;
}

function assertEditableEntity(entity: CadDocumentEntity): void {
  if (!editableEntityTypes.has(entity.type)) throw unsupported(entity);
  const expectedGeometry = entity.type.toLowerCase();
  if (entity.geometry.kind !== expectedGeometry) throw unsupported(entity);
}

function unsupported(entity: CadDocumentEntity): CadEditError {
  return new CadEditError("EDIT_UNSUPPORTED_ENTITY", `Unsupported CAD entity: ${entity.type}`);
}

function translateEntity(entity: CadDocumentEntity, delta: CadEditPoint3): void {
  entity.bbox = translateBox(entity.bbox, delta);
  switch (entity.geometry.kind) {
    case "line":
      entity.geometry.start = translatePoint(entity.geometry.start, delta);
      entity.geometry.end = translatePoint(entity.geometry.end, delta);
      return;
    case "circle":
    case "arc":
      entity.geometry.center = translatePoint(entity.geometry.center, delta);
      return;
    case "lwpolyline":
      entity.geometry.vertices = entity.geometry.vertices.map((vertex) => ({
        ...vertex,
        point: translatePoint(vertex.point, delta)
      }));
      entity.geometry.elevation += delta[2];
      return;
    default:
      throw unsupported(entity);
  }
}

function translatePoint(point: CadPoint3, delta: CadEditPoint3): CadPoint3 {
  return [point[0] + delta[0], point[1] + delta[1], point[2] + delta[2]];
}

function translateBox(
  bbox: CadDocumentEntity["bbox"],
  delta: CadEditPoint3
): CadDocumentEntity["bbox"] {
  if (bbox === null) return null;
  return { min: translatePoint(bbox.min, delta), max: translatePoint(bbox.max, delta) };
}

function incrementEntityCounts(snapshot: CadDocumentSnapshot, entity: CadDocumentEntity, delta: 1 | -1): void {
  snapshot.index.summary.entityCount += delta;
  if (entity.space === "model") snapshot.index.summary.modelSpaceCount += delta;
  if (entity.space === "paper") snapshot.index.summary.paperSpaceCount += delta;
  const layer = snapshot.index.layers.find((candidate) => candidate.name === entity.layer);
  if (!layer) throw new CadEditError("EDIT_TARGET_NOT_FOUND", `Indexed layer not found: ${entity.layer}`);
  layer.entityCount += delta;
}
