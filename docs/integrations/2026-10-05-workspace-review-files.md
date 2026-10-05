# Workspace review file inventory

Scope: every changed path in `1c19a332..60e4c35b`, plus the fixes described in the companion review. This table records per-file static inventory/import-boundary checks, not a claim that every interaction or every line has been exhaustively verified. TypeScript covers the native app; runtime checks cover the named browser/backend cases.

| File | Lines/state | Check |
|---|---|---|
| `.gitignore` | 97 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/api/routes_workspace.py` | 61 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/api/routes_workspace_catalog.py` | 102 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/api/routes_workspace_sessions.py` | 37 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/main.py` | 60 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/modules/workspace/catalog.py` | 87 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/modules/workspace/sessions.py` | 51 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/modules/workspace/settings.py` | 36 | Inventory/import-boundary scan; see semantic findings |
| `backend/app/schemas/workspace.py` | 45 | Inventory/import-boundary scan; see semantic findings |
| `backend/tests/test_workspace_catalog.py` | 57 | Inventory/import-boundary scan; see semantic findings |
| `backend/tests/test_workspace_sessions.py` | 38 | Inventory/import-boundary scan; see semantic findings |
| `backend/tests/test_workspace_settings.py` | 40 | Inventory/import-boundary scan; see semantic findings |
| `bun.lock` | 2339 | Inventory/import-boundary scan; see semantic findings |
| `docs/integrations/2026-10-05-native-session-history.md` | 11 | Inventory/import-boundary scan; see semantic findings |
| `docs/integrations/2026-10-05-native-workspace-components.md` | 33 | Inventory/import-boundary scan; see semantic findings |
| `docs/integrations/2026-10-05-workspace-structure-plan.md` | 25 | Inventory/import-boundary scan; see semantic findings |
| `docs/integrations/native-editor-route-ledger.md` | 58 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/app/(workspace)/build/page.tsx` | 3 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/app/(workspace)/gallery/page.tsx` | 3 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/app/(workspace)/history/page.tsx` | 4 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/app/(workspace)/layout.tsx` | 6 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/app/(workspace)/settings/page.tsx` | 3 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/app/api/v1/workspace/[...path]/route.ts` | 18 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/WorkspaceLayout.tsx` | 31 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/WorkspaceProviders.tsx` | 38 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/WorkspaceSidebar.tsx` | 64 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/language.ts` | 19 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/locales/en-US.json` | 198 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/locales/ko-KR.json` | 198 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/theme/constants.ts` | 46 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/theme/types.ts` | 21 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/theme/useTheme.ts` | 61 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/components/workspace/workspace.css` | 556 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/elements/workspace/Badge.tsx` | 29 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/elements/workspace/Button.tsx` | 47 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/elements/workspace/Card.tsx` | 19 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/elements/workspace/Input.tsx` | 24 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/elements/workspace/Toggle.tsx` | 29 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/elements/workspace/index.ts` | 5 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/agents/AgentCard.tsx` | 23 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/agents/AgentDetailPanel.tsx` | 26 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/agents/AgentsPage.tsx` | 33 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/GalleryPage.tsx` | 107 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/api.ts` | 22 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/components/ComponentCard.tsx` | 65 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/components/GalleryCard.tsx` | 106 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/components/GalleryDetail.tsx` | 424 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/components/GalleryImportDialog.tsx` | 135 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/components/GallerySyncDialog.tsx` | 97 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/components/index.ts` | 4 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/gallery/hooks/useGallery.ts` | 31 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/history/HistoryPage.tsx` | 194 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/history/components/MessageBubble.tsx` | 115 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/history/components/RunCard.tsx` | 78 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/history/components/SessionCard.tsx` | 60 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/history/components/SessionDetailPanel.tsx` | 107 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/history/components/index.ts` | 2 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/ExtendedRegulations.tsx` | 123 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/LandInfoCard.tsx` | 98 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/LandSearchForm.tsx` | 123 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/LandStatsPanel.tsx` | 50 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/LawArticleList.tsx` | 92 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/RegulationSummary.tsx` | 122 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/land/components/RestrictionsList.tsx` | 37 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/model-registry/index.ts` | 8 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/model-registry/model-registry.constants.ts` | 236 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/model-registry/model-registry.types.ts` | 25 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/model-registry/model-registry.utils.ts` | 40 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/sessions/api.ts` | 14 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/sessions/hooks/useSessions.ts` | 22 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/SettingsPage.tsx` | 23 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/api/settings.ts` | 7 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/ApiKeysCard.tsx` | 27 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/AppearanceCard.tsx` | 95 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/EngineConnectionCard.tsx` | 42 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/EnvironmentVariableRow.tsx` | 97 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/EnvironmentVariablesCard.tsx` | 244 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/FontScaleControl.tsx` | 74 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/components/UISettingsCard.tsx` | 206 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/hooks/useHealth.ts` | 15 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/hooks/useSettings.ts` | 21 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/model/font-scale-constants.ts` | 6 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/model/font-scale.ts` | 7 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/model/settings-store.ts` | 36 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/settings/model/types.ts` | 21 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/AgentFlow.tsx` | 346 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/AgentFlowToolbar.tsx` | 179 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/AgentNode.tsx` | 136 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/CustomEdge.tsx` | 107 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/index.ts` | 8 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/layout-generator.ts` | 747 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/agentflow/types.ts` | 355 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/AgentAddDialog.tsx` | 212 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/AgentConfigPanel.tsx` | 185 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/EditableAgentPanel.tsx` | 183 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/JsonView.tsx` | 182 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/ModelSelector.tsx` | 185 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/PatternSelector.tsx` | 85 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/components/TerminationEditor.tsx` | 231 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/hooks/useTeamEditor.ts` | 214 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-builder/index.ts` | 14 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/TeamsPage.tsx` | 657 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/api.ts` | 52 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/SortableChip.tsx` | 40 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/TeamCard.tsx` | 79 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/TeamCreateDialog.tsx` | 155 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/TeamDeleteDialog.tsx` | 104 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/UnsavedChangesDialog.tsx` | 84 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/ValidationBadge.tsx` | 33 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/components/index.ts` | 2 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/hooks/useTeams.ts` | 75 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/hooks/useUnsavedChanges.ts` | 62 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/model/presentation.ts` | 30 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/team-templates/model/team-store.ts` | 16 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/features/workspace/WorkspaceLayout.tsx` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/locales/en-US.json` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/locales/ko-KR.json` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/ui/Badge.tsx` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/ui/Button.tsx` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/ui/Card.tsx` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/ui/Input.tsx` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/ui/index.ts` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/features/workspace/workspace.css` | removed/moved | Previous-path removal checked |
| `frontend/app/editor/lib/backend-request.ts` | 30 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/lib/contracts/workspace.ts` | 558 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/lib/display-error.ts` | 4 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/lib/workspace-request.ts` | 16 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/package.json` | 66 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/playwright.migration.config.cjs` | 3 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/tests/catalog-routes.spec.cjs` | 62 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/tests/history-route.spec.cjs` | 74 | Inventory/import-boundary scan; see semantic findings |
| `frontend/app/editor/tests/settings-route.spec.cjs` | 52 | Inventory/import-boundary scan; see semantic findings |
