import type { DrawingFormat } from "@dwg/contracts";

// Save As proves a written copy matches the active document, which holds only
// when both sides come from one parser and one entity model.
//
// Writing DXF from a DWG once failed that proof because ACadSharp derived a
// different bounding box for an XY-plane hatch depending on the format it
// read. The index now projects the hatch's OCS elevation onto world Z instead
// of retaining that artifact, the two readers agree, and that direction
// verifies.
//
// Writing DWG from a DXF still cannot: a DXF is indexed by the legacy indexer
// as cad-index/v0.1 while any DWG can only be read by ACadSharp as
// cad-index/v0.2, so the copy and its source are described by different
// models. That direction is withheld rather than written unverified.
export function drawingExportUnavailableReason(
  sourceFormat: DrawingFormat | null,
  format: DrawingFormat
): string | null {
  if (sourceFormat !== "dxf" || format !== "dwg") return null;
  return "DWG drawing export is withheld for a DXF source because the copy cannot be verified against it.";
}

export function isDrawingExportAvailable(
  sourceFormat: DrawingFormat | null,
  format: DrawingFormat
): boolean {
  return drawingExportUnavailableReason(sourceFormat, format) === null;
}
