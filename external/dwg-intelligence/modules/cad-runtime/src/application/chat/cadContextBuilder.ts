import type { CadEntityIndex } from "../../domain/cad-index/types.js";

const maxEntities = 200;
const maxTextLength = 500;

export function buildCadContext(index: CadEntityIndex, query = ""): string {
  const typeCounts = new Map<string, number>();
  for (const entity of index.entities) {
    typeCounts.set(entity.type, (typeCounts.get(entity.type) ?? 0) + 1);
  }
  const selectedEntities = selectEntities(index, query);

  const lines = [
    `schema=${index.schemaVersion}`,
    `drawingId=${index.drawingId}`,
    `source=${index.source.kind}:${clean(index.source.displayName)} parser=${index.source.parser}`,
    `summary entities=${index.summary.entityCount} layers=${index.summary.layerCount} unsupported=${index.summary.unsupportedCount}`,
    `types=${[...typeCounts.entries()].map(([type, count]) => `${type}:${count}`).join(",")}`,
    `layers=${index.layers.map((layer) => `${clean(layer.name)}:${layer.entityCount}`).join(",")}`,
    "entities:"
  ];

  for (const entity of selectedEntities) {
    const details = [
      `id=${clean(entity.id)}`,
      `handle=${clean(entity.handle ?? "none")}`,
      `type=${clean(entity.type)}`,
      `layer=${clean(entity.layer)}`,
      `layout=${clean(entity.layout)}`,
      `bbox=${formatBox(entity.bbox)}`
    ];
    if (entity.text) details.push(`text=${JSON.stringify(clean(entity.text).slice(0, maxTextLength))}`);
    if (entity.blockName) details.push(`block=${JSON.stringify(clean(entity.blockName))}`);
    if (entity.warnings.length > 0) details.push(`warnings=${entity.warnings.map(clean).join(",")}`);
    lines.push(`- ${details.join(" ")}`);
  }

  if (index.entities.length > selectedEntities.length) {
    lines.push(
      `selection=whole-index-query-ranked selected=${selectedEntities.length} omitted=${index.entities.length - selectedEntities.length}`
    );
  }
  if (index.unsupported.length > 0) {
    lines.push(
      `unsupported=${index.unsupported
        .map((item) => `${clean(item.type)}:${item.count}:${clean(item.reason)}`)
        .join("|")}`
    );
  }

  return lines.join("\n");
}

function selectEntities(index: CadEntityIndex, query: string) {
  const rawTerms = query.toLowerCase().match(/[\p{L}\p{N}_-]{2,}/gu) ?? [];
  const terms = [...new Set(rawTerms.flatMap((term) => [
    term,
    stripKoreanParticle(term)
  ]))];
  const asksForText = /표|텍스트|문자|text|schedule|table/i.test(query);

  return index.entities
    .map((entity, position) => {
      const searchable = [
        entity.handle,
        entity.type,
        entity.layer,
        entity.layout,
        entity.text,
        entity.blockName,
        ...Object.entries(entity.attributes).flat()
      ]
        .filter((value): value is string => typeof value === "string")
        .join("\n")
        .toLowerCase();
      const score = terms.reduce(
        (total, term) => total + (searchable.includes(term) ? term.length : 0),
        asksForText && entity.text ? 1 : 0
      );
      return { entity, position, score };
    })
    .sort((left, right) => right.score - left.score || left.position - right.position)
    .slice(0, maxEntities)
    .map(({ entity }) => entity);
}

function stripKoreanParticle(term: string) {
  if (!/^[가-힣]+$/u.test(term)) return term;
  const particle = [
    "으로",
    "에서",
    "에게",
    "한테",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "로",
    "와",
    "과",
    "도",
    "만"
  ].find((candidate) => term.endsWith(candidate));
  if (!particle || term.length - particle.length < 2) return term;
  return term.slice(0, -particle.length);
}

function formatBox(box: CadEntityIndex["entities"][number]["bbox"]) {
  if (!box) return "unavailable";
  return `[${box.min.join(",")}]→[${box.max.join(",")}]`;
}

function clean(value: string) {
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "").replace(/\r?\n/g, "\\n");
}
