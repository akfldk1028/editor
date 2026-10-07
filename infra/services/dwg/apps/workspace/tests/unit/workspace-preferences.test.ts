import assert from "node:assert/strict";
import test from "node:test";

import {
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
    artifactShare: 0.6,
    sidebarWidth: 300,
    sidebarCollapsed: true,
    sidebarTab: "skills",
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  });
  assert.equal(store.load().theme, "dark");
  assert.equal(store.load().artifactShare, 0.6);
  assert.equal(store.load().sidebarCollapsed, true);

  values.set("dwg.workspace-preferences.v3", "{\"theme\":\"invalid\"}");
  assert.deepEqual(store.load(), defaultWorkspacePreferences);
});

test("migrates legacy v1 preferences to v3 defaults for the new layout", () => {
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
    artifactShare: null,
    sidebarWidth: 240,
    sidebarCollapsed: false,
    sidebarTab: "project",
    sidebarSections: {
      project: false,
      drawing: true,
      sessions: true
    }
  });
  assert.deepEqual(JSON.parse(values.get("dwg.workspace-preferences.v3")!), store.load());
});

test("clamps persisted sidebar widths and rejects unknown sidebar tabs", () => {
  assert.equal(clampSidebarWidth(150), 200);
  assert.equal(clampSidebarWidth(500), 320);
  assert.equal(clampSidebarWidth(320), 320);

  const values = new Map<string, string>([["dwg.workspace-preferences.v3", JSON.stringify({
    theme: "system",
    artifactShare: 0.5,
    sidebarWidth: 500,
    sidebarCollapsed: false,
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

  assert.equal(store.load().sidebarWidth, 320);

  values.set("dwg.workspace-preferences.v3", JSON.stringify({
    theme: "system",
    artifactShare: 0.5,
    sidebarWidth: 240,
    sidebarCollapsed: false,
    sidebarTab: "unknown",
    sidebarSections: {
      project: true,
      drawing: true,
      sessions: true
    }
  }));
  assert.deepEqual(store.load(), defaultWorkspacePreferences);
});

test("migrates v2 preferences: keeps theme, tab and a clamped sidebar, drops the px artifact width", () => {
  const values = new Map<string, string>([["dwg.workspace-preferences.v2", JSON.stringify({
    theme: "light",
    artifactWidth: 998,
    sidebarWidth: 420,
    sidebarTab: "sessions",
    sidebarSections: { project: true, drawing: false, sessions: true }
  })]]);
  const store = createWorkspacePreferencesStore({
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value)
  });
  assert.deepEqual(store.load(), {
    theme: "light",
    artifactShare: null,
    sidebarWidth: 320,
    sidebarCollapsed: false,
    sidebarTab: "sessions",
    sidebarSections: { project: true, drawing: false, sessions: true }
  });
});

test("an early v3 record without an artifact share reads as the default share", () => {
  const values = new Map<string, string>([["dwg.workspace-preferences.v3", JSON.stringify({
    theme: "dark",
    artifactWidth: 998,
    sidebarWidth: 240,
    sidebarCollapsed: false,
    sidebarTab: "project",
    sidebarSections: { project: true, drawing: true, sessions: true }
  })]]);
  const store = createWorkspacePreferencesStore({
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value)
  });
  assert.equal(store.load().artifactShare, null);
  assert.equal(store.load().theme, "dark");
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
    artifactShare: null,
    sidebarWidth: 240,
    sidebarCollapsed: false,
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
