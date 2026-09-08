export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export type SidebarTab = "project" | "sessions" | "skills";

export interface WorkspacePreferences {
  theme: ThemePreference;
  artifactWidth: number;
  sidebarWidth: number;
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

const storageKey = "dwg.workspace-preferences.v2";
const legacyStorageKey = "dwg.workspace-preferences.v1";
const defaultSidebarWidth = 320;
const minimumSidebarWidth = 280;
const maximumSidebarWidth = 420;
const conversationMinimumWidth = 500;
const separatorWidth = 7;
const artifactMinimumWidth = 520;

export const defaultWorkspacePreferences: WorkspacePreferences = {
  theme: "system",
  artifactWidth: artifactMinimumWidth,
  sidebarWidth: defaultSidebarWidth,
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

export function clampArtifactWidth(
  viewportWidth: number,
  desiredWidth: number,
  sidebarVisible: boolean,
  preferredSidebarWidth = defaultSidebarWidth
) {
  const availableWidth =
    viewportWidth -
    (sidebarVisible ? clampSidebarWidth(preferredSidebarWidth) : 0) -
    conversationMinimumWidth -
    (sidebarVisible ? separatorWidth * 2 : separatorWidth);
  const maximumWidth = Math.max(0, availableWidth);
  const minimumWidth = Math.min(artifactMinimumWidth, maximumWidth);
  return Math.min(maximumWidth, Math.max(minimumWidth, desiredWidth));
}

export function clampSidebarWidth(desiredWidth: number) {
  return Math.min(maximumSidebarWidth, Math.max(minimumSidebarWidth, desiredWidth));
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
        const legacyRaw = storage.getItem(legacyStorageKey);
        if (!legacyRaw) return memoryValue;
        const migrated = migrateLegacyPreferences(legacyRaw);
        if (!migrated) {
          memoryValue = defaultWorkspacePreferences;
          return memoryValue;
        }
        this.save(migrated);
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

function migrateLegacyPreferences(raw: string): WorkspacePreferences | null {
  try {
    const legacy = validateLegacyPreferences(JSON.parse(raw));
    return legacy && {
      ...legacy,
      sidebarWidth: defaultSidebarWidth,
      sidebarTab: "project"
    };
  } catch {
    return null;
  }
}

function validateLegacyPreferences(value: unknown): Omit<WorkspacePreferences, "sidebarWidth" | "sidebarTab"> | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const sections = record.sidebarSections;
  if (
    (record.theme !== "light" &&
      record.theme !== "dark" &&
      record.theme !== "system") ||
    typeof record.artifactWidth !== "number" ||
    !Number.isFinite(record.artifactWidth) ||
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
    artifactWidth: record.artifactWidth,
    sidebarSections: {
      project: sectionRecord.project,
      drawing: sectionRecord.drawing,
      sessions: sectionRecord.sessions
    }
  };
}

function validatePreferences(value: unknown): WorkspacePreferences | null {
  const legacy = validateLegacyPreferences(value);
  if (!legacy) return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.sidebarWidth !== "number" ||
    !Number.isFinite(record.sidebarWidth) ||
    (record.sidebarTab !== "project" &&
      record.sidebarTab !== "sessions" &&
      record.sidebarTab !== "skills")
  ) {
    return null;
  }
  return {
    ...legacy,
    sidebarWidth: clampSidebarWidth(record.sidebarWidth),
    sidebarTab: record.sidebarTab
  };
}
