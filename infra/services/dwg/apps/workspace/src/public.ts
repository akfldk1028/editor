/**
 * Public entry of the CAD workspace. A host frame (the editor shell) mounts
 * `DwgWorkspaceProvider` once and places the pieces in its own slots; the
 * standalone app (`DwgWorkspace`) composes the same pieces in a fixed frame.
 */
export { App as DwgWorkspace } from "./app/App.js";
export { DwgWorkspaceProvider, useDwgWorkspace } from "./app/workspace/DwgWorkspaceProvider.js";
export type { DwgWorkspaceState, DwgSidebarTab } from "./app/workspace/DwgWorkspaceProvider.js";
export { DwgSidebar, DwgSidebarActions } from "./app/workspace/DwgSidebar.js";
export { DwgConversation, DwgConversationActions, DwgConversationHeading, DwgSettings } from "./app/workspace/DwgConversation.js";
export { dwgArtifactTabs, useDwgArtifact } from "./app/workspace/DwgArtifact.js";
export type { DwgArtifactTab, DwgArtifactView } from "./app/workspace/DwgArtifact.js";
