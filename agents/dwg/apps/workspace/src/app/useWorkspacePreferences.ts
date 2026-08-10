import { useEffect, useMemo, useState } from "react";

import {
  clampSidebarWidth,
  createWorkspacePreferencesStore,
  defaultWorkspacePreferences,
  resolveTheme,
  type SidebarTab,
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

  function update(next: WorkspacePreferences) {
    setPreferences(next);
    browserStore?.save(next);
  }

  return useMemo(() => ({
    preferences,
    resolvedTheme: resolveTheme(preferences.theme, systemDark),
    setTheme(theme: ThemePreference) {
      update({ ...preferences, theme });
    },
    setArtifactWidth(artifactWidth: number) {
      update({ ...preferences, artifactWidth });
    },
    setSidebarWidth(sidebarWidth: number) {
      update({ ...preferences, sidebarWidth: clampSidebarWidth(sidebarWidth) });
    },
    setSidebarTab(sidebarTab: SidebarTab) {
      update({ ...preferences, sidebarTab });
    },
    toggleSection(section: keyof WorkspacePreferences["sidebarSections"]) {
      update({
        ...preferences,
        sidebarSections: {
          ...preferences.sidebarSections,
          [section]: !preferences.sidebarSections[section]
        }
      });
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
