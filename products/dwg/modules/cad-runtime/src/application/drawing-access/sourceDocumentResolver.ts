import { CadSaveError, type CadParsedDocumentEvidence, type CadSourceDocumentResolver } from "@dwg/cad-capabilities";

export interface ConfiguredSourceDocumentResolverOptions {
  documentId: string;
  configuredPath: string;
  readSha256(path: string, signal?: AbortSignal): Promise<string>;
  readEvidence(path: string, signal?: AbortSignal): Promise<CadParsedDocumentEvidence>;
}

export function createConfiguredSourceDocumentResolver(
  options: ConfiguredSourceDocumentResolverOptions
): CadSourceDocumentResolver {
  return {
    async resolve(documentId, signal) {
      if (documentId !== options.documentId) {
        throw new CadSaveError("CAD_SAVE_SOURCE_MISMATCH", "CAD_SAVE_SOURCE_MISMATCH");
      }
      if (signal?.aborted) throw signal.reason;
      const [sourceSha256, evidence] = await Promise.all([
        options.readSha256(options.configuredPath, signal),
        options.readEvidence(options.configuredPath, signal)
      ]);
      if (
        evidence.index.drawingId !== documentId ||
        sourceSha256.toUpperCase() !== evidence.sourceSha256.toUpperCase()
      ) {
        throw new CadSaveError("CAD_SAVE_SOURCE_MISMATCH", "CAD_SAVE_SOURCE_MISMATCH");
      }
      return {
        documentId,
        canonicalPath: options.configuredPath,
        sourceSha256: sourceSha256.toUpperCase(),
        drawingVersion: evidence.drawingVersion,
        units: evidence.units
      };
    }
  };
}
