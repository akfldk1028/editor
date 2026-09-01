import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  cloneDocumentSnapshot,
  createDocumentSnapshot
} from "@dwg/cad-document";
import type { CadEntityIndex } from "@dwg/contracts";

import { buildIndexFromDxfText } from "../../src/parsers/dxf/dxfIndexer.js";

const fixturePath = "tests/fixtures/dxf/minimal-architectural.dxf";
const fixtureSha256 =
  "86be7bbdf2ca52e4343f0914e2986229229a2db90db9350453f7fc21c17b97b6";

test("parses the retained DXF into an editable document without inventing move geometry", async () => {
  const dxfText = await readFile(fixturePath, "utf8");
  const parsedIndex: CadEntityIndex = buildIndexFromDxfText(dxfText, {
    displayName: "minimal-architectural.dxf"
  });

  const source = createDocumentSnapshot(parsedIndex, fixtureSha256);
  const edited = cloneDocumentSnapshot(source);
  const textLayer = edited.layers.find((layer) => layer.name === "A-TEXT");
  const textEntity = edited.index.entities.find(
    (entity) => entity.text === "ROOM 101"
  );

  assert.deepEqual(textLayer, {
    id: "layer:imported:QS1URVhU",
    name: "A-TEXT",
    color: null,
    visible: true,
    frozen: false,
    locked: null
  });
  assert.ok(textEntity);
  assert.equal(textEntity.layer, "A-TEXT");
  assert.deepEqual(textEntity.geometry, {
    kind: "bbox",
    reason: "dxf-parser-bbox"
  });

  textLayer.name = "A-TEXT-EDITED";
  textEntity.text = "ROOM 101 EDITED";

  assert.equal(source.layers.find((layer) => layer.id === textLayer.id)?.name, "A-TEXT");
  assert.equal(
    source.index.entities.find((entity) => entity.id === textEntity.id)?.text,
    "ROOM 101"
  );
});

test("normalizes parser-generated numeric DXF handles to the public string contract", () => {
  const index = buildIndexFromDxfText([
    "0", "SECTION", "2", "ENTITIES",
    "0", "LINE", "8", "F001_ROOMS",
    "10", "0", "20", "0", "30", "0",
    "11", "10", "21", "0", "31", "0",
    "0", "ENDSEC", "0", "EOF", ""
  ].join("\n"));

  assert.equal(index.entities.length, 1);
  assert.ok(
    index.entities.every(
      (entity) => entity.handle === null || typeof entity.handle === "string"
    )
  );
});
