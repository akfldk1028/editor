import { z } from "zod";

export const CAD_EDIT_SCHEMA_VERSION = "cad-edit/v1" as const;
export const MAX_CAD_EDIT_TEXT_CHARS = 16_384;
export const MAX_CAD_EDIT_COMMANDS_PER_BATCH = 100;
export const MAX_CAD_EDIT_HANDLES_PER_COMMAND = 200;
export const MAX_CAD_EDIT_PREVIEW_CHANGES = 200;
export const MAX_CAD_EDIT_PREVIEW_WARNINGS = 100;
export const CAD_EDIT_LAYER_ID_PATTERN = /^layer:(?:imported|created):[A-Za-z0-9_-]+$/;

const nonEmptyString = z.string().min(1);
const uuid = z.string().uuid();
const revision = z.number().int().nonnegative().safe();
const editErrorCode = z.string().regex(/^EDIT_[A-Z0-9_]{1,60}$/);
const editErrorMessage = z.string().min(1).max(240);
const aciColor = z.number().int().min(1).max(255);
const handle = nonEmptyString;
const layerId = z.string().regex(CAD_EDIT_LAYER_ID_PATTERN);

export const cadEditPoint3Schema = z.tuple([
  z.number().finite(),
  z.number().finite(),
  z.number().finite()
]);

export const cadPointBoxSchema = z.object({
  min: cadEditPoint3Schema,
  max: cadEditPoint3Schema
}).strict();

const cadHandleListSchema = z.array(handle).min(1).max(MAX_CAD_EDIT_HANDLES_PER_COMMAND).superRefine((handles, context) => {
  const duplicate = handles.find((item, index) => handles.indexOf(item) !== index);
  if (duplicate !== undefined) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: `Duplicate handle: ${duplicate}`
    });
  }
});

export const cadEditCommandSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("layer.create"),
    layerId,
    name: nonEmptyString,
    color: aciColor
  }).strict(),
  z.object({
    kind: z.literal("layer.update"),
    layerId,
    name: nonEmptyString.optional(),
    color: aciColor.optional(),
    visible: z.boolean().optional(),
    locked: z.boolean().optional()
  }).strict(),
  z.object({
    kind: z.literal("text.replace"),
    handle,
    text: z.string().max(MAX_CAD_EDIT_TEXT_CHARS)
  }).strict(),
  z.object({
    kind: z.literal("entity.move"),
    handles: cadHandleListSchema,
    delta: cadEditPoint3Schema
  }).strict(),
  z.object({
    kind: z.literal("entity.copy"),
    handles: cadHandleListSchema,
    delta: cadEditPoint3Schema
  }).strict(),
  z.object({
    kind: z.literal("entity.delete"),
    handles: cadHandleListSchema
  }).strict()
]).superRefine((operation, context) => {
  if (
    operation.kind === "layer.update" &&
    operation.name === undefined &&
    operation.color === undefined &&
    operation.visible === undefined &&
    operation.locked === undefined
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "layer.update requires at least one mutable field"
    });
  }
});

export const cadEditOriginSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("user"), id: nonEmptyString }).strict(),
  z.object({
    kind: z.literal("skill"),
    id: nonEmptyString,
    skillVersion: nonEmptyString,
    runId: uuid
  }).strict()
]);

export const cadEditPreconditionSchema = z.discriminatedUnion("field", [
  z.object({ target: nonEmptyString, field: z.literal("exists"), equals: z.boolean() }).strict(),
  z.object({ target: nonEmptyString, field: z.literal("type"), equals: z.string() }).strict(),
  z.object({ target: nonEmptyString, field: z.literal("layer"), equals: z.string() }).strict(),
  z.object({ target: nonEmptyString, field: z.literal("text"), equals: z.string() }).strict()
]);

export const cadCommandProposalSchema = z.object({
  commandId: uuid,
  expectedRevision: revision,
  origin: cadEditOriginSchema,
  preconditions: z.array(cadEditPreconditionSchema).min(1),
  operation: cadEditCommandSchema
}).strict();

export const cadEditBatchSchema = z.object({
  schemaVersion: z.literal(CAD_EDIT_SCHEMA_VERSION),
  transactionId: uuid,
  documentId: nonEmptyString,
  expectedRevision: revision,
  commands: z.array(cadCommandProposalSchema).min(1).max(MAX_CAD_EDIT_COMMANDS_PER_BATCH)
}).strict().superRefine((batch, context) => {
  batch.commands.forEach((command, index) => {
    if (command.expectedRevision !== batch.expectedRevision) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["commands", index, "expectedRevision"],
        message: "Command expectedRevision must equal batch expectedRevision"
      });
    }
  });
});

export const cadEntityChangeStateSchema = z.object({
  id: nonEmptyString,
  handle: handle.nullable(),
  type: nonEmptyString,
  layer: nonEmptyString,
  bbox: cadPointBoxSchema.nullable(),
  text: z.string().nullable()
}).strict();

export const cadLayerChangeStateSchema = z.object({
  id: nonEmptyString,
  name: nonEmptyString,
  color: aciColor.nullable(),
  visible: z.boolean(),
  frozen: z.boolean(),
  locked: z.boolean().nullable()
}).strict();

const cadLayerChangeSchema = z.object({
  commandId: uuid,
  kind: z.union([z.literal("layer.create"), z.literal("layer.update")]),
  targetId: nonEmptyString,
  before: cadLayerChangeStateSchema.nullable(),
  after: cadLayerChangeStateSchema.nullable()
}).strict();

const cadEntityChangeSchema = z.object({
  commandId: uuid,
  kind: z.union([
    z.literal("text.replace"),
    z.literal("entity.move"),
    z.literal("entity.copy"),
    z.literal("entity.delete")
  ]),
  targetId: nonEmptyString,
  before: cadEntityChangeStateSchema.nullable(),
  after: cadEntityChangeStateSchema.nullable()
}).strict();

export const cadChangeSchema = z.union([cadLayerChangeSchema, cadEntityChangeSchema]);

export const cadResolvedCommandSchema = z.object({
  proposal: cadCommandProposalSchema,
  before: z.union([cadEntityChangeStateSchema, cadLayerChangeStateSchema]).nullable(),
  result: z.union([cadEntityChangeStateSchema, cadLayerChangeStateSchema]).nullable(),
  warnings: z.array(z.string())
}).strict();

export const cadEditPreviewResponseSchema = z.object({
  previewId: uuid,
  documentId: nonEmptyString,
  transactionId: uuid,
  baseRevision: revision,
  nextRevision: revision,
  changeCount: z.number().int().nonnegative().safe(),
  changesTruncated: z.boolean(),
  changes: z.array(cadChangeSchema).max(MAX_CAD_EDIT_PREVIEW_CHANGES),
  warningCount: z.number().int().nonnegative().safe(),
  warningsTruncated: z.boolean(),
  warnings: z.array(z.string()).max(MAX_CAD_EDIT_PREVIEW_WARNINGS)
}).strict().superRefine((preview, context) => {
  if (preview.nextRevision !== preview.baseRevision + 1) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["nextRevision"],
      message: "nextRevision must equal baseRevision + 1"
    });
  }
  if (
    preview.changeCount < preview.changes.length ||
    preview.changesTruncated !== (preview.changeCount > preview.changes.length)
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["changesTruncated"],
      message: "changesTruncated must exactly describe omitted changes"
    });
  }
  if (
    preview.warningCount < preview.warnings.length ||
    preview.warningsTruncated !== (preview.warningCount > preview.warnings.length)
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["warningsTruncated"],
      message: "warningsTruncated must exactly describe omitted warnings"
    });
  }
});

export const cadEditApplyResponseSchema = z.object({
  documentId: nonEmptyString,
  revision,
  transactionId: uuid,
  changeCount: z.number().int().nonnegative()
}).strict();

const cadEditStaleErrorSchema = z.object({
  code: z.literal("EDIT_PREVIEW_STALE"),
  message: editErrorMessage,
  currentRevision: revision
}).strict();

const cadEditGenericErrorSchema = z.object({
  code: editErrorCode.refine((code) => code !== "EDIT_PREVIEW_STALE"),
  message: editErrorMessage
}).strict();

export const cadEditErrorResponseSchema = z.object({
  error: z.union([cadEditStaleErrorSchema, cadEditGenericErrorSchema])
}).strict();

export const cadEditPreviewRequestSchema = z.object({
  batch: cadEditBatchSchema
}).strict();

export const cadEditApplyRequestSchema = z.object({
  previewId: uuid,
  documentId: nonEmptyString,
  expectedRevision: revision,
  approved: z.literal(true)
}).strict();

export const cadEditHistoryRequestSchema = z.object({
  documentId: nonEmptyString,
  expectedRevision: revision,
  approved: z.literal(true)
}).strict();

export type CadEditPoint3 = z.infer<typeof cadEditPoint3Schema>;
export type CadEditCommand = z.infer<typeof cadEditCommandSchema>;
export type CadEditOrigin = z.infer<typeof cadEditOriginSchema>;
export type CadEditPrecondition = z.infer<typeof cadEditPreconditionSchema>;
export type CadCommandProposal = z.infer<typeof cadCommandProposalSchema>;
export type CadEditBatch = z.infer<typeof cadEditBatchSchema>;
export type CadEntityChangeState = z.infer<typeof cadEntityChangeStateSchema>;
export type CadLayerChangeState = z.infer<typeof cadLayerChangeStateSchema>;
export type CadChange = z.infer<typeof cadChangeSchema>;
export type CadResolvedCommand = z.infer<typeof cadResolvedCommandSchema>;
export type CadEditPreviewResponse = z.infer<typeof cadEditPreviewResponseSchema>;
export type CadEditApplyResponse = z.infer<typeof cadEditApplyResponseSchema>;
export type CadEditErrorResponse = z.infer<typeof cadEditErrorResponseSchema>;
export type CadEditPreviewRequest = z.infer<typeof cadEditPreviewRequestSchema>;
export type CadEditApplyRequest = z.infer<typeof cadEditApplyRequestSchema>;
export type CadEditHistoryRequest = z.infer<typeof cadEditHistoryRequestSchema>;

export function parseCadEditBatch(value: unknown): CadEditBatch {
  return cadEditBatchSchema.parse(value);
}

export function parseCadEditPreviewRequest(value: unknown): CadEditPreviewRequest {
  return cadEditPreviewRequestSchema.parse(value);
}

export function parseCadEditApplyRequest(value: unknown): CadEditApplyRequest {
  return cadEditApplyRequestSchema.parse(value);
}

export function parseCadEditHistoryRequest(value: unknown): CadEditHistoryRequest {
  return cadEditHistoryRequestSchema.parse(value);
}

export function parseCadEditPreviewResponse(value: unknown): CadEditPreviewResponse {
  return cadEditPreviewResponseSchema.parse(value);
}

export function parseCadEditApplyResponse(value: unknown): CadEditApplyResponse {
  return cadEditApplyResponseSchema.parse(value);
}

export function parseCadEditErrorResponse(value: unknown): CadEditErrorResponse {
  return cadEditErrorResponseSchema.parse(value);
}
