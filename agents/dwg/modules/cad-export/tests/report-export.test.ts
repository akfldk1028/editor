import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import test from "node:test";

import type { CadOutputVerification, InspectionRun } from "@dwg/contracts";
import type { CadDocumentSnapshot } from "@dwg/cad-document";
import {
  encodeBounded,
  exportCadReport,
  MAX_REPORT_BYTES,
  MAX_REPORT_INPUT_COLLECTION_ITEMS,
  type CadReportInput
} from "../src/index.js";

const transactionIds = [
  "00000000-0000-4000-8000-000000000002",
  "00000000-0000-4000-8000-000000000001"
] as const;

test("exports stable ordered JSON with the full cumulative change set", async () => {
  const report = await exportCadReport(input(), "json");
  const repeated = await exportCadReport(input(), "json");
  const decoded = JSON.parse(new TextDecoder().decode(report.bytes)) as {
    changeSet: { transactionIds: string[]; changes: Array<{ commandId: string; kind: string }> };
  };

  assert.equal(report.mediaType, "application/json; charset=utf-8");
  assert.equal(report.filename, "unsafe-name-rev-2-report.json");
  assert.deepEqual(decoded.changeSet.transactionIds, [...transactionIds]);
  assert.deepEqual(
    decoded.changeSet.changes.map((change) => [change.commandId, change.kind]),
    [
      ["10000000-0000-4000-8000-000000000006", "entity.delete"],
      ["10000000-0000-4000-8000-000000000005", "entity.copy"],
      ["10000000-0000-4000-8000-000000000004", "entity.move"],
      ["10000000-0000-4000-8000-000000000003", "text.replace"],
      ["10000000-0000-4000-8000-000000000002", "layer.update"],
      ["10000000-0000-4000-8000-000000000001", "layer.create"]
    ]
  );
  assert.equal(report.sha256, repeated.sha256);
  assert.deepEqual(report.bytes, repeated.bytes);
  assert.equal(report.sha256, sha256(report.bytes));
});

test("normalizes every semantically unordered report collection for all formats", async () => {
  const original = input();
  const permuted = permuteUnorderedCollections(input());

  for (const format of ["json", "csv", "pdf", "svg"] as const) {
    const [left, right] = await Promise.all([
      exportCadReport(original, format),
      exportCadReport(permuted, format)
    ]);
    assert.equal(right.sha256, left.sha256, format);
    assert.deepEqual(right.bytes, left.bytes, format);
  }
});

test("uses bytewise key ordering instead of host locale collation", async () => {
  const report = await exportCadReport(input(), "json");
  const text = new TextDecoder().decode(report.bytes);

  assert.ok(text.indexOf('"z":"last"') < text.indexOf('"ä":"umlaut"'));
  assert.ok(text.indexOf('"":"bmp"') < text.indexOf('"𐀀":"supplementary"'));
});

test("exports UTF-8 CSV with spreadsheet formulas made literal", async () => {
  const report = await exportCadReport(input("=SUM(1,1)"), "csv");
  const text = new TextDecoder().decode(report.bytes);

  assert.equal(report.mediaType, "text/csv; charset=utf-8");
  assert.equal(report.filename, "unsafe-name-rev-2-report.csv");
  assert.deepEqual([...report.bytes.subarray(0, 3)], [0xef, 0xbb, 0xbf]);
  assert.match(text, /'=SUM\(1,1\)/u);
  assert.match(text, /'\+formula/u);
  assert.match(text, /'-formula/u);
  assert.match(text, /'@formula/u);
  assert.match(text, /00000000-0000-4000-8000-000000000001/u);
  assert.match(text, /entity\.move/u);
});

test("CSV neutralizes formulas after control whitespace and preserves RFC 4180 data", async () => {
  const adversarial = "\u00a0 \t\u000b=SUM(1,1),\"quoted\"\r\nnext";
  const report = await exportCadReport(input(adversarial), "csv");
  const rows = parseCsv(new TextDecoder().decode(report.bytes).replace(/^\uFEFF/u, ""));
  const finding = rows.find((row) => row[0] === "finding");

  assert.ok(finding);
  assert.equal(finding[4], `'${adversarial}`);
  assert.equal(finding[5], "'-formula");
});

test("exports a deterministic PDF 1.7 report without an external renderer", async () => {
  const report = await exportCadReport(input(), "pdf");
  const repeated = await exportCadReport(input(), "pdf");
  const text = new TextDecoder().decode(report.bytes);

  assert.equal(report.mediaType, "application/pdf");
  assert.equal(report.filename, "unsafe-name-rev-2-report.pdf");
  assert.match(text, /^%PDF-1\.7\n/u);
  assert.match(text, /Unsupported geometry: spline/u);
  assert.match(text, /%%EOF\n$/u);
  assert.deepEqual(report.bytes, repeated.bytes);
  assert.equal(report.sha256, sha256(report.bytes));
});

test("PDF xref and object offsets resolve to exact byte positions", async () => {
  const report = await exportCadReport(input(), "pdf");
  const text = new TextDecoder().decode(report.bytes);
  const startXref = Number(/startxref\n(\d+)\n%%EOF/u.exec(text)?.[1]);
  assert.equal(text.slice(startXref, startXref + 4), "xref");

  const xref = text.slice(startXref).split("\n");
  assert.equal(xref[1], "0 6");
  for (let objectNumber = 1; objectNumber <= 5; objectNumber += 1) {
    const offset = Number(xref[2 + objectNumber]?.slice(0, 10));
    assert.equal(text.slice(offset, offset + 7), `${objectNumber} 0 obj`);
  }
});

test("exports valid SVG while explicitly retaining unsupported geometry", async () => {
  const report = await exportCadReport(input(), "svg");
  const text = new TextDecoder().decode(report.bytes);

  assert.equal(report.mediaType, "image/svg+xml; charset=utf-8");
  assert.equal(report.filename, "unsafe-name-rev-2-report.svg");
  assert.match(text, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/u);
  assert.match(text, /Unsupported geometry: spline/u);
  assert.match(text, /00000000-0000-4000-8000-000000000001/u);
  assert.match(text, /entity\.move/u);
  assert.match(text, /<line /u);
  assert.doesNotMatch(text, /<path /u);
});

test("SVG is well-formed XML and escapes report text and attributes", async () => {
  const unsafe = input();
  unsafe.document.documentId = `drawing:&<>\"'`;
  unsafe.document.index.source.displayName = `&<>\"'\u0000.dxf`;
  const report = await exportCadReport(unsafe, "svg");
  const text = new TextDecoder().decode(report.bytes);

  assertWellFormedXml(text);
  assert.match(text, /&amp;&lt;&gt;&quot;&apos;/u);
  assert.doesNotMatch(text, /<title>[^<]*&<>/u);
});

test("serializes all six typed CAD change variants without reordering", async () => {
  const report = await exportCadReport(input(), "json");
  const decoded = JSON.parse(new TextDecoder().decode(report.bytes)) as {
    changeSet: { changes: Array<{ kind: string }> };
  };
  assert.deepEqual(decoded.changeSet.changes.map(({ kind }) => kind), [
    "entity.delete",
    "entity.copy",
    "entity.move",
    "text.replace",
    "layer.update",
    "layer.create"
  ]);
});

test("rejects report bytes beyond the bounded export ceiling", async () => {
  const overlong = input("x".repeat(1_048_577));

  await assert.rejects(
    exportCadReport(overlong, "json"),
    /EXPORT_REPORT_BYTE_LIMIT/u
  );
});

test("preflights multibyte oversized input before every serializer", async () => {
  for (const format of ["json", "csv", "pdf", "svg"] as const) {
    await assert.rejects(
      exportCadReport(input("한".repeat(350_000)), format),
      /EXPORT_REPORT_INPUT_STRING_LIMIT/u,
      format
    );
  }
});

test("bounded writers reject serializer expansion before a body exceeds one MiB", async () => {
  const escaped = input("\u0000".repeat(170_000));
  for (const format of ["json", "pdf", "svg"] as const) {
    await assert.rejects(exportCadReport(escaped, format), /^Error: EXPORT_REPORT_BYTE_LIMIT$/u, format);
  }

  const quoted = input('"'.repeat(524_280));
  quoted.changeSet = null;
  await assert.rejects(exportCadReport(quoted, "csv"), /^Error: EXPORT_REPORT_BYTE_LIMIT$/u);
});

test("preflights excessive depth and collection counts", async () => {
  const deep = input() as CadReportInput & { extra?: unknown };
  let nested: Record<string, unknown> = {};
  deep.extra = nested;
  for (let depth = 0; depth < 40; depth += 1) {
    nested.next = {};
    nested = nested.next as Record<string, unknown>;
  }
  await assert.rejects(exportCadReport(deep, "json"), /EXPORT_REPORT_INPUT_DEPTH_LIMIT/u);

  const numerous = input() as CadReportInput & { extra?: unknown };
  numerous.extra = Array.from({ length: 20_001 }, (_, index) => index);
  await assert.rejects(exportCadReport(numerous, "json"), /EXPORT_REPORT_INPUT_COLLECTION_LIMIT/u);
});

test("rejects oversized arrays from length before traversing indices", async () => {
  let getterCalls = 0;
  const oversizedWithGetter = new Array(20_001);
  Object.defineProperty(oversizedWithGetter, "0", {
    enumerable: true,
    get() {
      getterCalls += 1;
      return "not read";
    }
  });
  for (const sparse of [new Array(20_001), new Array(4_294_967_295)]) {
    const oversized = input() as CadReportInput & { extra?: unknown };
    oversized.extra = sparse;
    await assert.rejects(
      exportCadReport(oversized, "json"),
      /EXPORT_REPORT_INPUT_COLLECTION_LIMIT/u
    );
  }
  const guarded = input() as CadReportInput & { extra?: unknown };
  guarded.extra = oversizedWithGetter;
  await assert.rejects(
    exportCadReport(guarded, "json"),
    /EXPORT_REPORT_INPUT_COLLECTION_LIMIT/u
  );
  assert.equal(getterCalls, 0);

  const dense = input() as CadReportInput & { extra?: unknown };
  dense.extra = Array.from({ length: MAX_REPORT_INPUT_COLLECTION_ITEMS + 1 }, (_, index) => index);
  await assert.rejects(
    exportCadReport(dense, "json"),
    /EXPORT_REPORT_INPUT_COLLECTION_LIMIT/u
  );
});

test("rejects plain objects above the per-object enumerable key cap", async () => {
  const oversized = input() as CadReportInput & { extra?: unknown };
  oversized.extra = Object.fromEntries(
    Array.from(
      { length: MAX_REPORT_INPUT_COLLECTION_ITEMS + 1 },
      (_, index) => [`key-${index}`, null]
    )
  );
  await assert.rejects(
    exportCadReport(oversized, "json"),
    /EXPORT_REPORT_INPUT_COLLECTION_LIMIT/u
  );
});

test("accepts a dense array exactly at the per-collection boundary", async () => {
  const boundary = input() as CadReportInput & { extra?: unknown };
  boundary.extra = Array.from({ length: MAX_REPORT_INPUT_COLLECTION_ITEMS }, () => null);
  await assert.doesNotReject(exportCadReport(boundary, "json"));
});

test("rejects sparse report arrays and non-index enumerable properties", async () => {
  const sparse = input();
  sparse.findings!.warnings = new Array(3);
  sparse.findings!.warnings[2] = "visible";
  await assert.rejects(exportCadReport(sparse, "json"), /EXPORT_REPORT_INPUT_ARRAY_SPARSE/u);

  const decorated = input();
  const warnings = ["visible"] as string[] & { extra?: string };
  warnings.extra = "must not disappear";
  decorated.findings!.warnings = warnings;
  await assert.rejects(
    exportCadReport(decorated, "json"),
    /EXPORT_REPORT_INPUT_ARRAY_PROPERTY/u
  );
});

test("rejects array prototype overrides before inherited method access", async () => {
  let getterCalls = 0;
  const prototype = Object.create(Array.prototype) as unknown[];
  Object.defineProperty(prototype, "map", {
    configurable: true,
    get() {
      getterCalls += 1;
      return Array.prototype.map;
    }
  });
  const unsafe = input();
  Object.setPrototypeOf(unsafe.findings!.warnings, prototype);

  await assert.rejects(
    exportCadReport(unsafe, "json"),
    /EXPORT_REPORT_INPUT_PROTOTYPE/u
  );
  assert.equal(getterCalls, 0);
});

test("rejects proxy array prototypes without invoking proxy traps", async () => {
  let trapCalls = 0;
  const prototype = new Proxy(Array.prototype, {
    get() {
      trapCalls += 1;
      return undefined;
    },
    getOwnPropertyDescriptor() {
      trapCalls += 1;
      return undefined;
    },
    getPrototypeOf() {
      trapCalls += 1;
      return Array.prototype;
    },
    ownKeys() {
      trapCalls += 1;
      return [];
    }
  });
  const unsafe = input();
  Object.setPrototypeOf(unsafe.findings!.warnings, prototype);

  await assert.rejects(
    exportCadReport(unsafe, "json"),
    /EXPORT_REPORT_INPUT_PROTOTYPE/u
  );
  assert.equal(trapCalls, 0);
});

test("rejects null and custom array prototypes", async () => {
  for (const prototype of [null, Object.create(Array.prototype)]) {
    const unsafe = input();
    Object.setPrototypeOf(unsafe.findings!.warnings, prototype);
    await assert.rejects(
      exportCadReport(unsafe, "json"),
      /EXPORT_REPORT_INPUT_PROTOTYPE/u
    );
  }
});

test("rejects own array method overrides as enumerable properties without invoking them", async () => {
  let methodCalls = 0;
  for (const method of ["map", "sort"] as const) {
    const unsafe = input();
    Object.assign(unsafe.findings!.warnings, {
      [method]() {
        methodCalls += 1;
        return [];
      }
    });
    await assert.rejects(
      exportCadReport(unsafe, "json"),
      /EXPORT_REPORT_INPUT_ARRAY_PROPERTY/u
    );
  }
  assert.equal(methodCalls, 0);
});

test("rejects object and array accessors without invoking getters", async () => {
  let getterCalls = 0;
  const objectAccessor = input() as CadReportInput & { extra?: unknown };
  objectAccessor.extra = Object.defineProperty({}, "secret", {
    enumerable: true,
    get() {
      getterCalls += 1;
      return "secret";
    }
  });
  await assert.rejects(
    exportCadReport(objectAccessor, "json"),
    /EXPORT_REPORT_INPUT_ACCESSOR/u
  );

  const arrayAccessor = input();
  const warnings: string[] = [];
  Object.defineProperty(warnings, "0", {
    enumerable: true,
    get() {
      getterCalls += 1;
      return "secret";
    }
  });
  decoratedArrayLength(warnings, 1);
  arrayAccessor.findings!.warnings = warnings;
  await assert.rejects(
    exportCadReport(arrayAccessor, "json"),
    /EXPORT_REPORT_INPUT_ACCESSOR/u
  );
  assert.equal(getterCalls, 0);
});

test("rejects proxies before invoking any user traps", async () => {
  let trapCalls = 0;
  const proxy = new Proxy({}, {
    getPrototypeOf() {
      trapCalls += 1;
      return Object.prototype;
    },
    ownKeys() {
      trapCalls += 1;
      return [];
    },
    getOwnPropertyDescriptor() {
      trapCalls += 1;
      return undefined;
    },
    get() {
      trapCalls += 1;
      return undefined;
    }
  });
  const unsafe = input() as CadReportInput & { extra?: unknown };
  unsafe.extra = proxy;
  await assert.rejects(exportCadReport(unsafe, "json"), /EXPORT_REPORT_INPUT_PROXY/u);
  assert.equal(trapCalls, 0);
});

test("rejects non-plain object prototypes", async () => {
  const unsafe = input() as CadReportInput & { extra?: unknown };
  unsafe.extra = Object.create({ inherited: "not serialized data" }) as object;
  await assert.rejects(exportCadReport(unsafe, "json"), /EXPORT_REPORT_INPUT_PROTOTYPE/u);
});

test("preflight rejects lone high and low surrogates in scalar values", async () => {
  for (const invalid of ["\ud800", "\udc00"]) {
    await assert.rejects(
      exportCadReport(input(invalid), "json"),
      /EXPORT_REPORT_INPUT_UTF16_INVALID/u
    );
  }
});

test("preflight rejects lone surrogates in attribute and map keys regardless of insertion order", async () => {
  for (const surrogate of ["\ud800", "\udc00"]) {
    for (const invalidFirst of [false, true]) {
      const entries = invalidFirst
        ? [[surrogate, "invalid"], ["safe", "value"]]
        : [["safe", "value"], [surrogate, "invalid"]];
      const invalidAttribute = input();
      invalidAttribute.document.index.entities[0]!.attributes = Object.fromEntries(entries);
      await assert.rejects(
        exportCadReport(invalidAttribute, "json"),
        /EXPORT_REPORT_INPUT_UTF16_INVALID/u
      );

      const invalidMap = input();
      invalidMap.verification!.copiedHandleMap = Object.fromEntries(entries);
      await assert.rejects(
        exportCadReport(invalidMap, "json"),
        /EXPORT_REPORT_INPUT_UTF16_INVALID/u
      );
    }
  }
});

test("valid supplementary characters round-trip and use exact UTF-8 byte counts", async () => {
  const emoji = "😀";
  const valid = input(emoji.repeat(131_072));
  valid.changeSet = null;
  const report = await exportCadReport(valid, "json");
  const decoded = JSON.parse(new TextDecoder().decode(report.bytes)) as {
    findings: { findings: Array<{ text: string }> };
  };
  assert.equal(decoded.findings.findings[0]?.text, emoji.repeat(131_072));

  const oversized = input(emoji.repeat(131_073));
  oversized.changeSet = null;
  await assert.rejects(
    exportCadReport(oversized, "json"),
    /EXPORT_REPORT_INPUT_STRING_LIMIT/u
  );
});

test("valid supplementary object keys are permutation-stable", async () => {
  const left = input();
  const right = input();
  left.verification!.copiedHandleMap = { "😀": "smile", "𐀀": "linear-b" };
  right.verification!.copiedHandleMap = { "𐀀": "linear-b", "😀": "smile" };

  const [leftReport, rightReport] = await Promise.all([
    exportCadReport(left, "json"),
    exportCadReport(right, "json")
  ]);
  assert.equal(rightReport.sha256, leftReport.sha256);
  assert.deepEqual(rightReport.bytes, leftReport.bytes);
});

test("preflight rejects direct and indirect active-ancestor cycles", async () => {
  const direct = input() as CadReportInput & { extra?: unknown };
  direct.extra = direct;
  await assert.rejects(exportCadReport(direct, "json"), /EXPORT_REPORT_INPUT_CYCLE/u);

  const indirect = input() as CadReportInput & { extra?: unknown };
  const first: { next?: unknown } = {};
  const second: { next?: unknown } = { next: first };
  first.next = second;
  indirect.extra = first;
  await assert.rejects(exportCadReport(indirect, "json"), /EXPORT_REPORT_INPUT_CYCLE/u);
});

test("shared object and array aliases serialize as deterministic duplicate values", async () => {
  const aliased = input();
  const sharedLayer = aliased.document.index.layers[0]!;
  aliased.document.index.layers = [sharedLayer, sharedLayer];
  const sharedWarnings = ["shared-z", "shared-a"];
  aliased.document.index.entities[0]!.warnings = sharedWarnings;
  aliased.findings!.warnings = sharedWarnings;

  const duplicated = structuredClone(aliased);
  duplicated.document.index.layers = duplicated.document.index.layers.map((layer) => ({ ...layer }));
  duplicated.document.index.entities[0]!.warnings = [...sharedWarnings];
  duplicated.findings!.warnings = [...sharedWarnings];

  const [aliasReport, duplicateReport] = await Promise.all([
    exportCadReport(aliased, "json"),
    exportCadReport(duplicated, "json")
  ]);
  assert.equal(aliasReport.sha256, duplicateReport.sha256);
  assert.deepEqual(aliasReport.bytes, duplicateReport.bytes);
  const decoded = JSON.parse(new TextDecoder().decode(aliasReport.bytes)) as {
    document: { index: { layers: unknown[]; entities: Array<{ id: string; warnings: string[] }> } };
    findings: { warnings: string[] };
  };
  assert.equal(decoded.document.index.layers.length, 2);
  assert.deepEqual(
    decoded.document.index.entities.find(({ id }) => id === "h:20")?.warnings,
    ["shared-a", "shared-z"]
  );
  assert.deepEqual(decoded.findings.warnings, ["shared-a", "shared-z"]);
});

test("enforces the exact final encoded-byte boundary including multibyte text", () => {
  assert.equal(encodeBounded("한".repeat(349_525) + "x").byteLength, MAX_REPORT_BYTES);
  assert.throws(
    () => encodeBounded("한".repeat(349_525) + "xx"),
    /EXPORT_REPORT_BYTE_LIMIT/u
  );
});

function input(formula = "@formula"): CadReportInput {
  return {
    document: documentSnapshot(),
    findings: findings(formula),
    changeSet: {
      documentId: "drawing:unsafe<>:/\\name",
      revision: 2,
      transactionIds: [...transactionIds],
      changes: [
        {
          commandId: "10000000-0000-4000-8000-000000000006",
          kind: "entity.delete",
          targetId: "h:30",
          before: entityState("h:30", "30", "LINE", "0", "delete"),
          after: null
        },
        {
          commandId: "10000000-0000-4000-8000-000000000005",
          kind: "entity.copy",
          targetId: "copy:h:10",
          before: null,
          after: entityState("copy:h:10", null, "LINE", "0", "copy")
        },
        {
          commandId: "10000000-0000-4000-8000-000000000004",
          kind: "entity.move",
          targetId: "h:10",
          before: { id: "h:10", handle: "10", type: "LINE", layer: "0", bbox: { min: [0, 0, 0], max: [1, 1, 0] }, text: null },
          after: { id: "h:10", handle: "10", type: "LINE", layer: "0", bbox: { min: [2, 0, 0], max: [3, 1, 0] }, text: null }
        },
        {
          commandId: "10000000-0000-4000-8000-000000000003",
          kind: "text.replace",
          targetId: "h:20",
          before: entityState("h:20", "20", "TEXT", "A", "before"),
          after: entityState("h:20", "20", "TEXT", "A", formula)
        },
        {
          commandId: "10000000-0000-4000-8000-000000000002",
          kind: "layer.update",
          targetId: "layer:imported:MA",
          before: layerState("layer:imported:MA", "0", 7),
          after: layerState("layer:imported:MA", "0", 1)
        },
        {
          commandId: "10000000-0000-4000-8000-000000000001",
          kind: "layer.create",
          targetId: "layer:created:QQ",
          before: null,
          after: layerState("layer:created:QQ", "A", 3)
        }
      ]
    },
    verification: verification()
  };
}

function documentSnapshot(): CadDocumentSnapshot {
  return {
    documentId: "drawing:unsafe<>:/\\name",
    revision: 2,
    sourceSha256: "A".repeat(64),
    drawingVersion: "AC1032",
    units: "Millimeters",
    index: {
      schemaVersion: "cad-index/v0.2",
      drawingId: "drawing:unsafe<>:/\\name",
      source: { kind: "dxf", displayName: "unsafe<>:/\\name.dxf", parser: "fixture" },
      summary: { entityCount: 2, layerCount: 1, unsupportedCount: 1, modelSpaceCount: 2, paperSpaceCount: 0 },
      drawing: { fileVersion: "AC1032", units: "Millimeters" },
      layers: [{ name: "0", entityCount: 2, visible: true, frozen: false, color: 7, locked: false }],
      unsupported: [{ type: "SPLINE", count: 1, reason: "spline" }],
      entities: [
        {
          id: "h:20", handle: "20", type: "TEXT", layer: "0", space: "model", layout: "Model",
          bbox: { min: [0, 0, 0], max: [0, 0, 0] }, text: "=SUM(1,1)", blockName: null, attributes: { z: "last", a: "first" }, warnings: ["z", "a"],
          geometry: { kind: "text", insertionPoint: [0, 0, 0], alignmentPoint: null, height: 1, rotation: 0, width: null }
        },
        {
          id: "h:10", handle: "10", type: "LINE", layer: "0", space: "model", layout: "Model",
          bbox: { min: [1, 0, 0], max: [2, 1, 0] }, text: "+formula", blockName: null, attributes: {}, warnings: [],
          geometry: { kind: "line", start: [1, 0, 0], end: [2, 1, 0] }
        },
        {
          id: "h:30", handle: "30", type: "SPLINE", layer: "0", space: "model", layout: "Model",
          bbox: null, text: "-formula", blockName: null, attributes: {}, warnings: [],
          geometry: { kind: "unavailable", reason: "spline" }
        }
      ]
    },
    layers: [{ id: "layer:imported:MA", name: "0", color: 7, visible: true, frozen: false, locked: false }]
  };
}

function findings(formula: string): InspectionRun {
  return {
    status: "completed",
    drawingId: "drawing:unsafe<>:/\\name",
    events: [
      { sequence: 1, agentId: "evidence-agent", action: "verify", status: "completed" },
      { sequence: 0, agentId: "orchestrator", action: "plan", status: "planned" }
    ],
    findings: [
      { id: "finding:2", handle: "30", type: "LINE", layer: "0", bbox: null, text: null, reason: "z", confidence: 1 },
      { id: "finding:1", handle: "20", type: "TEXT", layer: "0", bbox: null, text: formula, reason: "-formula", confidence: 1 }
    ],
    issues: [
      { entityId: "h:30", missing: ["bbox", "handle"] },
      { entityId: "h:20", missing: ["type", "id"] }
    ],
    warnings: ["+formula", "-formula", "@formula", "a-warning"]
  };
}

function verification(): CadOutputVerification {
  return {
    id: "verification:1",
    status: "passed",
    format: "dxf",
    version: "AC1032",
    sourceSha256: "A".repeat(64),
    outputSha256: "B".repeat(64),
    intendedChangeCount: 2,
    verifiedChangeCount: 2,
    copiedHandleMap: {
      z: "last",
      ä: "umlaut",
      "": "bmp",
      "𐀀": "supplementary",
      "10": "110",
      "20": "120"
    },
    warnings: ["z-warning", "a-warning"]
  };
}

function entityState(
  id: string,
  handle: string | null,
  type: string,
  layer: string,
  text: string
) {
  return { id, handle, type, layer, bbox: null, text };
}

function layerState(id: string, name: string, color: number) {
  return { id, name, color, visible: true, frozen: false, locked: false };
}

function permuteUnorderedCollections(value: CadReportInput): CadReportInput {
  const result = structuredClone(value);
  result.document.index.entities.reverse();
  result.document.index.layers.reverse();
  result.document.index.unsupported.reverse();
  result.document.layers.reverse();
  for (const entity of result.document.index.entities) {
    entity.warnings.reverse();
    entity.attributes = Object.fromEntries(Object.entries(entity.attributes).reverse());
  }
  if (result.findings) {
    result.findings.findings.reverse();
    result.findings.issues.reverse();
    result.findings.warnings.reverse();
    for (const issue of result.findings.issues) issue.missing.reverse();
  }
  if (result.verification) {
    result.verification.warnings.reverse();
    result.verification.copiedHandleMap = Object.fromEntries(
      Object.entries(result.verification.copiedHandleMap).reverse()
    );
  }
  return result;
}

function parseCsv(value: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]!;
    if (quoted && character === '"' && value[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (!quoted && character === ",") {
      row.push(cell);
      cell = "";
    } else if (!quoted && character === "\r" && value[index + 1] === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      index += 1;
    } else {
      cell += character;
    }
  }
  assert.equal(quoted, false);
  return rows;
}

function assertWellFormedXml(value: string): void {
  assert.doesNotMatch(value, /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/u);
  const parsed = spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-NonInteractive",
      "-Command",
      "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); $xml=[Console]::In.ReadToEnd(); $document=[xml]$xml; $document.DocumentElement.LocalName"
    ],
    { input: value, encoding: "utf8", windowsHide: true }
  );
  assert.equal(parsed.status, 0, parsed.stderr);
  assert.equal(parsed.stdout.trim(), "svg");
}

function decoratedArrayLength(value: unknown[], length: number): void {
  Object.defineProperty(value, "length", { value: length, writable: true });
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex").toUpperCase();
}
