import type { CadReportInput } from "./index.js";
import { canonicalReport, stableJson } from "./index.js";
import { BoundedTextWriter } from "./textWriter.js";

export function createSvgReport(input: CadReportInput): string {
  const normalized = canonicalReport(input) as unknown as CadReportInput;
  const writer = new BoundedTextWriter();
  writer.append('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" viewBox="0 0 800 600" role="img">\n<title>');
  writeXmlEscaped(writer, normalized.document.index.source.displayName);
  writer.append(" CAD report</title>\n<desc>");
  writeXmlEscaped(writer, stableJson(normalized));
  writer.append('</desc>\n<rect width="800" height="600" fill="white"/>\n<text x="16" y="24" font-family="monospace" font-size="14">');
  writeXmlEscaped(writer, normalized.document.documentId);
  writer.append(` revision ${normalized.document.revision}</text>`);
  let textY = 48;
  const entities = normalized.document.index.entities;
  for (let index = 0; index < entities.length; index += 1) {
    const entity = entities[index]!;
    if (entity.geometry.kind === "line") {
      writer.append(`\n<line x1="${entity.geometry.start[0]}" y1="${entity.geometry.start[1]}" x2="${entity.geometry.end[0]}" y2="${entity.geometry.end[1]}" stroke="black"/>`);
      continue;
    }
    const reason = entity.geometry.kind === "unavailable" || entity.geometry.kind === "bbox"
      ? entity.geometry.reason
      : entity.geometry.kind;
    writer.append(`\n<text x="16" y="${textY}" font-family="monospace" font-size="12">Unsupported geometry: `);
    writeXmlEscaped(writer, reason);
    writer.append(" (");
    writeXmlEscaped(writer, entity.id);
    writer.append(")</text>");
    textY += 16;
  }
  writer.append("\n</svg>");
  return writer.finish();
}

function writeXmlEscaped(writer: BoundedTextWriter, value: string): void {
  let run = "";
  const flush = () => {
    if (run.length > 0) writer.append(run);
    run = "";
  };
  for (const character of value) {
    const escaped = isXmlCharacter(character) ? xmlEscapes[character] : "�";
    if (escaped !== undefined) {
      flush();
      writer.append(escaped);
    } else {
      run += character;
      if (run.length >= 4_096) flush();
    }
  }
  flush();
}

function isXmlCharacter(character: string): boolean {
  const codePoint = character.codePointAt(0)!;
  return (
    codePoint === 0x09 ||
    codePoint === 0x0a ||
    codePoint === 0x0d ||
    (codePoint >= 0x20 && codePoint <= 0xd7ff) ||
    (codePoint >= 0xe000 && codePoint <= 0xfffd) ||
    (codePoint >= 0x10000 && codePoint <= 0x10ffff)
  );
}

const xmlEscapes: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&apos;"
};
