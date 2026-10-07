import { clampArtifactShare, clampSidebarWidth, layout } from "./layoutModes";

export { clampSidebarWidth } from "./layoutModes";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export type SidebarTab = "project" | "sessions" | "skills";

export interface WorkspacePreferences {
  theme: ThemePreference;
  /**
   * Preferred artifact share of the row it shares with the conversation
   * (0..1); null follows the default. A share, not px, so a width chosen on
   * a large screen still leaves the conversation room on a smaller one.
   */
  artifactShare: number | null;
  sidebarWidth: number;
  /** Wide layout only: the sidebar is folded into its rail. */
  sidebarCollapsed: boolean;
  /**
   * The DWG sidebar section and section folds from before the shell owned
   * these preferences. Kept so stored records still validate; the shell does
   * not read them.
   */
  sidebarTab: SidebarTab;
  sidebarSections: {
    project: boolean;
    drawing: boolean;
    sessions: boolean;
  };
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const storageKey = "dwg.workspace-preferences.v3";
/** Older keys, newest first. Their artifact widths used the 520px-floor model and are dropped. */
const legacyStorageKeys = ["dwg.workspace-preferences.v2", "dwg.workspace-preferences.v1"] as const;

export const defaultWorkspacePreferences: WorkspacePreferences = {
  theme: "system",
  artifactShare: null,
  sidebarWidth: layout.sidebar.default,
  sidebarCollapsed: false,
  sidebarTab: "project",
  sidebarSections: {
    project: true,
    drawing: true,
    sessions: true
  }
};

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean
): ResolvedTheme {
  if (preference === "system") {
    return systemPrefersDark ? "dark" : "light";
  }
  return preference;
}

export function createWorkspacePreferencesStore(storage: StorageLike) {
  let memoryValue = defaultWorkspacePreferences;
  let legacyMigrationAttempted = false;

  return {
    load(): WorkspacePreferences {
      try {
        const raw = storage.getItem(storageKey);
        if (raw) {
          memoryValue = parseCurrentPreferences(raw) ?? defaultWorkspacePreferences;
          return memoryValue;
        }

        if (legacyMigrationAttempted) return memoryValue;
        legacyMigrationAttempted = true;
        for (const key of legacyStorageKeys) {
          const legacyRaw = storage.getItem(key);
          if (!legacyRaw) continue;
          const migrated = migrateLegacyPreferences(legacyRaw);
          if (!migrated) {
            memoryValue = defaultWorkspacePreferences;
            return memoryValue;
          }
          this.save(migrated);
          return memoryValue;
        }
        return memoryValue;
      } catch {
        return memoryValue;
      }
    },
    save(preferences: WorkspacePreferences) {
      memoryValue = preferences;
      try {
        storage.setItem(storageKey, JSON.stringify(preferences));
      } catch {
        // Restricted browsers still keep preferences for the current runtime.
      }
    }
  };
}

function parseCurrentPreferences(raw: string): WorkspacePreferences | null {
  try {
    return validatePreferences(JSON.parse(raw));
  } catch {
    return null;
  }
}

/** v1 and v2 share theme and sections; v2 adds a sidebar width and tab. */
function migrateLegacyPreferences(raw: string): WorkspacePreferences | null {
  try {
    const value: unknown = JSON.parse(raw);
    const base = validateBase(value);
    if (!base) return null;
    const record = value as Record<string, unknown>;
    return {
      ...base,
      artifactShare: null,
      sidebarWidth: typeof record.sidebarWidth === "number" && Number.isFinite(record.sidebarWidth)
        ? clampSidebarWidth(record.sidebarWidth)
        : layout.sidebar.default,
      sidebarCollapsed: false,
      sidebarTab: isSidebarTab(record.sidebarTab) ? record.sidebarTab : "project"
    };
  } catch {
    return null;
  }
}

function isSidebarTab(value: unknown): value is SidebarTab {
  return value === "project" || value === "sessions" || value === "skills";
}

function validateBase(value: unknown): Pick<WorkspacePreferences, "theme" | "sidebarSections"> | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const sections = record.sidebarSections;
  if (
    (record.theme !== "light" &&
      record.theme !== "dark" &&
      record.theme !== "system") ||
    !sections ||
    typeof sections !== "object"
  ) {
    return null;
  }
  const sectionRecord = sections as Record<string, unknown>;
  if (
    typeof sectionRecord.project !== "boolean" ||
    typeof sectionRecord.drawing !== "boolean" ||
    typeof sectionRecord.sessions !== "boolean"
  ) {
    return null;
  }
  return {
    theme: record.theme,
    sidebarSections: {
      project: sectionRecord.project,
      drawing: sectionRecord.drawing,
      sessions: sectionRecord.sessions
    }
  };
}

function validatePreferences(value: unknown): WorkspacePreferences | null {
  const base = validateBase(value);
  if (!base) return null;
  const record = value as Record<string, unknown>;
  // Absent (an early v3 that stored px) reads as the default share.
  const share = record.artifactShare ?? null;
  if (
    (share !== null && (typeof share !== "number" || !Number.isFinite(share))) ||
    typeof record.sidebarWidth !== "number" ||
    !Number.isFinite(record.sidebarWidth) ||
    typeof record.sidebarCollapsed !== "boolean" ||
    !isSidebarTab(record.sidebarTab)
  ) {
    return null;
  }
  return {
    ...base,
    artifactShare: share === null ? null : clampArtifactShare(share),
    sidebarWidth: clampSidebarWidth(record.sidebarWidth),
    sidebarCollapsed: record.sidebarCollapsed,
    sidebarTab: record.sidebarTab
  };
}

