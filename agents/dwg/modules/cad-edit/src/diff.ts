import type {
  CadChange,
  CadEntityChangeState,
  CadLayerChangeState
} from "@dwg/contracts";
import type {
  CadDocumentLayer,
  CadDocumentSnapshot
} from "@dwg/cad-document";

type CadDocumentEntity = CadDocumentSnapshot["index"]["entities"][number];

export function entityChangeState(entity: CadDocumentEntity): CadEntityChangeState {
  return {
    id: entity.id,
    handle: entity.handle,
    type: entity.type,
    layer: entity.layer,
    bbox: entity.bbox === null ? null : structuredClone(entity.bbox),
    text: entity.text
  };
}

export function layerChangeState(layer: CadDocumentLayer): CadLayerChangeState {
  return {
    id: layer.id,
    name: layer.name,
    color: layer.color,
    visible: layer.visible,
    frozen: layer.frozen,
    locked: layer.locked
  };
}

export function entityChange(
  commandId: string,
  kind: Extract<CadChange["kind"], "text.replace" | "entity.move" | "entity.copy" | "entity.delete">,
  targetId: string,
  before: CadDocumentEntity | null,
  after: CadDocumentEntity | null
): CadChange {
  return {
    commandId,
    kind,
    targetId,
    before: before === null ? null : entityChangeState(before),
    after: after === null ? null : entityChangeState(after)
  };
}

export function layerChange(
  commandId: string,
  kind: Extract<CadChange["kind"], "layer.create" | "layer.update">,
  targetId: string,
  before: CadDocumentLayer | null,
  after: CadDocumentLayer | null
): CadChange {
  return {
    commandId,
    kind,
    targetId,
    before: before === null ? null : layerChangeState(before),
    after: after === null ? null : layerChangeState(after)
  };
}
