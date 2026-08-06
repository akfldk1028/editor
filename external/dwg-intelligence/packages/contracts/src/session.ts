import { z } from "zod";

export const DRAWING_SESSION_ERROR_CODES = [
  "DRAWING_OPEN_CANCELLED",
  "DRAWING_UNSUPPORTED",
  "DRAWING_NOT_FOUND",
  "SESSION_UNKNOWN",
  "SESSION_LIMIT",
  "SESSION_LAST",
  "DIALOG_UNAVAILABLE"
] as const;

export type DrawingSessionErrorCode = (typeof DRAWING_SESSION_ERROR_CODES)[number];

const drawingSession = z.object({
  id: z.string().min(1).max(128),
  displayName: z.string().min(1).max(255),
  drawingId: z.string().min(1).max(255),
  active: z.boolean()
}).strict();

const drawingSessionListResponse = z.object({
  sessions: z.array(drawingSession).max(64),
  activeSessionId: z.string().min(1).max(128),
  /** False in headless and test processes, where no host dialog can be shown. */
  dialogAvailable: z.boolean()
}).strict();

const drawingSessionErrorResponse = z.object({
  error: z.object({
    code: z.enum(DRAWING_SESSION_ERROR_CODES),
    message: z.string().min(1).max(512)
  }).strict()
}).strict();

export type DrawingSession = z.infer<typeof drawingSession>;
export type DrawingSessionListResponse = z.infer<typeof drawingSessionListResponse>;
export type DrawingSessionErrorResponse = z.infer<typeof drawingSessionErrorResponse>;

export function parseDrawingSessionListResponse(value: unknown): DrawingSessionListResponse {
  return drawingSessionListResponse.parse(value);
}

export function parseDrawingSessionErrorResponse(value: unknown): DrawingSessionErrorResponse {
  return drawingSessionErrorResponse.parse(value);
}
