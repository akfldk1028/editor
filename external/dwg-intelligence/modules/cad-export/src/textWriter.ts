import { Buffer } from "node:buffer";

export const MAX_REPORT_BYTES = 1_048_576;

export class BoundedTextWriter {
  readonly #chunks: string[] = [];
  #byteLength = 0;

  get byteLength(): number {
    return this.#byteLength;
  }

  append(value: string): void {
    const nextBytes = Buffer.byteLength(value, "utf8");
    if (this.#byteLength + nextBytes > MAX_REPORT_BYTES) {
      throw new Error("EXPORT_REPORT_BYTE_LIMIT");
    }
    this.#chunks[this.#chunks.length] = value;
    this.#byteLength += nextBytes;
  }

  finish(): string {
    return arrayJoin(this.#chunks, "");
  }
}

const arrayJoin = Function.prototype.call.bind(Array.prototype.join) as (
  value: readonly string[],
  separator?: string
) => string;
