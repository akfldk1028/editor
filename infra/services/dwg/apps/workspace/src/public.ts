/**
 * Public entry of the CAD workspace. A host frame (the editor shell) mounts
 * `DwgWorkspaceProvider` once and places the pieces in its own slots; the
 * standalone app (`DwgWorkspace`) composes the same pieces in a fixed frame.
 */
export { App as DwgWorkspace } from "./app/App.tsx";
export { DwgWorkspaceProvider, useDwgWorkspace } from "./app/workspace/DwgWorkspaceProvider.tsx";
export type { DwgWorkspaceState, DwgSidebarTab } from "./app/workspace/DwgWorkspaceProvider.tsx";
export { DwgSidebar, DwgSidebarActions } from "./app/workspace/DwgSidebar.tsx";
export { DwgConversation, DwgConversationActions, DwgConversationHeading, DwgSettings } from "./app/workspace/DwgConversation.tsx";
export { dwgArtifactTabs, useDwgArtifact } from "./app/workspace/DwgArtifact.tsx";
export type { DwgArtifactTab, DwgArtifactView } from "./app/workspace/DwgArtifact.tsx";
