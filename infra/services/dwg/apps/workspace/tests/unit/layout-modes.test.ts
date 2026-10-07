import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  artifactPresentationFor,
  artifactShareFor,
  artifactWidthFor,
  clampArtifactWidth,
  layout,
  layoutModeFor,
  maximumArtifactWidth,
  sharedRowWidth
} from "../../src/app/layoutModes.js";

test("modes follow the workspace width at the shared thresholds", () => {
  assert.equal(layoutModeFor(1920), "wide");
  assert.equal(layoutModeFor(1200), "wide");
  assert.equal(layoutModeFor(1199), "medium");
  assert.equal(layoutModeFor(768), "medium");
  assert.equal(layoutModeFor(767), "narrow");
  assert.equal(layoutModeFor(360), "narrow");
});

test("the stylesheet's container queries repeat the layoutModes thresholds", () => {
  const css = readFileSync(new URL("../../src/app/styles.css", import.meta.url), "utf8");
  const thresholds = new Set(
    [...css.matchAll(/@container dwg-workspace \((min|max)-width: (\d+)px\)/g)]
      .map(([, kind, value]) => kind === "max" ? Number(value) + 1 : Number(value))
  );
  assert.deepEqual([...thresholds].sort((a, b) => a - b), [layout.mediumMinWidth, layout.wideMinWidth]);
});

test("the artifact defaults to 45% of the row and never squeezes the conversation below its floor", () => {
  const row = sharedRowWidth(1920, "wide", true, 240);
  assert.equal(row, 1920 - 240 - layout.separatorWidth);
  assert.equal(artifactWidthFor(row, null), Math.round(row * 0.45));
  assert.ok(row - layout.separatorWidth - artifactWidthFor(row, 0.8) >= layout.conversationMinWidth);
  assert.equal(clampArtifactWidth(1000, 100), layout.artifact.min);
  assert.equal(clampArtifactWidth(1000, 5000), maximumArtifactWidth(1000));
});

test("a persisted share scales with the row instead of pinning a px width", () => {
  const share = artifactShareFor(1673, 998);
  const smaller = artifactWidthFor(1193, share);
  assert.ok(1193 - layout.separatorWidth - smaller > layout.conversationMinWidth + 100);
});

test("the artifact sits inline only while both minimums fit; narrow shows one panel", () => {
  assert.equal(artifactPresentationFor("wide", 1000), "inline");
  assert.equal(artifactPresentationFor("medium", 768), "inline");
  assert.equal(artifactPresentationFor("medium", 600), "sheet");
  assert.equal(artifactPresentationFor("narrow", 700), "panel");
});

test("sidebar track: inline width + separator, rail when collapsed, none below wide", () => {
  assert.equal(sharedRowWidth(1440, "wide", true, 240), 1440 - 240 - layout.separatorWidth);
  assert.equal(sharedRowWidth(1440, "wide", false, 240), 1440 - layout.sidebar.rail);
  assert.equal(sharedRowWidth(1100, "medium", true, 240), 1100);
});
