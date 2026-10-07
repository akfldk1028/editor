import { useEffect, useMemo, useRef, useState } from "react";

import {
  clampSidebarWidth,
  createWorkspacePreferencesStore,
  defaultWorkspacePreferences,
  resolveTheme,
  type ThemePreference,
  type WorkspacePreferences
} from "./workspacePreferences";

export function useWorkspacePreferences() {
  const [browserStore] = useState(createBrowserStore);
  const [preferences, setPreferences] = useState<WorkspacePreferences>(
    () => browserStore?.load() ?? defaultWorkspacePreferences
  );
  const [systemDark, setSystemDark] = useState(
    () => typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
  );

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  /** The newest preferences, so a drag that ends can save what its last move set. */
  const latest = useRef(preferences);

  /** `save: false` only updates the view (a resize drag in progress); `persist()` saves it at the end. */
  function update(next: WorkspacePreferences, save = true) {
    latest.current = next;
    setPreferences(next);
    if (save) browserStore?.save(next);
  }

  return useMemo(() => ({
    preferences,
    resolvedTheme: resolveTheme(preferences.theme, systemDark),
    setTheme(theme: ThemePreference) {
      update({ ...preferences, theme });
    },
    setArtifactShare(artifactShare: number, save = true) {
      update({ ...latest.current, artifactShare }, save);
    },
    setSidebarWidth(sidebarWidth: number, save = true) {
      update({ ...latest.current, sidebarWidth: clampSidebarWidth(sidebarWidth) }, save);
    },
    persist() {
      browserStore?.save(latest.current);
    },
    setSidebarCollapsed(sidebarCollapsed: boolean) {
      update({ ...preferences, sidebarCollapsed });
    }
  }), [preferences, systemDark]);
}

function createBrowserStore() {
  try {
    return typeof window === "undefined"
      ? null
      : createWorkspacePreferencesStore(window.localStorage);
  } catch {
    return null;
  }
}
