import assert from "node:assert/strict";
import test from "node:test";

import {
  clampArtifactWidth,
  clampSidebarWidth,
  createWorkspacePreferencesStore,
  defaultWorkspacePreferences,
  resolveTheme
} from "../../src/app/workspacePreferences.js";

test("resolves explicit and system theme preferences", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
});

test("clamps the CAD artifact width while preserving the conversation", () => {
  assert.equal(clampArtifactWidth(1440, 900, true), 606);
  assert.equal(clampArtifactWidth(1440, 300, true), 520);
  assert.equal(clampArtifactWidth(1200, 1000, false), 693);
});

test("workspace preferences persist and reject malformed storage", () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value)
  };
  const store = createWorkspacePreferencesStore(storage);

  assert.deepEqual(store.load(), defaultWorkspacePreferences);
  store.save({
    theme: "dark",
    artifactWidth: 720,
    sidebarWidth: 400,
    sidebarTab: "skills",
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  });
  assert.equal(store.load().theme, "dark");
  assert.equal(store.load().artifactWidth, 720);

  values.set("dwg.workspace-preferences.v2", "{\"theme\":\"invalid\"}");
  assert.deepEqual(store.load(), defaultWorkspacePreferences);
});

test("migrates legacy v1 preferences to a clamped v2 sidebar preference", () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value)
  };
  values.set("dwg.workspace-preferences.v1", JSON.stringify({
    theme: "dark",
    artifactWidth: 720,
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  }));

  const store = createWorkspacePreferencesStore(storage);
  assert.deepEqual(store.load(), {
    theme: "dark",
    artifactWidth: 720,
    sidebarWidth: 320,
    sidebarTab: "project",
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  });
  assert.deepEqual(JSON.parse(values.get("dwg.workspace-preferences.v2")!), store.load());
});

test("clamps persisted sidebar widths and rejects unknown sidebar tabs", () => {
  assert.equal(clampSidebarWidth(200), 280);
  assert.equal(clampSidebarWidth(500), 420);

  const values = new Map<string, string>([["dwg.workspace-preferences.v2", JSON.stringify({
    theme: "system",
    artifactWidth: 680,
    sidebarWidth: 500,
    sidebarTab: "skills",
    sidebarSections: {
      project: true,
      drawing: true,
      sessions: true
    }
  })]]);
  const store = createWorkspacePreferencesStore({
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value)
  });

  assert.equal(store.load().sidebarWidth, 420);

  values.set("dwg.workspace-preferences.v2", JSON.stringify({
    theme: "system",
    artifactWidth: 680,
    sidebarWidth: 320,
    sidebarTab: "unknown",
    sidebarSections: {
      project: true,
      drawing: true,
      sessions: true
    }
  }));
  assert.deepEqual(store.load(), defaultWorkspacePreferences);
});

test("workspace preference storage failures preserve usable defaults", () => {
  const store = createWorkspacePreferencesStore({
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    }
  });

  assert.deepEqual(store.load(), defaultWorkspacePreferences);
  assert.doesNotThrow(() => store.save(defaultWorkspacePreferences));
});

test("attempts a legacy migration only once when v2 persistence is blocked", () => {
  let legacyReads = 0;
  let writeAttempts = 0;
  const legacy = JSON.stringify({
    theme: "dark",
    artifactWidth: 720,
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  });
  const store = createWorkspacePreferencesStore({
    getItem(key) {
      if (key === "dwg.workspace-preferences.v1") {
        legacyReads += 1;
        return legacy;
      }
      return null;
    },
    setItem() {
      writeAttempts += 1;
      throw new Error("blocked");
    }
  });
  const expected = {
    theme: "dark" as const,
    artifactWidth: 720,
    sidebarWidth: 320,
    sidebarTab: "project" as const,
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  };

  assert.deepEqual(store.load(), expected);
  assert.deepEqual(store.load(), expected);
  assert.equal(legacyReads, 1);
  assert.equal(writeAttempts, 1);
});
