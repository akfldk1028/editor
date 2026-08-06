export type JsonRecord = Record<string, unknown>;

export function asJsonRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

export function parseJsonRecord(text: string): JsonRecord | null {
  try {
    return asJsonRecord(JSON.parse(text) as unknown);
  } catch {
    return null;
  }
}
