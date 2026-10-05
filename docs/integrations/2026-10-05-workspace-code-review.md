# Workspace integration code review

Scope: `1c19a332..60e4c35b`, 132 changed paths (123 existing files and 9 removed/moved paths). The [file inventory](2026-10-05-workspace-review-files.md) records every path and its static import-boundary check. Detailed semantic review focused on mutations, draft state, navigation, JSON inputs, API/storage contracts and history identity. This is not a claim of exhaustive verification of every branch in every original component.

## Findings and fixes

| Severity | Finding | Resolution and evidence |
|---|---|---|
| High | Saving UI preferences reset an independently edited environment draft because a previous mutation remained successful and any settings-cache change rehydrated the environment card. | Removed the cache-driven re-sync. Browser regression first observed `saved-value` replacing `unsaved-value`; now the pending edit survives. |
| High | Team POST accepted `participants` as a string, null participants, object labels and blank providers. The builder assumes a list of component objects. JSON Apply likewise accepted malformed local drafts. | Added domain-owned recursive shape validation to team/gallery writes and a client guard before applying JSON. Backend regression first returned 201, now 422; browser rejects the malformed draft without closing its JSON editor. This is shape validation, not provider execution. |
| High | Closing a team panel or selecting another team silently discarded a dirty draft; only route links were guarded. | Internal panel/team/exit-edit actions use the same explicit stay/leave dialog. Browser close-panel regression first failed because no dialog existed; now passes. Delete cancellation no longer clears the selected panel; deletion success has a separate callback. |
| High | Editing one child of an AND termination rewrote the parent as OR, changing stopping behavior. | Preserve the original AND/OR component and its configuration when editing children. Real-backend browser regression first saved OrTermination, then passed with AndTermination and the edited limit intact. |
| Medium | History detail retained the previous session's two-step delete confirmation when another session occupied the same component position. | Key detail panels by session identity. Browser regression checks that the newly selected session is not already confirmed. |
| Medium | History divided a seconds-valued run duration by 1000. | Render seconds directly. Source evidence: original Studio `teammanager/teammanager.py` emits `duration=time.time() - start_time`. Browser fixture verifies 12.5 seconds displays as 12.5s. |
| Medium | Undo/redo mutated history refs from React state updaters; repeated updater evaluation could mutate shared history. Save completion also cleared edits made after submission. | History/future now belong to immutable draft state. Dirty state compares against the saved baseline. Save completion clears only the submitted draft identity; newer edits retain the returned server version. Undo/redo boundary behavior passes browser checks; StrictMode-specific failure was identified by inspection, not claimed as independently reproduced. |

## Validation

- TypeScript noEmit: passed after final source edits.
- Workspace settings/catalog/sessions plus design workspace backend: 14 passed.
- Full native browser regression with `EDITOR_TEST_URL=http://127.0.0.1:3003` and `EDITOR_VERIFY_LIVE_VWORLD=1`: 19 passed, exit 0.
- Additional AND-preservation browser regression: failed before the fix, then 1 passed after the final termination edit. The full suite was not repeated after this isolated edit.
- One initial full-suite launch omitted EDITOR_TEST_URL and navigated to `undefined/agents`; it was stopped and rerun with the required environment. That was a test invocation error, not an application failure.
- No primitive-to-feature/API imports or workspace-domain-to-FastAPI imports were found by the per-file boundary scan. Core/viewer packages were not changed. No automatic bulk lint rewrite was used.

## Remaining limits

The stored template's Run button still targets the unported Playground. Gallery live component tests, actual owner/project-bound session execution, MCP/deployment and the previously listed design execution flows remain unfinished. Configuration/provider validity, actual model calls, arbitrary gallery compatibility, cross-window settings editing, all keyboard/accessibility paths, clean dependency installation and every original graph-layout branch are not proven by these checks. The dependency recovery/lock mismatch recorded in the previous checkpoint remains.

The repository's advertised `.agents/skills/review-architecture/SKILL.md` was absent, and a search of local skill roots did not locate it. Review used the available AGENTS.md and architecture documents directly; no nonexistent skill execution is claimed. Existing source repositories and runtime evidence were preserved.
