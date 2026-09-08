import { randomUUID } from "node:crypto";
import { realpath, stat } from "node:fs/promises";

import {
  CadSaveError,
  type DestinationGrantStore,
  type OutputDestinationGrant
} from "./contracts.js";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export function createDestinationGrantStore(options: {
  now?: () => number;
  createId?: () => string;
} = {}): DestinationGrantStore {
  const now = options.now ?? Date.now;
  const createId = options.createId ?? randomUUID;
  const active = new Map<string, OutputDestinationGrant>();
  const retired = new Map<string, "expired" | "used">();

  return {
    async issue(directory, expiresAt) {
      if (!Number.isSafeInteger(expiresAt) || expiresAt <= now()) {
        throw new CadSaveError("DESTINATION_GRANT_INVALID");
      }
      let canonicalDirectory: string;
      try {
        canonicalDirectory = await realpath(directory);
        if (!(await stat(canonicalDirectory)).isDirectory()) {
          throw new Error("not a directory");
        }
      } catch {
        throw new CadSaveError("DESTINATION_GRANT_INVALID");
      }
      const id = createId();
      if (!UUID_PATTERN.test(id) || active.has(id) || retired.has(id)) {
        throw new CadSaveError("DESTINATION_GRANT_INVALID");
      }
      active.set(id, {
        id,
        canonicalDirectory,
        expiresAt,
        used: false
      });
      return id;
    },

    async consume(id) {
      if (typeof id !== "string" || !UUID_PATTERN.test(id)) {
        throw new CadSaveError("DESTINATION_GRANT_UNKNOWN");
      }
      const grant = active.get(id);
      if (!grant) {
        const status = retired.get(id);
        throw new CadSaveError(
          status === "used"
            ? "DESTINATION_GRANT_REUSED"
            : status === "expired"
              ? "DESTINATION_GRANT_EXPIRED"
              : "DESTINATION_GRANT_UNKNOWN"
        );
      }
      active.delete(id);
      if (grant.expiresAt <= now()) {
        retired.set(id, "expired");
        throw new CadSaveError("DESTINATION_GRANT_EXPIRED");
      }
      retired.set(id, "used");
      return { ...grant, used: true };
    }
  };
}
